"""The admin-only security log: list, filter, and the lockout override."""
from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.shortcuts import render

from ..models import SecurityEvent
from .master import admin_required

PER_PAGE = 100


def _filtered(request):
    """(queryset, kept, filters) — shared with the text export so the two can't drift."""
    events = SecurityEvent.objects.select_related("actor", "target")

    user = request.GET.get("user", "").strip()
    action = request.GET.get("action", "")
    if user:
        # actor_label, not the FK: a failed sign-in can name a user that never existed.
        events = events.filter(actor_label__icontains=user)
    if action in dict(SecurityEvent.ACTIONS):
        events = events.filter(action=action)

    kept = {k: v for k, v in (("user", user), ("action", action)) if v}
    filters = [
        {"name": "user", "label": "User", "blank": "Any login ID", "selected": user,
         "type": "text", "options": []},
        {"name": "action", "label": "Event", "blank": "Any event", "selected": action,
         "options": SecurityEvent.ACTIONS},
    ]
    return events, kept, filters


@admin_required
def security_log(request):
    """
    Unlike the master lists this one paginates: retention is keep-everything and
    every sign-in adds a row, so it grows without bound.
    """
    events, kept, filters = _filtered(request)
    page = Paginator(events, PER_PAGE).get_page(request.GET.get("page"))

    return render(request, "accounts/security_log.html", {
        "events": page, "page": page,
        # Filters ride along in the page links so a filtered view stays linkable.
        "qs": ("&" + urlencode(kept)) if kept else "",
        "filters": filters, "filtered": bool(kept),
        "showing": page.paginator.count, "total": SecurityEvent.objects.count(),
        "clear_url": "security_log",
    })
