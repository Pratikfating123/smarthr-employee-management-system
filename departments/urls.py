from django.urls import path

from . import views

app_name = "departments"

urlpatterns = [
    path("", views.department_list, name="list"),
    path("create/", views.department_create, name="create"),
    path("<int:pk>/edit/", views.department_edit, name="edit"),
    path("<int:pk>/toggle/", views.department_toggle, name="toggle"),
    path("designations/", views.designation_list, name="designations"),
    path("designations/<int:pk>/toggle/", views.designation_toggle, name="designation_toggle"),
]
