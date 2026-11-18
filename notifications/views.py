from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.utils import paginate

from .models import Notification


@login_required
def notification_list(request):
    page_obj, querystring = paginate(request, Notification.objects.filter(user=request.user), per_page=20)
    return render(request, "notifications/list.html", {"page_obj": page_obj, "querystring": querystring})


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("notifications:list")


@login_required
@require_POST
def mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    return redirect(notification.url if notification.url.startswith("/") else "notifications:list")
