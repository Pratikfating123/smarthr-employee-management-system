from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.permissions import hr_required
from core.utils import paginate, month_bounds

from .forms import EmployeeForm
from .models import Employee


def can_manage(actor, employee):
    """Admins manage everyone; HR managers cannot touch admin accounts."""
    if actor.is_admin_role:
        return True
    return actor.is_hr_role and not employee.user.is_admin_role


@hr_required
def employee_list(request):
    from departments.models import Department, Designation

    employees = Employee.objects.select_related("user", "department", "designation")
    q = request.GET.get("q", "").strip()
    if q:
        employees = employees.filter(
            Q(employee_id__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__email__icontains=q)
        )
    for param, field in (("department", "department_id"), ("designation", "designation_id")):
        value = request.GET.get(param, "")
        if value.isdigit():
            employees = employees.filter(**{field: int(value)})
    status = request.GET.get("status", "")
    if status in Employee.Status.values:
        employees = employees.filter(status=status)
    page_obj, querystring = paginate(request, employees)
    return render(
        request,
        "employees/list.html",
        {
            "page_obj": page_obj,
            "querystring": querystring,
            "departments": Department.objects.all(),
            "designations": Designation.objects.all(),
            "statuses": Employee.Status.choices,
            "filters": {"q": q, "department": request.GET.get("department", ""), "designation": request.GET.get("designation", ""), "status": status},
        },
    )


@hr_required
def employee_create(request):
    form = EmployeeForm(request.POST or None, request.FILES or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        employee = form.save()
        log_action(request.user, "employee_created", employee, f"{employee.employee_id} {employee.full_name}")
        messages.success(
            request,
            f"Employee {employee.full_name} created. Login: {employee.user.username} · "
            f"temporary password: {form.temp_password} (shown once — share securely and ask them to change it).",
        )
        return redirect("employees:detail", pk=employee.pk)
    return render(
        request,
        "generic_form.html",
        {"form": form, "title": "Add employee", "cancel_url": "employees:list", "submit_label": "Create employee", "multipart": True},
    )


@hr_required
def employee_edit(request, pk):
    employee = get_object_or_404(Employee.objects.select_related("user"), pk=pk)
    if not can_manage(request.user, employee):
        raise PermissionDenied
    old_role = employee.user.role
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=employee, actor=request.user)
    if request.method == "POST" and form.is_valid():
        employee = form.save()
        log_action(request.user, "employee_updated", employee, employee.employee_id)
        if employee.user.role != old_role:
            log_action(request.user, "user_role_changed", employee.user, f"{old_role} -> {employee.user.role}")
        messages.success(request, "Employee updated.")
        return redirect("employees:detail", pk=employee.pk)
    return render(
        request,
        "generic_form.html",
        {
            "form": form,
            "title": f"Edit {employee.full_name}",
            "cancel_url": "employees:detail",
            "cancel_args": [employee.pk],
            "submit_label": "Save changes",
            "multipart": True,
        },
    )


@login_required
def employee_detail(request, pk):
    employee = get_object_or_404(
        Employee.objects.select_related("user", "department", "designation", "reporting_manager__user"), pk=pk
    )
    user = request.user
    own = employee.user_id == user.pk
    if not (user.is_hr_or_admin or own):
        raise PermissionDenied

    from attendance.models import Attendance
    from leaves.services import balance_summary
    from payroll.models import Payroll, SalaryStructure

    today = timezone.localdate()
    start, end = month_bounds(today.year, today.month)
    month_records = Attendance.objects.filter(employee=employee, date__range=(start, end))
    summary = {label: month_records.filter(status=value).count() for value, label in Attendance.Status.choices}
    context = {
        "employee": employee,
        "own": own,
        "can_manage": user.is_hr_or_admin and can_manage(user, employee),
        "attendance_summary": summary,
        "balances": balance_summary(employee, today.year),
        "show_salary": user.is_payroll_manager,
    }
    if user.is_payroll_manager:
        context["structure"] = (
            SalaryStructure.objects.filter(employee=employee, is_active=True).order_by("-effective_date").first()
        )
    payslips = Payroll.objects.filter(employee=employee)
    if not user.is_payroll_manager:
        payslips = payslips.filter(status=Payroll.Status.APPROVED) if own else payslips.none()
    context["payslips"] = payslips[:6]
    return render(request, "employees/detail.html", context)


@hr_required
@require_POST
def employee_status(request, pk):
    employee = get_object_or_404(Employee.objects.select_related("user"), pk=pk)
    if not can_manage(request.user, employee):
        raise PermissionDenied
    if employee.user_id == request.user.pk:
        messages.error(request, "You cannot change your own employment status.")
        return redirect("employees:detail", pk=pk)
    action = request.POST.get("action")
    if action == "deactivate":
        employee.status = Employee.Status.INACTIVE
    elif action == "activate":
        employee.status = Employee.Status.ACTIVE
    else:
        messages.error(request, "Unknown action.")
        return redirect("employees:detail", pk=pk)
    employee.save(update_fields=["status", "updated_at"])
    employee.user.is_active = employee.status == Employee.Status.ACTIVE
    employee.user.save(update_fields=["is_active"])
    log_action(request.user, f"employee_{action}d", employee, employee.employee_id)
    messages.success(request, f"{employee.full_name} {action}d.")
    return redirect("employees:detail", pk=pk)
