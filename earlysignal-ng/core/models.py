"""Data tier. Four entities, as drawn in Figure 3.2 of the seminar report:

    USER  --manages-->  ACADEMIC RECORD  <--1:M--  STUDENT
                              |
                             1:1
                              |
                         PREDICTION
"""
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from . import nigeria


class User(AbstractUser):
    """USER: user_id, username, password_hash, role."""

    ADMIN = "ADMIN"
    LECTURER = "LECTURER"
    ROLE_CHOICES = [(ADMIN, "Administrator"), (LECTURER, "Lecturer / Academic adviser")]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=LECTURER)

    @property
    def is_administrator(self) -> bool:
        return self.role == self.ADMIN or self.is_superuser

    @property
    def display_name(self) -> str:
        return self.get_full_name() or self.username

    @property
    def initials(self) -> str:
        parts = (self.get_full_name() or self.username).split()
        return "".join(p[0] for p in parts[:2]).upper()


class Student(models.Model):
    """STUDENT: student_id, full_name, department, level.

    Institution, institution type and state are added for the Nigeria-wide
    case study.
    """

    student_id = models.CharField(
        "Student ID", max_length=40, unique=True,
        help_text="Matric number or reference code, for example F/HD/24/3211030.",
    )
    full_name = models.CharField(max_length=120)
    department = models.CharField(max_length=120)
    level = models.CharField(max_length=20, choices=nigeria.LEVEL_CHOICES)
    institution = models.CharField(max_length=160)
    institution_type = models.CharField(
        max_length=30, choices=nigeria.INSTITUTION_TYPE_CHOICES, default=nigeria.POLYTECHNIC
    )
    state = models.CharField(max_length=20, choices=nigeria.STATE_CHOICES)
    zone = models.CharField(max_length=20, editable=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.student_id})"

    @property
    def gpa_scale(self) -> float:
        return nigeria.scale_for(self.institution_type)

    def clean(self):
        allowed = nigeria.LEVELS.get(self.institution_type, [])
        if self.level and allowed and self.level not in allowed:
            raise ValidationError(
                {"level": f"{self.institution_type} levels are: {', '.join(allowed)}."}
            )

    def save(self, *args, **kwargs):
        self.zone = nigeria.zone_for(self.state)
        super().save(*args, **kwargs)

    @property
    def latest_record(self):
        return self.records.order_by("-created_at").first()


PERCENT = [MinValueValidator(0), MaxValueValidator(100)]


class AcademicRecord(models.Model):
    """ACADEMIC RECORD: record_id, student_id (FK), ca_score, attendance_rate,
    previous_result. These three indicators are the model's only inputs."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="records")
    session = models.CharField(max_length=9, help_text="Academic session, for example 2025/2026.")
    semester = models.CharField(max_length=6, choices=nigeria.SEMESTER_CHOICES)
    ca_score = models.DecimalField(
        "CA score (%)", max_digits=5, decimal_places=2, validators=PERCENT,
        help_text="Continuous assessment so far, as a percentage of the marks available.",
    )
    attendance_rate = models.DecimalField(
        "Attendance (%)", max_digits=5, decimal_places=2, validators=PERCENT,
        help_text="Share of classes attended this semester.",
    )
    previous_gpa = models.DecimalField(
        "Previous GPA", max_digits=3, decimal_places=2, validators=[MinValueValidator(0)],
        help_text="GPA from the last completed semester, on the institution's own scale.",
    )
    previous_result = models.DecimalField(
        max_digits=5, decimal_places=2, editable=False,
        help_text="Previous GPA as a percentage of its scale. This is what the model reads.",
    )
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="records_entered",
    )
    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="records_corrected",
    )
    corrected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.student.student_id} {self.session} {self.semester}"

    def clean(self):
        if self.previous_gpa is not None and self.student_id:
            scale = self.student.gpa_scale
            if float(self.previous_gpa) > scale:
                raise ValidationError(
                    {"previous_gpa": f"{self.student.institution_type} GPA is on a "
                                     f"{scale:.2f} scale, so this cannot be above {scale:.2f}."}
                )

    def save(self, *args, **kwargs):
        self.previous_result = nigeria.normalise_gpa(
            self.previous_gpa, self.student.institution_type
        )
        super().save(*args, **kwargs)

    @property
    def features(self) -> list[float]:
        return [float(self.ca_score), float(self.attendance_rate), float(self.previous_result)]

    @property
    def has_prediction(self) -> bool:
        return hasattr(self, "prediction")


class Prediction(models.Model):
    """PREDICTION: prediction_id, record_id (FK), predicted_outcome,
    risk_category, date_generated. One prediction per academic record, so any
    prediction traces back to the exact indicators that produced it."""

    PASS = "On track to pass"
    UNDER = "At risk of under-performing"
    OUTCOME_CHOICES = [(PASS, PASS), (UNDER, UNDER)]

    LOW, MEDIUM, HIGH = "Low", "Medium", "High"
    RISK_CHOICES = [(LOW, "Low risk"), (MEDIUM, "Medium risk"), (HIGH, "High risk")]

    record = models.OneToOneField(AcademicRecord, on_delete=models.CASCADE, related_name="prediction")
    predicted_outcome = models.CharField(max_length=30, choices=OUTCOME_CHOICES)
    risk_category = models.CharField(max_length=10, choices=RISK_CHOICES, db_index=True)
    probability = models.FloatField(help_text="Calibrated chance of under-performing.")
    explanation = models.JSONField(default=dict, blank=True)
    model_name = models.CharField(max_length=40)
    model_version = models.CharField(max_length=20)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="predictions_requested",
    )
    date_generated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_generated"]

    def __str__(self):
        return f"{self.record} -> {self.risk_category}"

    @property
    def percent(self) -> int:
        # A forest can vote unanimously, but no forecast is certain, so the
        # figure shown to people stays between 1 and 99.
        return min(max(round(self.probability * 100), 1), 99)
