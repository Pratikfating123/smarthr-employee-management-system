import calendar

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render

from attendance.models import Attendance
from core.utils import paginate
from departments.models import Department
from employees.models import Employee
from leaves.models import LeaveRequest
from payroll.models import Payroll

from . import builders
from .exports import csv_response, xlsx_response


def _hr(user):
    return user.is_hr_or_admin


def _payroll(user):
    return user.is_payroll_manager


# slug -> definition. `filters` names the controls shown above the report.
REPORTS = {
    "employee-directory": {"title": "Employee directory", "build": builders.employee_directory, "perm": _hr,
                           "filters": ["department", "status"], "statuses": Employee.Status.choices,
                           "blurb": "All employees with department, designation and status."},
    "department-headcount": {"title": "Department headcount", "build": builders.department_headcount, "perm": _hr,
                             "filters": [], "blurb": "Active and total employees per department."},
    "daily-attendance": {"title": "Daily attendance", "build": builders.daily_attendance, "perm": _hr,
                         "filters": ["date", "department", "status"], "statuses": Attendance.Status.choices,
                         "blurb": "Every attendance record for one day."},
    "monthly-attendance": {"title": "Monthly attendance summary", "build": builders.monthly_attendance, "perm": _hr,
                           "filters": ["year", "month", "department"], "blurb": "Per-employee status counts for a month."},
    "late-arrivals": {"title": "Late arrivals", "build": builders.late_arrivals_report, "perm": _hr,
                      "filters": ["date_from", "date_to", "department"], "blurb": "Late check-ins in a date range."},
    "missing-punches": {"title": "Missing punches", "build": builders.missing_punches_report, "perm": _hr,
                        "filters": ["date_from", "date_to", "department"], "blurb": "Records with only a check-in or only a check-out."},
    "leave-history": {"title": "Leave requests & approvals", "build": builders.leave_history, "perm": _hr,
                      "filters": ["date_from", "date_to", "department", "status"], "statuses": LeaveRequest.Status.choices,
                      "blurb": "Leave requests with reviewer and decision details."},
    "leave-utilization": {"title": "Leave utilization", "build": builders.leave_utilization, "perm": _hr,
                          "filters": ["year", "department"], "blurb": "Allocated, used and remaining leave per employee."},
    "payroll-summary": {"title": "Monthly payroll summary", "build": builders.payroll_summary, "perm": _payroll,
                        "filters": ["year", "month", "department", "status"], "statuses": Payroll.Status.choices,
                        "blurb": "Gross, deductions and net pay for a month."},
}


@login_required
def report_index(request):
    if not request.user.is_hr_or_admin:
        raise PermissionDenied
    available = [{"slug": s, **spec} for s, spec in REPORTS.items() if spec["perm"](request.user)]
    return render(request, "reports/index.html", {"reports": available})


@login_required
def report_detail(request, slug):
    spec = REPORTS.get(slug)
    if spec is None:
        raise Http404
    if not spec["perm"](request.user):
        raise PermissionDenied  # same rule applies to the on-screen report and its exports
    headers, rows = spec["build"](request)
    export = request.GET.get("export")
    if export == "csv":
        return csv_response(slug, headers, rows)
    if export == "xlsx":
        return xlsx_response(slug, headers, rows)
    page_obj, querystring = paginate(request, rows, per_page=50)
    params = request.GET.copy()
    params.pop("export", None)
    params.pop("page", None)
    return render(
        request,
        "reports/detail.html",
        {
            "slug": slug,
            "spec": spec,
            "headers": headers,
            "page_obj": page_obj,
            "querystring": querystring,
            "export_query": params.urlencode(),
            "total": len(rows),
            "departments": Department.objects.all(),
            "months": [(i, calendar.month_name[i]) for i in range(1, 13)],
            "get": request.GET,
        },
    )
