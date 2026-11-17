
from django.contrib import messages
from django.shortcuts import render, redirect

from core.api import api_request, get_api_list
from core.decorators import login_required


@login_required
def webhook_list(request):
    """Display webhooks belonging to the logged-in user."""

    webhooks, error = get_api_list(request, "/webhooks/")

    if error:
        messages.error(
            request,
            f"Could not load webhooks: {error}"
        )
        webhooks = []

    active_filter = request.GET.get("status", "all")

    if active_filter == "active":
        webhooks = [
            webhook for webhook in webhooks
            if webhook.get("is_active") is True
        ]

    elif active_filter == "inactive":
        webhooks = [
            webhook for webhook in webhooks
            if webhook.get("is_active") is False
        ]

    return render(
        request,
        "webhooks/list.html",
        {
            "webhooks": webhooks,
            "active_filter": active_filter,
        }
    )


@login_required
def webhook_create(request):
    """Create a webhook using the logged-in user's JWT."""

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        target_url = request.POST.get("target_url", "").strip()
        secret = request.POST.get("secret", "").strip()

        event_types_text = request.POST.get(
            "subscribed_event_types", ""
        )

        subscribed_event_types = [
            event.strip()
            for event in event_types_text.replace(
                "\n", ","
            ).split(",")
            if event.strip()
        ]

        payload = {
            "name": name,
            "target_url": target_url,
            "subscribed_event_types": subscribed_event_types,
            "is_active": request.POST.get("is_active") == "on",
        }

        if secret:
            payload["secret"] = secret

        data, error = api_request(
            request,
            "POST",
            "/webhooks/",
            json=payload,
        )

        if error:
            messages.error(
                request,
                f"Unable to create webhook: {error}"
            )

            return render(
                request,
                "webhooks/form.html",
                {
                    "page_title": "Create Webhook",
                    "is_edit": False,
                    "error": error,
                    "form_data": request.POST,
                }
            )

        messages.success(
            request,
            "Webhook created successfully."
        )

        return redirect("webhook_list")

    return render(
        request,
        "webhooks/form.html",
        {
            "page_title": "Create Webhook",
            "is_edit": False,
            "form_data": {},
        }
    )


@login_required
def webhook_edit(request, webhook_id):
    """Edit an existing webhook."""

    if request.method == "POST":

        event_types = [
            item.strip()
            for item in request.POST.get(
                "subscribed_event_types", ""
            ).replace(",", "\n").splitlines()
            if item.strip()
        ]

        payload = {
            "name": request.POST.get("name", "").strip(),
            "target_url": request.POST.get("target_url", "").strip(),
            "subscribed_event_types": event_types,
            "is_active": request.POST.get("is_active") == "on",
        }

        secret = request.POST.get("secret", "").strip()

        if secret:
            payload["secret"] = secret

        data, error = api_request(
            request,
            "PATCH",
            f"/webhooks/{webhook_id}",
            json=payload,
        )

        if error:
            messages.error(
                request,
                f"Unable to update webhook: {error}"
            )

            return render(
                request,
                "webhooks/form.html",
                {
                    "page_title": "Edit Webhook",
                    "is_edit": True,
                    "error": error,
                    "form_data": request.POST,
                }
            )

        messages.success(
            request,
            "Webhook updated successfully."
        )

        return redirect("webhook_list")

    # GET: retrieve the existing webhook

    webhook, error = api_request(
        request,
        "GET",
        f"/webhooks/{webhook_id}",
    )

    if error:
        messages.error(
            request,
            f"Unable to load webhook: {error}"
        )
        return redirect("webhook_list")

    return render(
        request,
        "webhooks/form.html",
        {
            "webhook": webhook,
            "is_edit": True,
            "page_title": "Edit Webhook",
            "form_data": {},
        }
    )


@login_required
def webhook_delete(request, webhook_id):
    """Delete (soft-delete) an existing webhook."""

    if request.method == "POST":

        data, error = api_request(
            request,
            "DELETE",
            f"/webhooks/{webhook_id}",
        )

        if error:
            messages.error(
                request,
                f"Unable to delete webhook: {error}"
            )
        else:
            messages.success(
                request,
                "Webhook deleted successfully."
            )

        return redirect("webhook_list")

    # GET: show the delete confirmation page

    webhook, error = api_request(
        request,
        "GET",
        f"/webhooks/{webhook_id}",
    )

    if error:
        messages.error(
            request,
            f"Unable to load webhook: {error}"
        )
        return redirect("webhook_list")

    return render(
        request,
        "webhooks/delete.html",
        {
            "webhook": webhook
        }
    )
