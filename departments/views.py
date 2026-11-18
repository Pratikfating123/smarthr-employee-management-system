from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.permissions import hr_required

from .forms import DepartmentForm, DesignationForm
from .models import Department, Designation


@hr_required
def department_list(request):
    departments = Department.objects.select_related("head").annotate(
        employee_count=Count("employees", filter=Q(employees__status="active"))
    )
    return render(request, "departments/list.html", {"departments": departments})


@hr_required
def department_create(request):
    form = DepartmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        department = form.save()
        log_action(request.user, "department_created", department, department.name)
        messages.success(request, f"Department “{department.name}” created.")
        return redirect("departments:list")
    return render(
        request,
        "generic_form.html",
        {"form": form, "title": "Add department", "cancel_url": "departments:list", "submit_label": "Create department"},
    )


@hr_required
def department_edit(request, pk):
    department = get_object_or_404(Department, pk=pk)
    form = DepartmentForm(request.POST or None, instance=department)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request.user, "department_updated", department, department.name)
        messages.success(request, "Department updated.")
        return redirect("departments:list")
    return render(
        request,
        "generic_form.html",
        {"form": form, "title": f"Edit {department.name}", "cancel_url": "departments:list", "submit_label": "Save changes"},
    )


@hr_required
@require_POST
def department_toggle(request, pk):
    department = get_object_or_404(Department, pk=pk)
    if department.is_active and department.employees.filter(status="active").exists():
        messages.error(request, "Cannot deactivate a department that still has active employees.")
    else:
        department.is_active = not department.is_active
        department.save(update_fields=["is_active", "updated_at"])
        log_action(request.user, "department_toggled", department, f"active={department.is_active}")
        messages.success(request, f"Department {'activated' if department.is_active else 'deactivated'}.")
    return redirect("departments:list")


@hr_required
def designation_list(request):
    form = DesignationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        designation = form.save()
        log_action(request.user, "designation_created", designation, designation.name)
        messages.success(request, "Designation added.")
        return redirect("departments:designations")
    designations = Designation.objects.annotate(employee_count=Count("employees", filter=Q(employees__status="active")))
    return render(request, "departments/designations.html", {"form": form, "designations": designations})


@hr_required
@require_POST
def designation_toggle(request, pk):
    designation = get_object_or_404(Designation, pk=pk)
    if designation.is_active and designation.employees.filter(status="active").exists():
        messages.error(request, "Cannot deactivate a designation that active employees hold.")
    else:
        designation.is_active = not designation.is_active
        designation.save(update_fields=["is_active"])
        messages.success(request, f"Designation {'activated' if designation.is_active else 'deactivated'}.")
    return redirect("departments:designations")
