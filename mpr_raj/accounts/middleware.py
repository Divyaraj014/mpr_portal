from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Users with a temp password can't go anywhere until they set their own."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and request.user.must_change_password
            and request.path not in (reverse("password_change"), reverse("logout"))
        ):
            return redirect("password_change")
        return self.get_response(request)
