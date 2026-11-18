def smarthr(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    from notifications.models import Notification

    unread = Notification.objects.filter(user=user, is_read=False)
    return {
        "unread_count": unread.count(),
        "recent_notifications": unread[:5],
        "nav_namespace": request.resolver_match.namespace if request.resolver_match else "",
    }
