from datetime import date
from decimal import Decimal
from itertools import count

from accounts.models import User
from departments.models import Department, Designation
from employees.models import Employee
from leaves.models import LeaveType
from payroll.models import SalaryStructure

_seq = count(1)
PASSWORD = "Test-pass-12345"


def make_department(name=None):
    n = next(_seq)
    return Department.objects.create(name=name or f"Dept {n}", code=f"D{n}")


def make_designation(name=None):
    return Designation.objects.create(name=name or f"Title {next(_seq)}")


def make_employee(role=User.Role.EMPLOYEE, department=None, can_manage_payroll=False, **kwargs):
    n = next(_seq)
    user = User.objects.create_user(
        username=f"emp{n:04d}", email=f"emp{n}@example.test", password=PASSWORD,
        first_name=f"First{n}", last_name=f"Last{n}", role=role, can_manage_payroll=can_manage_payroll,
    )
    return Employee.objects.create(
        employee_id=f"EMP{n:04d}", user=user, department=department or make_department(),
        designation=make_designation(), joining_date=kwargs.pop("joining_date", date(2024, 1, 1)), **kwargs,
    )


def make_leave_type(name=None, allowance="10"):
    return LeaveType.objects.create(name=name or f"Leave {next(_seq)}", default_allowance=Decimal(allowance))


def make_structure(employee, basic="50000", allowances="10000", pf="12", tax="10", other="500", effective=date(2024, 1, 1)):
    return SalaryStructure.objects.create(
        employee=employee, basic_salary=Decimal(basic), allowances=Decimal(allowances), pf_percent=Decimal(pf),
        tax_percent=Decimal(tax), other_deductions=Decimal(other), effective_date=effective,
    )
