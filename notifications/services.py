from .models import Notification


def notify(user, message, url=""):
    """Create an in-app notification. `url` must be an internal path (starts with '/')."""
    if user is None:
        return None
    if url and not url.startswith("/"):
        url = ""
    return Notification.objects.create(user=user, message=message[:255], url=url)


def notify_hr(message, url=""):
    from accounts.models import User

    for user in User.objects.filter(is_active=True, role__in=[User.Role.ADMIN, User.Role.HR]):
        notify(user, message, url)
