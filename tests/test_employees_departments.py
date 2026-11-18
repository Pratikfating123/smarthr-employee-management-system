from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from departments.models import Department
from employees.models import Employee

from .factories import PASSWORD, make_department, make_designation, make_employee


class EmployeeCrudTests(TestCase):
    def setUp(self):
        self.hr = make_employee(role=User.Role.HR)
        self.client.login(username=self.hr.user.username, password=PASSWORD)
        self.dept = make_department()
        self.desig = make_designation()

    def payload(self, **overrides):
        data = {
            "employee_id": "EMP9001", "first_name": "Test", "last_name": "Person", "work_email": "test.person@example.test",
            "phone": "123", "department": self.dept.pk, "designation": self.desig.pk, "joining_date": "2025-01-06",
            "employment_type": "full_time", "status": "active",
        }
        data.update(overrides)
        return data

    def test_create_makes_employee_user_with_login(self):
        resp = self.client.post(reverse("employees:create"), self.payload())
        emp = Employee.objects.get(employee_id="EMP9001")
        self.assertRedirects(resp, reverse("employees:detail", args=[emp.pk]))
        self.assertEqual(emp.user.role, User.Role.EMPLOYEE)
        self.assertTrue(emp.user.has_usable_password())

    def test_duplicate_employee_id_rejected(self):
        self.client.post(reverse("employees:create"), self.payload())
        resp = self.client.post(reverse("employees:create"), self.payload(work_email="other@example.test"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Employee.objects.filter(employee_id="EMP9001").count(), 1)

    def test_duplicate_email_rejected(self):
        self.client.post(reverse("employees:create"), self.payload())
        resp = self.client.post(reverse("employees:create"), self.payload(employee_id="EMP9002"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Employee.objects.filter(employee_id="EMP9002").exists())

    def test_hr_cannot_assign_roles(self):
        self.client.post(reverse("employees:create"), self.payload(role="admin"))
        self.assertEqual(Employee.objects.get(employee_id="EMP9001").user.role, User.Role.EMPLOYEE)

    def test_edit_updates_user_fields(self):
        self.client.post(reverse("employees:create"), self.payload())
        emp = Employee.objects.get(employee_id="EMP9001")
        resp = self.client.post(reverse("employees:edit", args=[emp.pk]), self.payload(first_name="Renamed"))
        self.assertRedirects(resp, reverse("employees:detail", args=[emp.pk]))
        emp.user.refresh_from_db()
        self.assertEqual(emp.user.first_name, "Renamed")

    def test_deactivate_and_reactivate(self):
        target = make_employee()
        self.client.post(reverse("employees:status", args=[target.pk]), {"action": "deactivate"})
        target.refresh_from_db()
        target.user.refresh_from_db()
        self.assertEqual(target.status, "inactive")
        self.assertFalse(target.user.is_active)
        self.client.post(reverse("employees:status", args=[target.pk]), {"action": "activate"})
        target.refresh_from_db()
        self.assertEqual(target.status, "active")

    def test_hr_cannot_edit_admin(self):
        admin = make_employee(role=User.Role.ADMIN)
        self.assertEqual(self.client.get(reverse("employees:edit", args=[admin.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("employees:status", args=[admin.pk]), {"action": "deactivate"}).status_code, 403)

    def test_cannot_deactivate_self(self):
        self.client.post(reverse("employees:status", args=[self.hr.pk]), {"action": "deactivate"})
        self.hr.refresh_from_db()
        self.assertEqual(self.hr.status, "active")

    def test_search_and_filter(self):
        a = make_employee(department=self.dept)
        make_employee()
        resp = self.client.get(reverse("employees:list"), {"q": a.employee_id})
        self.assertContains(resp, a.employee_id)
        self.assertEqual(resp.context["page_obj"].paginator.count, 1)
        resp = self.client.get(reverse("employees:list"), {"department": self.dept.pk})
        self.assertEqual(resp.context["page_obj"].paginator.count, 1)

    def test_employee_delete_protected_by_attendance(self):
        from django.db.models import ProtectedError
        from attendance.models import Attendance

        emp = make_employee()
        Attendance.objects.create(employee=emp, date=date(2026, 1, 5), status="present")
        with self.assertRaises(ProtectedError):
            emp.delete()


class DepartmentCrudTests(TestCase):
    def setUp(self):
        self.hr = make_employee(role=User.Role.HR)
        self.client.login(username=self.hr.user.username, password=PASSWORD)

    def test_create_edit(self):
        resp = self.client.post(reverse("departments:create"), {"name": "Legal", "code": "leg", "description": "", "is_active": "on"})
        self.assertRedirects(resp, reverse("departments:list"))
        dept = Department.objects.get(name="Legal")
        self.assertEqual(dept.code, "LEG")
        self.client.post(reverse("departments:edit", args=[dept.pk]), {"name": "Legal & Compliance", "code": "LEG", "description": "", "is_active": "on"})
        dept.refresh_from_db()
        self.assertEqual(dept.name, "Legal & Compliance")

    def test_duplicate_code_rejected(self):
        make_department("Ops")
        existing = Department.objects.get(name="Ops")
        resp = self.client.post(reverse("departments:create"), {"name": "Other", "code": existing.code, "is_active": "on"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Department.objects.filter(name="Other").exists())

    def test_cannot_deactivate_with_active_employees(self):
        dept = make_department()
        make_employee(department=dept)
        self.client.post(reverse("departments:toggle", args=[dept.pk]))
        dept.refresh_from_db()
        self.assertTrue(dept.is_active)

    def test_toggle_empty_department(self):
        dept = make_department()
        self.client.post(reverse("departments:toggle", args=[dept.pk]))
        dept.refresh_from_db()
        self.assertFalse(dept.is_active)

    def test_employee_counts_on_list(self):
        dept = make_department()
        make_employee(department=dept)
        make_employee(department=dept)
        resp = self.client.get(reverse("departments:list"))
        row = [d for d in resp.context["departments"] if d.pk == dept.pk][0]
        self.assertEqual(row.employee_count, 2)
