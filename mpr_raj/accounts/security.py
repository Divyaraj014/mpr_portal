"""
Writing the security log. Every SecurityEvent row in the system is created here.

Nothing in this module may raise into a request: a logging failure must not stop
someone signing in. The accepted trade is that anyone able to cause database
errors could suppress logging — acceptable for monitoring, not for a formal audit.
"""
import logging

from axes.helpers import get_client_ip_address

from .models import SecurityEvent

logger = logging.getLogger(__name__)


def client_ip(request):
    """
    Axes owns this parse. Reading HTTP_X_FORWARDED_FOR by hand is spoofable — a
    client can forge its own address into the log.

    With AXES_IPWARE_PROXY_COUNT unset (the default) axes uses REMOTE_ADDR, which
    a client cannot forge but which behind a proxy is the proxy's own address.
    See the deployment note in the README before turning the proxy count on.
    """
    if request is None:
        return None
    try:
        return get_client_ip_address(request) or None
    except Exception:
        return request.META.get("REMOTE_ADDR") or None


def _name(user):
    return getattr(user, "username", "") or ""


def record(action, *, actor=None, actor_label="", target=None, target_label="",
           request=None, detail=""):
    """Write one event. Swallows its own failures by design — see module docstring."""
    try:
        SecurityEvent.objects.create(
            action=action,
            actor=actor if getattr(actor, "pk", None) else None,
            actor_label=(actor_label or _name(actor))[:150],
            target=target if getattr(target, "pk", None) else None,
            target_label=(target_label or _name(target))[:150],
            ip=client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "") if request else "")[:256],
            detail=detail,
        )
    except Exception:
        logger.exception("security event not recorded: %s", action)
