import csv
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from openpyxl import Workbook

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value):
    """Neutralise spreadsheet formula injection: text starting with = + - @ is prefixed with an apostrophe."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def _plain(value):
    value = safe_text(value)
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def csv_response(filename, headers, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
    writer = csv.writer(response)
    writer.writerow([_plain(h) for h in headers])
    for row in rows:
        writer.writerow([_plain(v) for v in row])
    return response


def xlsx_response(filename, headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    sheet.append([safe_text(h) for h in headers])
    for row in rows:
        sheet.append([safe_text(v) if not isinstance(v, Decimal) else float(v) for v in row])
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    workbook.save(response)
    return response
