from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AcademicRecord, Prediction, Student, User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Role", {"fields": ("role",)}),)
    list_display = ("username", "first_name", "last_name", "role", "is_active")


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("student_id", "full_name", "institution", "state", "zone", "level")
    search_fields = ("student_id", "full_name", "institution")
    list_filter = ("zone", "institution_type")


@admin.register(AcademicRecord)
class AcademicRecordAdmin(admin.ModelAdmin):
    list_display = ("student", "session", "semester", "ca_score", "attendance_rate", "previous_gpa")


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ("record", "predicted_outcome", "risk_category", "probability", "date_generated")
    list_filter = ("risk_category",)
