from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("login/", views.SignIn.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("api/try/", views.api_try, name="api_try"),

    path("app/", views.dashboard, name="dashboard"),
    path("app/students/", views.student_list, name="student_list"),
    path("app/students/new/", views.student_create, name="student_create"),
    path("app/students/<int:pk>/", views.student_detail, name="student_detail"),
    path("app/students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("app/students/<int:pk>/records/new/", views.record_create, name="record_create"),
    path("app/records/<int:pk>/", views.record_detail, name="record_detail"),
    path("app/records/<int:pk>/predict/", views.record_predict, name="record_predict"),
    path("app/records/<int:pk>/edit/", views.record_edit, name="record_edit"),
    path("app/records/<int:pk>/delete/", views.record_delete, name="record_delete"),
    path("app/import/", views.import_records, name="import_records"),
    path("app/import/template.csv", views.import_template, name="import_template"),
    path("app/history/", views.history, name="history"),
    path("app/history/export.csv", views.history_export, name="history_export"),
    path("app/model/", views.model_report, name="model_report"),
    path("app/model/retrain/", views.model_retrain, name="model_retrain"),
    path("app/users/", views.user_list, name="user_list"),
    path("app/users/<int:pk>/", views.user_edit, name="user_edit"),
    path("app/account/password/", views.own_password, name="own_password"),
]
