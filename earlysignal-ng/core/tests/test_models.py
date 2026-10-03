from django.core.exceptions import ValidationError

from core import nigeria
from core.models import AcademicRecord, Prediction, Student

from .base import AppTestCase


class StudentModelTests(AppTestCase):
    def test_zone_is_derived_from_state(self):
        self.assertEqual(self.poly.zone, "South West")
        self.poly.state = "Kano"
        self.poly.save()
        self.assertEqual(self.poly.zone, "North West")

    def test_every_state_maps_to_one_of_six_zones(self):
        self.assertEqual(len(nigeria.STATES), 37)  # 36 states and the FCT
        self.assertEqual(len(nigeria.ZONE_NAMES), 6)
        for state in nigeria.STATES:
            self.assertIn(nigeria.zone_for(state), nigeria.ZONE_NAMES)

    def test_level_must_match_institution_type(self):
        self.poly.level = "300 Level"
        with self.assertRaises(ValidationError):
            self.poly.full_clean()

    def test_student_id_is_unique(self):
        clone = Student(student_id=self.poly.student_id, full_name="X", department="Y",
                        level="ND 1", institution="Z", institution_type="Polytechnic", state="Lagos")
        with self.assertRaises(ValidationError):
            clone.full_clean()


class RecordModelTests(AppTestCase):
    def test_gpa_is_normalised_to_the_institution_scale(self):
        poly = self.record(self.poly, gpa=2.0)   # 2.00 of 4.00
        uni = self.record(self.uni, gpa=2.5)     # 2.50 of 5.00
        self.assertEqual(float(poly.previous_result), 50.0)
        self.assertEqual(float(uni.previous_result), 50.0)

    def test_gpa_above_scale_is_rejected(self):
        rec = AcademicRecord(student=self.poly, session="2025/2026", semester="First",
                             ca_score=50, attendance_rate=80, previous_gpa=4.5)
        with self.assertRaises(ValidationError):
            rec.full_clean()

    def test_percentages_stay_within_range(self):
        rec = AcademicRecord(student=self.poly, session="2025/2026", semester="First",
                             ca_score=101, attendance_rate=-1, previous_gpa=3)
        with self.assertRaises(ValidationError) as ctx:
            rec.full_clean()
        self.assertIn("ca_score", ctx.exception.message_dict)
        self.assertIn("attendance_rate", ctx.exception.message_dict)

    def test_deleting_a_record_removes_its_prediction(self):
        rec = self.record()
        Prediction.objects.create(record=rec, predicted_outcome=Prediction.UNDER,
                                  risk_category=Prediction.HIGH, probability=0.9,
                                  model_name="t", model_version="t")
        rec.delete()
        self.assertEqual(Prediction.objects.count(), 0)
