
from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get("access_token"):
            messages.warning(request, "Please log in to continue.")
            return redirect("login")

        return view_func(request, *args, **kwargs)

    return wrapper


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.session.get("access_token"):
                messages.warning(request, "Please log in to continue.")
                return redirect("login")

            role = request.session.get("api_role")

            if role not in allowed_roles:
                messages.error(
                    request,
                    "You do not have permission to access this page."
                )
                return redirect("dashboard")

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
