from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.permissions import hr_required
from core.utils import paginate, parse_int, safe_redirect

from . import services
from .forms import LeaveRequestForm
from .models import LeaveRequest, LeaveType


def _visible(user):
    qs = LeaveRequest.objects.select_related("employee__user", "employee__department", "leave_type", "reviewer")
    if user.is_hr_or_admin:
        return qs
    employee = user.employee_profile
    return qs.filter(employee=employee) if employee else qs.none()


@login_required
def leave_list(request):
    leaves = _visible(request.user)
    status = request.GET.get("status", "")
    if status in LeaveRequest.Status.values:
        leaves = leaves.filter(status=status)
    leave_type = request.GET.get("leave_type", "")
    if leave_type.isdigit():
        leaves = leaves.filter(leave_type_id=int(leave_type))
    q = request.GET.get("q", "").strip()
    if q and request.user.is_hr_or_admin:
        leaves = leaves.filter(
            Q(employee__employee_id__icontains=q)
            | Q(employee__user__first_name__icontains=q)
            | Q(employee__user__last_name__icontains=q)
        )
    page_obj, querystring = paginate(request, leaves, per_page=20)
    return render(
        request,
        "leaves/list.html",
        {
            "page_obj": page_obj,
            "querystring": querystring,
            "statuses": LeaveRequest.Status.choices,
            "leave_types": LeaveType.objects.all(),
            "filters": {"status": status, "leave_type": leave_type, "q": q},
        },
    )


@login_required
def leave_apply(request):
    employee = request.user.employee_profile
    if employee is None or employee.status != "active":
        raise PermissionDenied
    form = LeaveRequestForm(request.POST or None, employee=employee)
    if request.method == "POST" and form.is_valid():
        leave = form.save()
        messages.success(request, f"Leave request submitted for {leave.days} working day(s).")
        return redirect("leaves:detail", pk=leave.pk)
    return render(
        request,
        "generic_form.html",
        {"form": form, "title": "Apply for leave", "cancel_url": "leaves:list", "submit_label": "Submit request"},
    )


@login_required
def leave_detail(request, pk):
    leave = get_object_or_404(_visible(request.user), pk=pk)  # employees get 404 for others' requests
    user = request.user
    own = leave.employee.user_id == user.pk
    can_review = user.is_hr_or_admin and not own and leave.status == LeaveRequest.Status.PENDING
    can_cancel = (own or user.is_hr_or_admin) and leave.status in (LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED)
    return render(request, "leaves/detail.html", {"leave": leave, "can_review": can_review, "can_cancel": can_cancel})


@login_required
def leave_balances(request):
    user = request.user
    year = parse_int(request.GET.get("year"), timezone.localdate().year, 2000, 2100)
    employee = user.employee_profile
    if user.is_hr_or_admin and request.GET.get("employee", "").isdigit():
        from employees.models import Employee

        employee = get_object_or_404(Employee, pk=int(request.GET["employee"]))
    if employee is None:
        raise PermissionDenied
    history = LeaveRequest.objects.filter(employee=employee, start_date__year=year).select_related("leave_type")
    return render(
        request,
        "leaves/balances.html",
        {"employee": employee, "year": year, "balances": services.balance_summary(employee, year), "history": history},
    )


def _review(request, pk, action):
    comments = request.POST.get("comments", "").strip()[:1000]
    try:
        if action == "approve":
            services.approve_request(pk, request.user, comments)
            messages.success(request, "Leave approved and balance updated.")
        else:
            services.reject_request(pk, request.user, comments)
            messages.success(request, "Leave rejected.")
    except LeaveRequest.DoesNotExist:
        raise Http404
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return safe_redirect(request, "leaves:detail", pk=pk)


@hr_required
@require_POST
def leave_approve(request, pk):
    return _review(request, pk, "approve")


@hr_required
@require_POST
def leave_reject(request, pk):
    return _review(request, pk, "reject")


@login_required
@require_POST
def leave_cancel(request, pk):
    get_object_or_404(_visible(request.user), pk=pk)
    try:
        services.cancel_request(pk, request.user)
        messages.success(request, "Leave request cancelled.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("leaves:detail", pk=pk)
