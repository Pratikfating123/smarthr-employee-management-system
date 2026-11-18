from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

handler403 = "core.views.error_403"
handler404 = "core.views.error_404"
handler500 = "core.views.error_500"

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("", include("core.urls")),
    path("employees/", include("employees.urls")),
    path("departments/", include("departments.urls")),
    path("attendance/", include("attendance.urls")),
    path("leaves/", include("leaves.urls")),
    path("payroll/", include("payroll.urls")),
    path("reports/", include("reports.urls")),
    path("notifications/", include("notifications.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
