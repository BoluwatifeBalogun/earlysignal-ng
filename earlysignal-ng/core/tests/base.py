"""Shared fixtures. The tests use the trained model in ml/artifacts, so run
`python manage.py train_model` (or `bootstrap`) once before `manage.py test`."""
from django.test import TestCase

from core.models import AcademicRecord, Student, User


class AppTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("boss", password="Strong#Pass1", role=User.ADMIN)
        cls.lecturer = User.objects.create_user("adviser", password="Strong#Pass1", role=User.LECTURER)
        cls.poly = Student.objects.create(
            student_id="F/HD/24/0000001", full_name="Test Polytechnic Student",
            department="Computer Science", level="HND 2",
            institution="Yaba College of Technology", institution_type="Polytechnic", state="Lagos")
        cls.uni = Student.objects.create(
            student_id="UNI/20/0000002", full_name="Test University Student",
            department="Economics", level="300 Level",
            institution="University of Ibadan", institution_type="University", state="Oyo")

    def record(self, student=None, ca=30, att=45, gpa=1.5):
        return AcademicRecord.objects.create(
            student=student or self.poly, session="2025/2026", semester="First",
            ca_score=ca, attendance_rate=att, previous_gpa=gpa, entered_by=self.lecturer)

    def as_lecturer(self):
        self.client.login(username="adviser", password="Strong#Pass1")

    def as_admin(self):
        self.client.login(username="boss", password="Strong#Pass1")
