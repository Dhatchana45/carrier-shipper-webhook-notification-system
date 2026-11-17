
from django.contrib import messages
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods

from .api import api_request


@require_http_methods(["GET", "POST"])
def login_view(request):

    # Redirect an already authenticated user.
    if request.session.get("access_token"):
        return redirect("dashboard")

    if request.method == "POST":

        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")

        if not email or not password:
            messages.error(
                request,
                "Email and password are required."
            )
            return render(
                request,
                "auth/login.html",
                {"email": email}
            )

        # Authenticate with FastAPI.
        result, error = api_request(
            request,
            "POST",
            "/auth/login",
            json={
                "email": email,
                "password": password,
            },
        )

        if error:
            messages.error(request, error)
            return render(
                request,
                "auth/login.html",
                {"email": email}
            )

        if (
            not isinstance(result, dict)
            or not result.get("access_token")
        ):
            messages.error(
                request,
                "The backend returned an invalid login response."
            )
            return render(
                request,
                "auth/login.html",
                {"email": email}
            )

        user = result.get("user") or {}

        if not user.get("is_active", False):
            messages.error(request, "This account is inactive.")
            return render(
                request,
                "auth/login.html",
                {"email": email}
            )

        role = str(user.get("role", "")).lower()

        if role not in ("admin", "carrier", "shipper"):
            messages.error(
                request,
                "Your account does not have an authorized role."
            )
            return render(
                request,
                "auth/login.html",
                {"email": email}
            )

        # Prevent session fixation.
        request.session.flush()

        # Store authenticated session.
        request.session["access_token"] = result["access_token"]
        request.session["api_user"] = user
        request.session["api_role"] = role

        # Set session lifetime based on JWT expiry.
        expires_in = result.get("expires_in", 1800)

        try:
            expires_in = max(60, int(expires_in))
        except (TypeError, ValueError):
            expires_in = 1800

        request.session.set_expiry(expires_in)

        messages.success(
            request,
            f"Welcome, {user.get('username', 'User')}."
        )

        return redirect("dashboard")

    return render(request, "auth/login.html")


@require_http_methods(["POST"])
def logout_view(request):

    request.session.flush()

    messages.success(
        request,
        "You have been logged out."
    )

    return redirect("login")
