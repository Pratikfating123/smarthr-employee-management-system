from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "core"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="core:dashboard", permanent=False), name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("audit-log/", views.audit_log, name="audit_log"),
]
