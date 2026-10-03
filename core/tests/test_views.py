import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.models import AcademicRecord, Prediction, Student, User
from core.services import records as record_service

from .base import AppTestCase

PROTECTED = ["dashboard", "student_list", "student_create", "import_records",
             "history", "history_export", "model_report", "own_password"]


class AccessTests(AppTestCase):
    def test_public_pages_load(self):
        self.assertEqual(self.client.get(reverse("landing")).status_code, 200)
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_app_pages_require_sign_in(self):
        for name in PROTECTED:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn(reverse("login"), response["Location"])

    def test_lecturer_can_open_working_pages(self):
        self.as_lecturer()
        for name in PROTECTED:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_sign_in_and_sign_out(self):
        from django.core.cache import cache
        cache.clear()
        bad = self.client.post(reverse("login"), {"username": "adviser", "password": "nope"})
        self.assertEqual(bad.status_code, 200)
        good = self.client.post(reverse("login"), {"username": "adviser", "password": "Strong#Pass1"})
        self.assertRedirects(good, reverse("dashboard"))
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_repeated_wrong_passwords_pause_sign_in(self):
        from django.core.cache import cache
        cache.clear()
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "adviser", "password": "nope"})
        locked = self.client.post(reverse("login"), {"username": "adviser", "password": "Strong#Pass1"})
        self.assertEqual(locked.status_code, 429)
        self.assertContains(locked, "Too many wrong attempts", status_code=429)
        cache.clear()
        ok = self.client.post(reverse("login"), {"username": "adviser", "password": "Strong#Pass1"})
        self.assertRedirects(ok, reverse("dashboard"))

    def test_admin_only_pages_refuse_lecturers(self):
        rec = self.record()
        self.as_lecturer()
        urls = [reverse("user_list"), reverse("user_edit", args=[self.admin.pk]),
                reverse("record_edit", args=[rec.pk]), reverse("student_edit", args=[self.poly.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(reverse("record_delete", args=[rec.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("model_retrain")).status_code, 403)
        self.assertTrue(AcademicRecord.objects.filter(pk=rec.pk).exists())

    def test_passwords_are_stored_hashed(self):
        self.assertNotEqual(self.lecturer.password, "Strong#Pass1")
        self.assertTrue(self.lecturer.check_password("Strong#Pass1"))


class PredictionFlowTests(AppTestCase):
    def test_enter_record_and_predict_in_one_step(self):
        self.as_lecturer()
        response = self.client.post(reverse("record_create", args=[self.poly.pk]), {
            "session": "2025/2026", "semester": "First", "ca_score": "22",
            "attendance_rate": "40", "previous_gpa": "1.20", "predict": "1"})
        rec = AcademicRecord.objects.get()
        self.assertRedirects(response, reverse("record_detail", args=[rec.pk]))
        self.assertEqual(rec.prediction.risk_category, Prediction.HIGH)
        self.assertEqual(rec.prediction.requested_by, self.lecturer)
        page = self.client.get(reverse("record_detail", args=[rec.pk]))
        self.assertContains(page, "High risk")

    def test_record_can_be_saved_first_and_predicted_later(self):
        self.as_lecturer()
        self.client.post(reverse("record_create", args=[self.uni.pk]), {
            "session": "2025/2026", "semester": "Second", "ca_score": "82",
            "attendance_rate": "93", "previous_gpa": "4.40"})
        rec = AcademicRecord.objects.get()
        self.assertFalse(rec.has_prediction)
        self.client.post(reverse("record_predict", args=[rec.pk]))
        self.assertEqual(Prediction.objects.get(record=rec).risk_category, Prediction.LOW)

    def test_invalid_record_is_not_saved(self):
        self.as_lecturer()
        response = self.client.post(reverse("record_create", args=[self.poly.pk]), {
            "session": "2025", "semester": "First", "ca_score": "120",
            "attendance_rate": "40", "previous_gpa": "4.80", "predict": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AcademicRecord.objects.count(), 0)
        for field in ("session", "ca_score", "previous_gpa"):
            self.assertIn(field, response.context["form"].errors)

    def test_admin_correction_refreshes_the_prediction(self):
        rec = self.record(ca=20, att=40, gpa=1.0)
        record_service.store_prediction(rec, self.lecturer)
        self.as_admin()
        self.client.post(reverse("record_edit", args=[rec.pk]), {
            "session": "2025/2026", "semester": "First", "ca_score": "85",
            "attendance_rate": "95", "previous_gpa": "3.70"})
        rec.refresh_from_db()
        self.assertEqual(Prediction.objects.filter(record=rec).count(), 1)
        self.assertEqual(rec.prediction.risk_category, Prediction.LOW)

    def test_history_lists_filters_and_exports(self):
        record_service.store_prediction(self.record(ca=20, att=40, gpa=1.0), self.lecturer)
        record_service.store_prediction(self.record(self.uni, ca=85, att=95, gpa=4.5), self.lecturer)
        self.as_lecturer()
        self.assertContains(self.client.get(reverse("history")), self.poly.full_name)
        high = self.client.get(reverse("history"), {"risk": "High"})
        self.assertContains(high, self.poly.full_name)
        self.assertNotContains(high, self.uni.full_name)
        export = self.client.get(reverse("history_export"))
        self.assertEqual(export["Content-Type"].split(";")[0], "text/csv")
        self.assertEqual(len(export.content.decode().strip().splitlines()), 3)

    def test_export_is_safe_to_open_in_a_spreadsheet(self):
        self.poly.full_name = '=HYPERLINK("http://evil.example","x")'
        self.poly.save()
        record_service.store_prediction(self.record(), self.lecturer)
        self.as_lecturer()
        body = self.client.get(reverse("history_export")).content.decode()
        self.assertIn("'=HYPERLINK", body)

    def test_correction_keeps_an_audit_trail(self):
        rec = self.record(ca=24, att=8, gpa=2.45)
        record_service.store_prediction(rec, self.lecturer)
        self.as_admin()
        self.client.post(reverse("record_edit", args=[rec.pk]), {
            "session": "2025/2026", "semester": "First", "ca_score": "24",
            "attendance_rate": "80", "previous_gpa": "2.45"})
        rec.refresh_from_db()
        self.assertEqual(rec.corrected_by, self.admin)
        self.assertEqual(rec.prediction.explanation["superseded"]["attendance_rate"], "8.00")
        self.client.post(reverse("record_predict", args=[rec.pk]))   # a re-run keeps the trail
        rec.prediction.refresh_from_db()
        self.assertIn("superseded", rec.prediction.explanation)
        self.assertContains(self.client.get(reverse("record_detail", args=[rec.pk])), "Before the correction")

    def test_public_try_endpoint_stores_nothing(self):
        response = self.client.get(reverse("api_try"), {"ca": 30, "att": 50, "prev": 40})
        self.assertEqual(response.status_code, 200)
        self.assertIn("risk", response.json())
        self.assertEqual(Prediction.objects.count(), 0)
        self.assertEqual(self.client.get(reverse("api_try"), {"ca": 300}).status_code, 400)


HEADER = ",".join(record_service.IMPORT_COLUMNS)


def csv_file(*rows):
    return SimpleUploadedFile("records.csv", ("\n".join([HEADER, *rows]) + "\n").encode(),
                              content_type="text/csv")


class ImportTests(AppTestCase):
    def test_figures_typed_the_way_lecturers_type_them_are_accepted(self):
        header = "Student ID,Full Name,Institution,Institution Type,State,Department,Level,Session,Semester,CA Score,Attendance Rate,Previous GPA"
        body = "\r\n".join([
            header,
            "X/1,Chlo\u00e9 Ad\u00e9,Kaduna Polytechnic,polytechnic,Kaduna State,Statistics,nd2,2026/27,first,62%,36/45,2.9",
            ",,,,,,,,,,,",
        ]) + "\r\n"
        upload = SimpleUploadedFile("class.csv", body.encode("cp1252"), content_type="text/csv")
        result = record_service.import_csv(upload, self.lecturer)
        self.assertEqual((result["imported"], result["errors"]), (1, []))
        rec = AcademicRecord.objects.get(student__student_id="X/1")
        self.assertEqual((float(rec.ca_score), float(rec.attendance_rate), rec.session), (62.0, 80.0, "2026/2027"))
        self.assertEqual((rec.student.level, rec.student.state, rec.student.full_name), ("ND 2", "Kaduna", "Chlo\u00e9 Ad\u00e9"))

    def test_a_shared_matric_number_is_not_filed_against_the_wrong_student(self):
        row = "F/HD/24/0000001,Somebody Else,University of Lagos,University,Lagos,Law,300 Level,2026/2027,First,30,40,3.10"
        result = record_service.import_csv(csv_file(row), self.lecturer)
        self.assertEqual(result["imported"], 0)
        self.assertIn("already belongs to", result["errors"][0]["reason"])
        self.assertEqual(self.poly.records.count(), 0)

    def test_good_rows_are_saved_and_bad_rows_are_reported(self):
        self.as_lecturer()
        upload = csv_file(
            "NEW/001,Ada Obi,University of Lagos,University,Lagos,Physics,200 Level,2025/2026,First,64,88,3.90",
            "F/HD/24/0000001,,,,,,,2025/2026,Second,35,52,1.80",
            "NEW/002,Musa Bello,Kaduna Polytechnic,Polytechnic,Kaduna,Statistics,ND 2,2025/2026,First,,70,2.5",
            "NEW/003,Ife Ade,Some Poly,Polytechnic,Atlantis,Statistics,ND 2,2025/2026,First,50,70,2.5",
            "NEW/004,Uche Eze,Some Poly,Polytechnic,Enugu,Statistics,ND 2,2025/2026,First,50,70,4.6",
        )
        response = self.client.post(reverse("import_records"), {"file": upload, "predict": "on"})
        result = response.context["result"]
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["new_students"], 1)
        self.assertEqual(result["predicted"], 2)
        self.assertEqual([e["line"] for e in result["errors"]], [4, 5, 6])
        self.assertFalse(Student.objects.filter(student_id__in=["NEW/002", "NEW/003", "NEW/004"]).exists())
        self.assertEqual(Prediction.objects.count(), 2)

    def test_repeated_rows_are_skipped(self):
        row = "F/HD/24/0000001,,,,,,,2025/2026,First,35,52,1.80"
        result = record_service.import_csv(csv_file(row, row), self.lecturer)
        self.assertEqual((result["imported"], result["duplicates"]), (1, 1))

    def test_missing_columns_stop_the_import(self):
        bad = SimpleUploadedFile("x.csv", b"student_id,ca_score\nA,1\n", content_type="text/csv")
        result = record_service.import_csv(bad, self.lecturer)
        self.assertIn("missing these columns", result["fatal"])
        self.assertEqual(AcademicRecord.objects.count(), 0)

    def test_template_download_has_the_expected_header(self):
        self.as_lecturer()
        body = self.client.get(reverse("import_template")).content.decode()
        self.assertTrue(body.startswith(HEADER))


class UserAdminTests(AppTestCase):
    def test_admin_creates_a_lecturer_account(self):
        self.as_admin()
        self.client.post(reverse("user_list"), {
            "username": "newadviser", "first_name": "New", "last_name": "Adviser",
            "email": "", "role": User.LECTURER, "password": "Fresh#Pass2026"})
        created = User.objects.get(username="newadviser")
        self.assertEqual(created.role, User.LECTURER)
        self.assertTrue(created.check_password("Fresh#Pass2026"))

    def test_deactivated_account_cannot_sign_in(self):
        self.as_admin()
        self.client.post(reverse("user_edit", args=[self.lecturer.pk]), {
            "first_name": "", "last_name": "", "email": "", "role": User.LECTURER, "new_password": ""})
        self.client.logout()
        self.assertFalse(self.client.login(username="adviser", password="Strong#Pass1"))

    def test_admin_cannot_lock_themselves_out(self):
        self.as_admin()
        self.client.post(reverse("user_edit", args=[self.admin.pk]), {
            "first_name": "", "last_name": "", "email": "", "role": User.LECTURER,
            "is_active": "on", "new_password": ""})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.ADMIN)

    def test_admin_deletes_a_record(self):
        rec = self.record()
        self.as_admin()
        self.client.post(reverse("record_delete", args=[rec.pk]))
        self.assertFalse(AcademicRecord.objects.filter(pk=rec.pk).exists())

    def test_user_changes_own_password(self):
        self.as_lecturer()
        self.client.post(reverse("own_password"), {
            "current_password": "Strong#Pass1", "new_password": "Another#Pass9"})
        self.lecturer.refresh_from_db()
        self.assertTrue(self.lecturer.check_password("Another#Pass9"))
