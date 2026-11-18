from django.contrib import admin

from .models import Payroll, SalaryStructure

admin.site.register(SalaryStructure)
admin.site.register(Payroll)
