from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def _guard(check):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


admin_required = _guard(lambda u: u.is_admin_role)
hr_required = _guard(lambda u: u.is_hr_or_admin)
payroll_required = _guard(lambda u: u.is_payroll_manager)
