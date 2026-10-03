"""Load demo accounts and a synthetic national cohort so every screen has
something to show. All students here are invented."""
from datetime import timedelta

import numpy as np
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import nigeria
from core.models import AcademicRecord, Prediction, Student, User
from core.services import predictor, records as record_service

FIRST = ["Adaeze", "Chinedu", "Ngozi", "Emeka", "Ifeoma", "Obinna", "Chiamaka", "Uchenna",
         "Tunde", "Folake", "Kehinde", "Bisi", "Segun", "Yetunde", "Damilola", "Ayomide",
         "Ibrahim", "Aisha", "Musa", "Fatima", "Yusuf", "Zainab", "Abubakar", "Halima",
         "Efosa", "Osaze", "Ivie", "Tamuno", "Ebiere", "Preye", "Ekaette", "Udeme",
         "Terver", "Dooshima", "Danladi", "Rahila", "Blessing", "Samuel", "Grace", "Daniel"]
LAST = ["Okonkwo", "Eze", "Nwosu", "Obi", "Chukwu", "Adeyemi", "Ogunleye", "Balogun",
        "Olawale", "Adebayo", "Bello", "Danjuma", "Abdullahi", "Sani", "Lawal", "Garba",
        "Osagie", "Igbinedion", "Dokubo", "Briggs", "Etim", "Udoh", "Akpan", "Tyoapine",
        "Gyang", "Dung", "Yakubu", "Shehu", "Aliyu", "Onyeka", "Afolabi", "Oyelaran"]
SESSIONS = [("2024/2025", "Second"), ("2025/2026", "First")]


class Command(BaseCommand):
    help = "Create demo accounts and a synthetic cohort spread across Nigeria."

    def add_arguments(self, parser):
        parser.add_argument("--students", type=int, default=280)
        parser.add_argument("--reset", action="store_true", help="Delete existing students first.")

    def handle(self, *args, **opts):
        rng = np.random.default_rng(7)
        admin, created = User.objects.get_or_create(
            username="admin", defaults=dict(first_name="Ngozi", last_name="Adeyemi",
                                            role=User.ADMIN, is_staff=True, is_superuser=True,
                                            email="admin@earlysignal.ng"))
        if created:
            admin.set_password("Admin@2026")
            admin.save()
        lecturer, created = User.objects.get_or_create(
            username="lecturer", defaults=dict(first_name="Tunde", last_name="Bello",
                                               role=User.LECTURER, email="lecturer@earlysignal.ng"))
        if created:
            lecturer.set_password("Lecturer@2026")
            lecturer.save()

        if opts["reset"]:
            Student.objects.all().delete()
        if Student.objects.exists():
            self.stdout.write("Students already exist. Use --reset to rebuild the demo cohort.")
            return

        now = timezone.now()
        students, record_rows = [], []
        for i in range(opts["students"]):
            name, inst_type, state = nigeria.INSTITUTIONS[i % len(nigeria.INSTITUTIONS)]
            prefix = {"University": "UG", "Polytechnic": "F/HD", "College of Education": "NCE"}[inst_type]
            students.append(Student(
                student_id=f"{prefix}/{rng.integers(21, 25)}/{3210000 + i}",
                full_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                institution=name, institution_type=inst_type, state=state,
                zone=nigeria.zone_for(state),
                department=str(rng.choice(nigeria.DEPARTMENTS)),
                level=str(rng.choice(nigeria.LEVELS[inst_type])),
            ))
        Student.objects.bulk_create(students)
        students = list(Student.objects.order_by("id"))

        records = []
        for s in students:
            scale = s.gpa_scale
            ability = rng.normal(0, 1)
            disengaged = rng.random() < 0.16
            drift = rng.normal(0, 4)
            n_terms = 2 if rng.random() < 0.7 else 1
            for t, (session, semester) in enumerate(SESSIONS[-n_terms:]):
                slip = (t * drift) + (rng.uniform(10, 30) if disengaged and t == n_terms - 1 else 0)
                att = float(np.clip(round(83 + 6 * ability + rng.normal(0, 8) - slip), 20, 100))
                ca = float(np.clip(round(58 + 10 * ability + 0.28 * (att - 80) + rng.normal(0, 8), 1), 5, 100))
                gpa = float(np.clip(round((57 + 11 * ability + rng.normal(0, 7)) / 100 * scale, 2), 0.5, scale))
                r = AcademicRecord(
                    student=s, session=session, semester=semester, ca_score=ca,
                    attendance_rate=att, previous_gpa=gpa,
                    previous_result=nigeria.normalise_gpa(gpa, s.institution_type),
                    entered_by=lecturer if rng.random() < 0.8 else admin)
                records.append((r, now - timedelta(days=(n_terms - 1 - t) * 150 + int(rng.integers(1, 40)))))
        AcademicRecord.objects.bulk_create([r for r, _ in records])
        saved = list(AcademicRecord.objects.order_by("id"))
        for rec, (_, when) in zip(saved, records):
            rec.created_at = when
        AcademicRecord.objects.bulk_update(saved, ["created_at"])

        if predictor.model_ready():
            # Leave a handful without predictions so the "awaiting" state is visible.
            to_predict = saved[:-6]
            record_service.store_predictions_bulk(to_predict, lecturer)
            for p in Prediction.objects.select_related("record"):
                Prediction.objects.filter(pk=p.pk).update(
                    date_generated=p.record.created_at + timedelta(hours=2))
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(students)} students, {len(saved)} records, "
            f"{Prediction.objects.count()} predictions."))
        self.stdout.write("Accounts: admin / Admin@2026 and lecturer / Lecturer@2026")
