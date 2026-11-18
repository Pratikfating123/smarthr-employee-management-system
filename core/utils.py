import calendar
from datetime import date

from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def paginate(request, queryset, per_page=15):
    page_obj = Paginator(queryset, per_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page_obj, params.urlencode()


def safe_redirect(request, default, **kwargs):
    """Redirect to POSTed/GET 'next' only if it points back to this host."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect(default, **kwargs)


def parse_date(value, default=None):
    try:
        return date.fromisoformat(value) if value else default
    except (TypeError, ValueError):
        return default


def parse_int(value, default=None, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        return default
    return number


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
