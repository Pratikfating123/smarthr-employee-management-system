from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.permissions import payroll_required
from core.utils import paginate, parse_int

from . import services
from .forms import PayrollGenerateForm, SalaryStructureForm
from .models import Payroll, SalaryStructure


@login_required
def payroll_list(request):
    user = request.user
    payrolls = Payroll.objects.select_related("employee__user", "employee__department")
    if user.is_payroll_manager:
        q = request.GET.get("q", "").strip()
        if q:
            payrolls = payrolls.filter(
                Q(employee__employee_id__icontains=q)
                | Q(employee__user__first_name__icontains=q)
                | Q(employee__user__last_name__icontains=q)
            )
        status = request.GET.get("status", "")
        if status in Payroll.Status.values:
            payrolls = payrolls.filter(status=status)
        payment = request.GET.get("payment", "")
        if payment in Payroll.PaymentStatus.values:
            payrolls = payrolls.filter(payment_status=payment)
    elif user.employee_profile is not None:
        # Employees: only their own approved payslips.
        payrolls = payrolls.filter(employee=user.employee_profile, status=Payroll.Status.APPROVED)
        q = status = payment = ""
    else:
        raise PermissionDenied
    year = parse_int(request.GET.get("year"), None, 2000, 2100)
    month = parse_int(request.GET.get("month"), None, 1, 12)
    if year:
        payrolls = payrolls.filter(year=year)
    if month:
        payrolls = payrolls.filter(month=month)
    page_obj, querystring = paginate(request, payrolls, per_page=20)
    return render(
        request,
        "payroll/list.html",
        {
            "page_obj": page_obj,
            "querystring": querystring,
            "statuses": Payroll.Status.choices,
            "payments": Payroll.PaymentStatus.choices,
            "filters": {"q": q, "status": status, "payment": payment, "year": year or "", "month": month or ""},
        },
    )


@payroll_required
def payroll_create(request):
    form = PayrollGenerateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        result = services.generate_payroll(data["year"], data["month"], request.user, data.get("employee"))
        messages.success(
            request,
            f"Created {result['created']} payroll record(s); {result['existing']} already existed; "
            f"{result['no_structure']} skipped (no salary structure); {result['invalid']} skipped (invalid structure).",
        )
        return redirect("payroll:list")
    return render(
        request,
        "generic_form.html",
        {
            "form": form,
            "title": "Generate payroll",
            "intro": "Creates one payroll record per employee per month from their salary structure. Existing records are never overwritten.",
            "cancel_url": "payroll:list",
            "submit_label": "Generate payroll",
        },
    )


@login_required
def payroll_detail(request, pk):
    payroll = get_object_or_404(Payroll.objects.select_related("employee__user", "employee__department", "employee__designation", "approved_by", "generated_by"), pk=pk)
    user = request.user
    if not user.is_payroll_manager:
        own = payroll.employee.user_id == user.pk
        if not (own and payroll.status == Payroll.Status.APPROVED):
            raise Http404  # do not reveal that other payslips exist
    return render(
        request,
        "payroll/detail.html",
        {"payroll": payroll, "payment_statuses": Payroll.PaymentStatus.choices, "manager": user.is_payroll_manager},
    )


def _action(request, pk, func, success, *args):
    payroll = get_object_or_404(Payroll, pk=pk)
    try:
        func(pk, request.user, *args)
        messages.success(request, success)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("payroll:detail", pk=payroll.pk)


@payroll_required
@require_POST
def payroll_approve(request, pk):
    return _action(request, pk, services.approve_payroll, "Payroll approved. The employee has been notified.")


@payroll_required
@require_POST
def payroll_payment(request, pk):
    return _action(request, pk, services.set_payment_status, "Payment status updated.", request.POST.get("payment_status", ""))


@payroll_required
def structure_list(request):
    structures = SalaryStructure.objects.select_related("employee__user")
    page_obj, querystring = paginate(request, structures, per_page=20)
    return render(request, "payroll/structures.html", {"page_obj": page_obj, "querystring": querystring})


@payroll_required
def structure_create(request):
    form = SalaryStructureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        structure = form.save()
        log_action(request.user, "salary_structure_created", structure, structure.employee.employee_id)
        messages.success(request, "Salary structure saved.")
        return redirect("payroll:structures")
    return render(
        request,
        "generic_form.html",
        {"form": form, "title": "New salary structure", "cancel_url": "payroll:structures", "submit_label": "Save structure"},
    )


@payroll_required
def structure_edit(request, pk):
    structure = get_object_or_404(SalaryStructure, pk=pk)
    form = SalaryStructureForm(request.POST or None, instance=structure)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(request.user, "salary_structure_updated", structure, structure.employee.employee_id)
        messages.success(request, "Salary structure updated. Existing payroll records are unchanged.")
        return redirect("payroll:structures")
    return render(
        request,
        "generic_form.html",
        {"form": form, "title": f"Edit structure · {structure.employee.employee_id}", "cancel_url": "payroll:structures", "submit_label": "Save changes"},
    )
