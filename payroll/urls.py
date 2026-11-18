from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    path("", views.payroll_list, name="list"),
    path("create/", views.payroll_create, name="create"),
    path("structures/", views.structure_list, name="structures"),
    path("structures/create/", views.structure_create, name="structure_create"),
    path("structures/<int:pk>/edit/", views.structure_edit, name="structure_edit"),
    path("<int:pk>/", views.payroll_detail, name="detail"),
    path("<int:pk>/approve/", views.payroll_approve, name="approve"),
    path("<int:pk>/payment/", views.payroll_payment, name="payment"),
]
