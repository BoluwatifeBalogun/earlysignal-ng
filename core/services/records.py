"""Saving predictions and importing records in bulk."""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from core import nigeria
from core.forms import validate_session
from core.models import AcademicRecord, Prediction, Student

from . import predictor

IMPORT_COLUMNS = [
    "student_id", "full_name", "institution", "institution_type", "state",
    "department", "level", "session", "semester",
    "ca_score", "attendance_rate", "previous_gpa",
]
MAX_IMPORT_ROWS = 2000


def store_prediction(record: AcademicRecord, user=None) -> Prediction:
    """Run the model on one record and save the result against it."""
    result = predictor.predict(*record.features)
    earlier = Prediction.objects.filter(record=record).values_list("explanation", flat=True).first() or {}
    prediction, _ = Prediction.objects.update_or_create(
        record=record,
        defaults={
            "predicted_outcome": result["outcome"],
            "risk_category": result["risk"],
            "probability": result["probability"],
            "explanation": {
                "baseline": result["baseline"],
                "score": result["score"],
                "cautions": result["cautions"],
                **({"superseded": earlier["superseded"]} if earlier.get("superseded") else {}),
                "factors": result["factors"],
                "advice": result["advice"],
            },
            "model_name": result["model_name"],
            "model_version": result["model_version"],
            "requested_by": user,
        },
    )
    return prediction


def ensure_explanation(prediction: Prediction) -> Prediction:
    """Bulk imports store the probability only; fill in the explanation on
    first view using the same model version that is deployed now."""
    if prediction.explanation.get("factors"):
        return prediction
    return store_prediction(prediction.record, prediction.requested_by)


def store_predictions_bulk(records: list[AcademicRecord], user=None) -> int:
    if not records:
        return 0
    bundle = predictor.load_bundle()
    results = predictor.predict_many([r.features for r in records])
    Prediction.objects.bulk_create(
        [
            Prediction(
                record=r,
                predicted_outcome=res["outcome"],
                risk_category=res["risk"],
                probability=res["probability"],
                explanation={},
                model_name=bundle["name"],
                model_version=bundle["version"],
                requested_by=user,
            )
            for r, res in zip(records, results)
        ]
    )
    return len(records)


def _decimal(row: dict, key: str, lo: float, hi: float, label: str, percent: bool = False) -> Decimal:
    """Read a figure the way lecturers actually type it: 62, 62%, or 18/30."""
    raw = (row.get(key) or "").strip()
    if raw == "":
        raise ValueError(f"{label} is empty")
    text = raw.rstrip("%").strip() if percent else raw
    try:
        if percent and "/" in text:
            got, out_of = (Decimal(part.strip()) for part in text.split("/", 1))
            if out_of <= 0 or got < 0 or got > out_of:
                raise ValueError(f"{label} '{raw}' is not a valid fraction")
            value = (got / out_of * 100).quantize(Decimal("0.01"))
        else:
            value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        if isinstance(exc, ValueError) and "fraction" in str(exc):
            raise
        raise ValueError(f"{label} '{raw}' is not a number")
    if not value.is_finite() or value < Decimal(str(lo)) or value > Decimal(str(hi)):
        raise ValueError(f"{label} must be between {lo:g} and {hi:g}")
    return value


def _key(value: str) -> str:
    return "".join((value or "").lower().split())


def _match(value: str, options: list[str], label: str) -> str:
    """Match ignoring case and spacing, so 'hnd2' finds 'HND 2'."""
    lookup = {_key(o): o for o in options}
    key = _key(value)
    if label == "State":
        key = key.removesuffix("state") or key
        key = {"abuja": "fct", "federalcapitalterritory": "fct"}.get(key, key)
    if key not in lookup:
        raise ValueError(f"{label} '{value}' is not recognised")
    return lookup[key]


def _session(value: str) -> str:
    """Accept 2026/27 as well as 2026/2027."""
    value = (value or "").strip().replace("-", "/")
    head, _, tail = value.partition("/")
    if len(head) == 4 and len(tail) == 2 and head.isdigit() and tail.isdigit():
        value = f"{head}/{head[:2]}{tail}"
    return validate_session(value)


def _decode(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp1252"):  # Excel on Windows saves the second
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def import_csv(uploaded, user, predict: bool = True) -> dict:
    """Import academic records row by row. Good rows are saved; bad rows are
    reported with the reason, and nothing is guessed or imputed."""
    text = _decode(uploaded.read())
    if text is None:
        return {"fatal": "The file could not be read as text. Save it as CSV and try again."}
    reader = csv.DictReader(io.StringIO(text))
    norm = lambda h: "_".join((h or "").strip().lower().replace("-", " ").split())
    reader.fieldnames = [norm(h) for h in (reader.fieldnames or [])]
    headers = reader.fieldnames
    missing = [c for c in IMPORT_COLUMNS if c not in headers]
    if missing:
        return {"fatal": "The file is missing these columns: " + ", ".join(missing) + "."}
    rows = []
    for raw in reader:
        if any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            rows.append((reader.line_num, raw))  # blank spreadsheet rows are ignored
    if not rows:
        return {"fatal": "The file has a header row but no records."}
    if len(rows) > MAX_IMPORT_ROWS:
        return {"fatal": f"The file has {len(rows):,} rows. Split it into files of "
                         f"{MAX_IMPORT_ROWS:,} rows or fewer."}

    errors, created_records, new_students, duplicates = [], [], 0, 0
    semesters = [s for s, _ in nigeria.SEMESTER_CHOICES]
    for line, raw in rows:
        row = {k: (v or "").strip() for k, v in raw.items() if isinstance(k, str)}
        try:
            student_id = row["student_id"].upper()
            if not student_id:
                raise ValueError("student_id is empty")
            session = _session(row["session"])
            semester = _match(row["semester"], semesters, "Semester")
            ca = _decimal(row, "ca_score", 0, 100, "CA score", percent=True)
            attendance = _decimal(row, "attendance_rate", 0, 100, "Attendance", percent=True)

            is_new = False
            with transaction.atomic():
                student = Student.objects.filter(student_id=student_id).first()
                if student is None:
                    inst_type = _match(row["institution_type"], nigeria.INSTITUTION_TYPES,
                                       "Institution type")
                    student = Student(
                        student_id=student_id,
                        full_name=row["full_name"],
                        institution=row["institution"],
                        institution_type=inst_type,
                        state=_match(row["state"], nigeria.STATES, "State"),
                        department=row["department"],
                        level=_match(row["level"], nigeria.LEVELS[inst_type],
                                     f"Level for a {inst_type.lower()}"),
                    )
                    student.full_clean()
                    student.save()
                    is_new = True
                elif row["full_name"] and _key(row["full_name"]) != _key(student.full_name):
                    # Never file a record against somebody else because two
                    # institutions happen to share a matric number.
                    raise ValueError(
                        f"Student ID {student_id} already belongs to {student.full_name} "
                        f"({student.institution}), not '{row['full_name']}'"
                    )
                gpa = _decimal(row, "previous_gpa", 0, student.gpa_scale,
                               f"Previous GPA ({student.gpa_scale:.2f} scale)")
                if AcademicRecord.objects.filter(
                    student=student, session=session, semester=semester,
                    ca_score=ca, attendance_rate=attendance, previous_gpa=gpa,
                ).exists():
                    duplicates += 1
                    continue
                record = AcademicRecord(
                    student=student, session=session, semester=semester,
                    ca_score=ca, attendance_rate=attendance, previous_gpa=gpa,
                    entered_by=user,
                )
                record.save()
            # Counted only once the whole row has been committed.
            created_records.append(record)
            new_students += is_new
        except ValidationError as exc:
            parts = exc.message_dict if hasattr(exc, "message_dict") else {"": exc.messages}
            msg = "; ".join(f"{k}: {' '.join(v)}" if k else " ".join(v) for k, v in parts.items())
            errors.append({"line": line, "student_id": row.get("student_id", ""), "reason": msg})
        except (ValueError, KeyError) as exc:
            reason = exc.messages[0] if hasattr(exc, "messages") else str(exc)
            errors.append({"line": line, "student_id": row.get("student_id", ""), "reason": reason})

    predicted = 0
    if predict and created_records and predictor.model_ready():
        predicted = store_predictions_bulk(created_records, user)
    return {
        "fatal": None,
        "total": len(rows),
        "imported": len(created_records),
        "new_students": new_students,
        "duplicates": duplicates,
        "predicted": predicted,
        "errors": errors,
    }
