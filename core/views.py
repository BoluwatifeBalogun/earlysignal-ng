"""Application tier: request handling, validation, access control."""
import csv
import tempfile
from collections import Counter, defaultdict
from functools import wraps
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from ml import pipeline

from . import nigeria
from .forms import (ImportForm, LoginForm, OwnPasswordForm, RecordForm, StudentForm,
                    TrainingUploadForm, UserCreateForm, UserEditForm)
from .models import AcademicRecord, Prediction, Student, User
from .services import predictor, records as record_service

RISK_ORDER = [Prediction.HIGH, Prediction.MEDIUM, Prediction.LOW]


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_administrator:
            return render(request, "core/forbidden.html", status=403)
        return view(request, *args, **kwargs)
    return wrapper


def _share(part, whole):
    return round(part / whole * 100) if whole else 0


# ---------------------------------------------------------------- public

def landing(request):
    metrics = predictor.load_metrics()
    selected = metrics["models"][metrics["selected"]] if metrics else None
    return render(request, "core/landing.html", {
        "metrics": metrics,
        "selected": selected,
        "zones": nigeria.ZONES,
        "state_count": len(nigeria.STATES),
    })


MAX_SIGN_IN_ATTEMPTS = 5
SIGN_IN_LOCK_SECONDS = 15 * 60


class SignIn(LoginView):
    """Sign in, with a pause after repeated wrong passwords for one username."""

    template_name = "core/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def _key(self):
        return "signin-fail:" + (self.request.POST.get("username") or "").strip().lower()[:150]

    def post(self, request, *args, **kwargs):
        if cache.get(self._key(), 0) >= MAX_SIGN_IN_ATTEMPTS:
            form = self.get_form()
            form.is_valid()
            form.errors.clear()
            form.add_error(None, "Too many wrong attempts for this username. Wait 15 minutes, "
                                 "or ask an administrator to reset the password.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._key()
        cache.set(key, cache.get(key, 0) + 1, SIGN_IN_LOCK_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._key())
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from django.conf import settings
        ctx["show_demo"] = settings.DEBUG and User.objects.filter(username="lecturer").exists()
        return ctx


@require_GET
def api_try(request):
    """Run the deployed model on three numbers. Nothing is stored, and no
    student is identified, so the public page and the what-if panel share it."""
    try:
        result = predictor.predict(
            request.GET.get("ca"), request.GET.get("att"), request.GET.get("prev"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except predictor.ModelNotTrained as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    return JsonResponse({k: result[k] for k in (
        "percent", "outcome", "risk", "baseline_percent", "factors", "advice", "cautions",
        "model_name")})


# ---------------------------------------------------------------- dashboard

@login_required
def dashboard(request):
    zone_filter = request.GET.get("zone", "")
    students = Student.objects.all()
    if zone_filter in nigeria.ZONE_NAMES:
        students = students.filter(zone=zone_filter)
    else:
        zone_filter = ""

    predictions = (Prediction.objects.select_related("record__student")
                   .filter(record__student__in=students).order_by("record__created_at", "id"))
    latest = {}
    for p in predictions:  # last one wins: each student's current signal
        latest[p.record.student_id] = p
    current = list(latest.values())
    total = len(current)
    risk_counts = Counter(p.risk_category for p in current)

    by_zone = defaultdict(Counter)
    by_type = defaultdict(Counter)
    for p in current:
        s = p.record.student
        by_zone[s.zone][p.risk_category] += 1
        by_type[s.institution_type][p.risk_category] += 1

    def rows(groups, names):
        out = []
        for name in names:
            c = groups.get(name, Counter())
            n = sum(c.values())
            out.append({
                "name": name, "total": n,
                "high": c[Prediction.HIGH], "medium": c[Prediction.MEDIUM], "low": c[Prediction.LOW],
                "high_pct": _share(c[Prediction.HIGH], n),
                "medium_pct": _share(c[Prediction.MEDIUM], n),
                "low_pct": _share(c[Prediction.LOW], n),
            })
        return out

    watchlist = sorted(
        (p for p in current if p.risk_category == Prediction.HIGH),
        key=lambda p: -p.probability)[:8]
    awaiting = AcademicRecord.objects.filter(
        prediction__isnull=True, student__in=students).count()

    return render(request, "core/dashboard.html", {
        "zone_filter": zone_filter,
        "zone_names": nigeria.ZONE_NAMES,
        "student_count": students.count(),
        "record_count": AcademicRecord.objects.filter(student__in=students).count(),
        "prediction_total": total,
        "awaiting": awaiting,
        "risk": [
            {"name": r, "count": risk_counts[r], "pct": _share(risk_counts[r], total)}
            for r in RISK_ORDER
        ],
        "high_count": risk_counts[Prediction.HIGH],
        "high_pct": _share(risk_counts[Prediction.HIGH], total),
        "zone_rows": rows(by_zone, nigeria.ZONE_NAMES),
        "type_rows": rows(by_type, nigeria.INSTITUTION_TYPES),
        "watchlist": watchlist,
        "recent": Prediction.objects.select_related("record__student")
                  .filter(record__student__in=students)[:6],
    })


# ---------------------------------------------------------------- students

@login_required
def student_list(request):
    q = request.GET.get("q", "").strip()
    zone = request.GET.get("zone", "")
    inst_type = request.GET.get("type", "")
    qs = Student.objects.annotate(n_records=Count("records")).order_by("full_name", "id")
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(student_id__icontains=q)
                       | Q(institution__icontains=q) | Q(department__icontains=q))
    if zone in nigeria.ZONE_NAMES:
        qs = qs.filter(zone=zone)
    if inst_type in nigeria.INSTITUTION_TYPES:
        qs = qs.filter(institution_type=inst_type)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    latest = {}
    for p in (Prediction.objects.filter(record__student__in=list(page.object_list))
              .select_related("record").order_by("record__created_at", "id")):
        latest[p.record.student_id] = p
    for s in page.object_list:
        s.signal = latest.get(s.id)
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "core/student_list.html", {
        "page": page, "q": q, "zone": zone, "type": inst_type,
        "zone_names": nigeria.ZONE_NAMES, "types": nigeria.INSTITUTION_TYPES,
        "total": qs.count(), "querystring": params.urlencode(),
        "filtered": bool(q or zone or inst_type),
    })


def _student_form_context(form, title, student=None):
    return {
        "form": form, "title": title, "student": student,
        "institutions": sorted({i[0] for i in nigeria.INSTITUTIONS}
                               | set(Student.objects.values_list("institution", flat=True))),
        "departments": sorted(set(nigeria.DEPARTMENTS)
                              | set(Student.objects.values_list("department", flat=True))),
        "levels_by_type": nigeria.LEVELS,
        "institution_lookup": {i[0]: {"type": i[1], "state": i[2]} for i in nigeria.INSTITUTIONS},
    }


@login_required
def student_create(request):
    form = StudentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        student = form.save()
        messages.success(request, f"Added {student.full_name}. Now enter an academic record.")
        return redirect("record_create", pk=student.pk)
    return render(request, "core/student_form.html", _student_form_context(form, "Add a student"))


@admin_required
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = StudentForm(request.POST or None, instance=student)
    if request.method == "POST" and form.is_valid():
        form.save()
        for record in student.records.all():  # scale may have changed
            record.save()
        messages.success(request, "Saved changes to the student's details.")
        return redirect("student_detail", pk=student.pk)
    return render(request, "core/student_form.html",
                  _student_form_context(form, "Correct student details", student))


def _band_lines():
    """Band edges for the sparkline (viewBox y = 70 - percent * 0.6)."""
    if not predictor.model_ready():
        return None
    t = predictor.band_thresholds()
    return {**t, "flag_y": round(70 - t["flag_from"] * 0.6, 1), "high_y": round(70 - t["high_from"] * 0.6, 1)}


def _band_evidence(band):
    """How students in this band actually turned out on the held-out test set."""
    metrics = predictor.load_metrics() or {}
    for row in metrics.get("calibration", {}).get("bands", []):
        if row["band"] == band and row["observed"] is not None:
            return {"n": row["n"], "pct": round(row["observed"] * 100)}
    return None


@login_required
def student_detail(request, pk):
    student = get_object_or_404(Student, pk=pk)
    records = list(student.records.select_related("prediction", "entered_by").order_by("created_at"))
    points = [
        {"label": f"{r.session} {r.semester}", "pct": r.prediction.percent,
         "risk": r.prediction.risk_category}
        for r in records if r.has_prediction
    ]
    # Sparkline geometry for the signal over time (viewBox 0 0 300 80).
    n = len(points)
    for i, pt in enumerate(points):
        pt["x"] = round(20 + (260 * i / (n - 1) if n > 1 else 130), 1)
        pt["y"] = round(70 - pt["pct"] * 0.6, 1)
    return render(request, "core/student_detail.html", {
        "bands": _band_lines(),
        "student": student,
        "records": list(reversed(records)),
        "points": points,
        "polyline": " ".join(f"{p['x']},{p['y']}" for p in points),
        "current": records[-1].prediction if records and records[-1].has_prediction else None,
    })


# ---------------------------------------------------------------- records

@login_required
def record_create(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = RecordForm(request.POST or None, student=student)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.student = student
        record.entered_by = request.user
        record.save()
        if "predict" in request.POST:
            try:
                record_service.store_prediction(record, request.user)
                messages.success(request, "Saved the record and generated a prediction.")
            except predictor.ModelNotTrained as exc:
                messages.error(request, f"Saved the record, but no prediction was made. {exc}")
        else:
            messages.success(request, "Saved the record. Request a prediction when you are ready.")
        return redirect("record_detail", pk=record.pk)
    return render(request, "core/record_form.html", {
        "form": form, "student": student, "title": "Enter an academic record",
        "requirement": nigeria.ATTENDANCE_REQUIREMENT,
    })


@admin_required
def record_edit(request, pk):
    record = get_object_or_404(AcademicRecord.objects.select_related("student"), pk=pk)
    before = {"ca_score": str(record.ca_score), "attendance_rate": str(record.attendance_rate),
              "previous_gpa": str(record.previous_gpa)}
    old = getattr(record, "prediction", None)
    superseded = None
    if old:
        superseded = {**before, "percent": old.percent, "risk": old.risk_category,
                      "date": timezone.localtime(old.date_generated).strftime("%d %b %Y, %H:%M")}
    form = RecordForm(request.POST or None, instance=record)
    if request.method == "POST" and form.is_valid():
        record = form.save(commit=False)
        record.corrected_by = request.user
        record.corrected_at = timezone.now()
        record.save()
        if old and predictor.model_ready():
            prediction = record_service.store_prediction(record, request.user)
            # Keep what the system said before the correction, for the audit trail.
            prediction.explanation["superseded"] = superseded
            prediction.save(update_fields=["explanation"])
            messages.success(request, "Corrected the record and refreshed its prediction.")
        else:
            messages.success(request, "Corrected the record.")
        return redirect("record_detail", pk=record.pk)
    return render(request, "core/record_form.html", {
        "form": form, "student": record.student, "record": record,
        "title": "Correct an academic record", "requirement": nigeria.ATTENDANCE_REQUIREMENT,
    })


@admin_required
@require_POST
def record_delete(request, pk):
    record = get_object_or_404(AcademicRecord, pk=pk)
    student_pk = record.student_id
    record.delete()
    messages.success(request, "Deleted the record and its prediction.")
    return redirect("student_detail", pk=student_pk)


@login_required
def record_detail(request, pk):
    record = get_object_or_404(
        AcademicRecord.objects.select_related("student", "entered_by", "corrected_by"), pk=pk)
    prediction = getattr(record, "prediction", None)
    if prediction and predictor.model_ready():
        prediction = record_service.ensure_explanation(prediction)
    factors = []
    if prediction:
        factors = prediction.explanation.get("factors", [])
        peak = max((abs(f["points"]) for f in factors), default=1) or 1
        for f in factors:
            f["width"] = max(round(abs(f["points"]) / peak * 100), 3)
    return render(request, "core/record_detail.html", {
        "record": record, "student": record.student, "prediction": prediction,
        "factors": factors,
        "advice": prediction.explanation.get("advice", []) if prediction else [],
        "baseline_pct": round(prediction.explanation.get("baseline", 0) * 100) if prediction else 0,
        "cautions": prediction.explanation.get("cautions", []) if prediction else [],
        "superseded": prediction.explanation.get("superseded") if prediction else None,
        "evidence": _band_evidence(prediction.risk_category) if prediction else None,
        "thresholds": predictor.band_thresholds() if predictor.model_ready() else None,
        "requirement": nigeria.ATTENDANCE_REQUIREMENT,
        "gauge_offset": round(251.3 * (1 - prediction.probability), 1) if prediction else 251.3,
    })


@login_required
@require_POST
def record_predict(request, pk):
    record = get_object_or_404(AcademicRecord, pk=pk)
    try:
        record_service.store_prediction(record, request.user)
        messages.success(request, "Generated a prediction.")
    except predictor.ModelNotTrained as exc:
        messages.error(request, str(exc))
    return redirect("record_detail", pk=record.pk)


# ---------------------------------------------------------------- import

@login_required
def import_records(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        result = record_service.import_csv(
            form.cleaned_data["file"], request.user, form.cleaned_data["predict"])
        if result["fatal"]:
            form.add_error("file", result["fatal"])
            result = None
        else:
            form = ImportForm()
    return render(request, "core/import.html", {
        "form": form, "result": result, "columns": record_service.IMPORT_COLUMNS,
        "max_rows": record_service.MAX_IMPORT_ROWS,
    })


@login_required
def import_template(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="earlysignal_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(record_service.IMPORT_COLUMNS)
    writer.writerow(["F/HD/24/3210001", "Adaeze Okonkwo", "Yaba College of Technology",
                     "Polytechnic", "Lagos", "Computer Science", "HND 2", "2025/2026",
                     "First", "62.5", "88", "3.12"])
    writer.writerow(["UNN/2023/184220", "Ibrahim Danjuma", "University of Nigeria, Nsukka",
                     "University", "Enugu", "Statistics", "300 Level", "2025/2026",
                     "First", "41", "69", "2.45"])
    return response


# ---------------------------------------------------------------- history

def _history_queryset(request):
    qs = Prediction.objects.select_related("record__student", "requested_by")
    q = request.GET.get("q", "").strip()
    risk = request.GET.get("risk", "")
    zone = request.GET.get("zone", "")
    if q:
        qs = qs.filter(Q(record__student__full_name__icontains=q)
                       | Q(record__student__student_id__icontains=q)
                       | Q(record__student__institution__icontains=q))
    if risk in RISK_ORDER:
        qs = qs.filter(risk_category=risk)
    if zone in nigeria.ZONE_NAMES:
        qs = qs.filter(record__student__zone=zone)
    return qs, q, risk, zone


@login_required
def history(request):
    qs, q, risk, zone = _history_queryset(request)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "core/history.html", {
        "page": page, "q": q, "risk": risk, "zone": zone, "risks": RISK_ORDER,
        "zone_names": nigeria.ZONE_NAMES, "total": qs.count(),
        "querystring": params.urlencode(), "filtered": bool(q or risk or zone),
    })


@login_required
def history_export(request):
    qs, *_ = _history_queryset(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="earlysignal_prediction_history.csv"'
    writer = csv.writer(response)

    def safe(value):
        """Spreadsheets run cells that start with = + - @ as formulas."""
        text = str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

    writer.writerow(["date_generated", "student_id", "full_name", "institution", "state", "zone",
                     "session", "semester", "ca_score", "attendance_rate", "previous_gpa",
                     "predicted_outcome", "risk_category", "chance_of_under_performing",
                     "model", "model_version", "requested_by"])
    for p in qs.iterator():
        r, s = p.record, p.record.student
        writer.writerow([
            timezone.localtime(p.date_generated).strftime("%Y-%m-%d %H:%M"), safe(s.student_id),
            safe(s.full_name), safe(s.institution),
            s.state, s.zone, r.session, r.semester, r.ca_score, r.attendance_rate, r.previous_gpa,
            p.predicted_outcome, p.risk_category, f"{p.probability:.4f}", p.model_name,
            p.model_version, p.requested_by.username if p.requested_by else "",
        ])
    return response


# ---------------------------------------------------------------- model

def _matrix(conf):
    total = sum(conf.values()) or 1
    return [
        {"key": "tn", "label": "Passed, predicted pass", "n": conf["tn"], "good": True},
        {"key": "fp", "label": "Passed, flagged anyway", "n": conf["fp"], "good": False},
        {"key": "fn", "label": "Under-performed, missed", "n": conf["fn"], "good": False},
        {"key": "tp", "label": "Under-performed, caught", "n": conf["tp"], "good": True},
    ], total


@login_required
def model_report(request):
    metrics = predictor.load_metrics()
    form = TrainingUploadForm()
    models = []
    if metrics:
        for name, res in metrics["models"].items():
            cells, total = _matrix(res["confusion"])
            for c in cells:
                c["pct"] = round(c["n"] / total * 100, 1)
            models.append({
                "name": name, "selected": name == metrics["selected"],
                "test": {k: round(v * 100, 1) for k, v in res["test"].items()},
                "cv": {k: {"mean": round(v["mean"] * 100, 1), "std": round(v["std"] * 100, 1),
                           "folds": [round(f * 100, 1) for f in v["folds"]]}
                       for k, v in res["cv"].items()},
                "cells": cells,
                "timing": res.get("timing"),
            })
        models.sort(key=lambda m: not m["selected"])
        for item in metrics["importance"]:
            item["pct"] = round(item["share"] * 100)
        for t in metrics["hypothesis"]["indicators"]:
            t["p_text"] = "< 0.001" if t["p_value"] < 0.001 else f"{t['p_value']:.3f}"
        metrics["baseline_pct"] = round(metrics["baseline"]["accuracy"] * 100, 1)
        metrics["data"]["under_pct"] = round(metrics["data"]["under_perform_share"] * 100, 1)
        perm = metrics["hypothesis"]["permutation"]
        perm["score_pct"] = round(perm["score"] * 100, 1)
        perm["shuffled_pct"] = round(perm["shuffled_mean"] * 100, 1)
        cal = metrics.get("calibration")
        if cal:
            cal["flag_pct"] = round(cal["flag_from"] * 100)
            cal["high_pct"] = round(cal["high_from"] * 100)
            for row in cal["reliability"]:
                row["predicted_pct"] = round(row["predicted"] * 100)
                row["observed_pct"] = round(row["observed"] * 100)
            for row in cal["bands"]:
                row["share_pct"] = round(row["share"] * 100)
                row["observed_pct"] = None if row["observed"] is None else round(row["observed"] * 100)
    return render(request, "core/model.html", {
        "metrics": metrics, "models": models, "form": form,
        "metric_names": [("accuracy", "Accuracy"), ("precision", "Precision"),
                         ("recall", "Recall"), ("f1", "F1-score"), ("roc_auc", "ROC AUC")],
    })


@admin_required
@require_POST
def model_retrain(request):
    form = TrainingUploadForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Choose a CSV file, or leave the field empty.")
        return redirect("model_report")
    upload = form.cleaned_data.get("file")
    try:
        if upload:
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
                for chunk in upload.chunks():
                    tmp.write(chunk)
                tmp_path = Path(tmp.name)
            try:
                metrics = pipeline.train(tmp_path, permutations=30)
                # Only a file that trained successfully replaces the dataset.
                pipeline.DATA_PATH.write_bytes(tmp_path.read_bytes())
            finally:
                tmp_path.unlink(missing_ok=True)
        else:
            metrics = pipeline.train(permutations=30)
    except pipeline.DatasetError as exc:
        messages.error(request, f"The model was not retrained. {exc}")
        return redirect("model_report")
    acc = metrics["models"][metrics["selected"]]["test"]["accuracy"] * 100
    messages.success(
        request, f"Retrained on {metrics['data']['rows_used']:,} records. "
                 f"{metrics['selected']} is deployed at {acc:.1f}% test accuracy. "
                 "Existing predictions keep the model version they were made with.")
    return redirect("model_report")


# ---------------------------------------------------------------- users

@admin_required
def user_list(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"Created the account {user.username}.")
        return redirect("user_list")
    users = User.objects.annotate(
        n_records=Count("records_entered", distinct=True),
        n_predictions=Count("predictions_requested", distinct=True)).order_by("username")
    return render(request, "core/users.html", {"users": users, "form": form})


@admin_required
def user_edit(request, pk):
    account = get_object_or_404(User, pk=pk)
    form = UserEditForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        is_self = account.pk == request.user.pk
        if is_self and (not form.cleaned_data["is_active"]
                        or form.cleaned_data["role"] != User.ADMIN):
            form.add_error(None, "You cannot deactivate your own account or remove your own "
                                 "administrator role. Ask another administrator to do it.")
        else:
            form.save()
            if is_self and form.cleaned_data.get("new_password"):
                update_session_auth_hash(request, account)
            messages.success(request, f"Saved changes to {account.username}.")
            return redirect("user_list")
    return render(request, "core/user_edit.html", {"form": form, "account": account})


@login_required
def own_password(request):
    form = OwnPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.set_password(form.cleaned_data["new_password"])
        request.user.save()
        update_session_auth_hash(request, request.user)
        messages.success(request, "Changed your password.")
        return redirect("dashboard")
    return render(request, "core/password.html", {"form": form})
