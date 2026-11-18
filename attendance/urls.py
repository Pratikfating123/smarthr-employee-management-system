from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.attendance_list, name="list"),
    path("record/", views.attendance_record, name="record"),
    path("summary/", views.attendance_summary, name="summary"),
    path("check-in/", views.check_in, name="check_in"),
    path("check-out/", views.check_out, name="check_out"),
]
