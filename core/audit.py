from .models import AuditLog


def log_action(actor, action, target=None, summary=""):
    """Record an administrative action. Never pass passwords, tokens or sensitive personal data in summary."""
    AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        target_type=target.__class__.__name__ if target is not None else "",
        target_id=str(target.pk) if target is not None and target.pk is not None else "",
        summary=(summary or "")[:255],
    )
