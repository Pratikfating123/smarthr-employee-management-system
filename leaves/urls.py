from django.urls import path

from . import views

app_name = "leaves"

urlpatterns = [
    path("", views.leave_list, name="list"),
    path("apply/", views.leave_apply, name="apply"),
    path("balances/", views.leave_balances, name="balances"),
    path("<int:pk>/", views.leave_detail, name="detail"),
    path("<int:pk>/approve/", views.leave_approve, name="approve"),
    path("<int:pk>/reject/", views.leave_reject, name="reject"),
    path("<int:pk>/cancel/", views.leave_cancel, name="cancel"),
]
