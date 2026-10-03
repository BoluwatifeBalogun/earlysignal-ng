import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from . import nigeria
from .models import AcademicRecord, Student, User

SESSION_RE = re.compile(r"^(\d{4})/(\d{4})$")


def validate_session(value: str) -> str:
    value = (value or "").strip()
    m = SESSION_RE.match(value)
    if not m or int(m.group(2)) != int(m.group(1)) + 1:
        raise forms.ValidationError("Write the session as two consecutive years, for example 2025/2026.")
    return value


class StyledMixin:
    """Gives every widget the input class and wires aria-describedby."""

    def _style(self):
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
                continue
            css = "select" if isinstance(widget, forms.Select) else "input"
            widget.attrs.setdefault("class", css)
            described = []
            if field.help_text:
                described.append(f"help_{name}")
            if self.is_bound and name in self.errors:
                described.append(f"error_{name}")
                widget.attrs["aria-invalid"] = "true"
            if described:
                widget.attrs["aria-describedby"] = " ".join(described)


class LoginForm(StyledMixin, AuthenticationForm):
    error_messages = {
        "invalid_login": "That username and password do not match an account. Check both and try again.",
        "inactive": "This account has been deactivated. Ask an administrator to restore it.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(autocomplete="username", autofocus=True)
        self.fields["password"].widget.attrs.update(autocomplete="current-password")
        self._style()


class StudentForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Student
        fields = ["student_id", "full_name", "institution", "institution_type",
                  "state", "department", "level"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["institution"].widget.attrs["list"] = "institution-list"
        self.fields["department"].widget.attrs["list"] = "department-list"
        self.fields["state"].help_text = "State where the institution is located."
        self._style()

    def clean_student_id(self):
        return self.cleaned_data["student_id"].strip().upper()


class RecordForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = AcademicRecord
        fields = ["session", "semester", "ca_score", "attendance_rate", "previous_gpa"]

    def __init__(self, *args, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        if student is not None:
            self.instance.student = student
        scale = self.instance.student.gpa_scale
        self.fields["previous_gpa"].label = f"Previous GPA (out of {scale:.2f})"
        self.fields["previous_gpa"].widget.attrs.update(
            min="0", max=f"{scale:.2f}", step="0.01", inputmode="decimal")
        for name in ("ca_score", "attendance_rate"):
            self.fields[name].widget.attrs.update(min="0", max="100", step="0.01", inputmode="decimal")
        self.fields["session"].widget.attrs["placeholder"] = "2025/2026"
        self._style()

    def clean_session(self):
        return validate_session(self.cleaned_data["session"])


class ImportForm(StyledMixin, forms.Form):
    file = forms.FileField(
        label="CSV file",
        help_text="Up to 2,000 rows. Download the template to see the columns.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )
    predict = forms.BooleanField(
        label="Generate a prediction for each imported record", required=False, initial=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class TrainingUploadForm(StyledMixin, forms.Form):
    file = forms.FileField(
        label="Labelled records (CSV)", required=False,
        help_text="Columns: ca_score, attendance_rate, previous_result (or previous_gpa and "
                  "gpa_scale), outcome (Pass or Under-perform). Leave empty to retrain on the "
                  "current dataset.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()


class UserCreateForm(StyledMixin, forms.ModelForm):
    password = forms.CharField(
        label="Temporary password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 8 characters. Ask the user to change it after first sign-in.")

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "role"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Letters, digits and @ . + - _ only."
        self._style()

    def clean_password(self):
        pw = self.cleaned_data["password"]
        password_validation.validate_password(pw)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class UserEditForm(StyledMixin, forms.ModelForm):
    new_password = forms.CharField(
        label="Reset password", required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Leave empty to keep the current password.")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "role", "is_active"]
        labels = {"is_active": "Account is active"}
        help_texts = {"is_active": "Deactivated accounts cannot sign in. Their records stay."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style()

    def clean_new_password(self):
        pw = self.cleaned_data.get("new_password")
        if pw:
            password_validation.validate_password(pw, self.instance)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("new_password"):
            user.set_password(self.cleaned_data["new_password"])
        if commit:
            user.save()
        return user


class OwnPasswordForm(StyledMixin, forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 8 characters, not entirely numeric.")

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self._style()

    def clean_current_password(self):
        pw = self.cleaned_data["current_password"]
        if not self.user.check_password(pw):
            raise forms.ValidationError("That is not your current password.")
        return pw

    def clean_new_password(self):
        pw = self.cleaned_data["new_password"]
        password_validation.validate_password(pw, self.user)
        return pw
