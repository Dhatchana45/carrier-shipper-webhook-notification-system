
import json

from django.contrib import messages
from django.shortcuts import render, redirect

from core.api import api_request, get_api_list
from core.decorators import login_required, role_required


# --------------------------------------------------
# Event List
# --------------------------------------------------

@login_required
@role_required("admin", "carrier", "shipper")
def event_list(request):
    events, error = get_api_list(request, "/events/")

    if error:
        messages.error(request, f"Could not load events: {error}")
        events = []

    return render(
        request,
        "events/list.html",
        {
            "events": events,
            "active_page": "events",
        }
    )


# --------------------------------------------------
# Create Event
# Admin only
# --------------------------------------------------

@login_required
@role_required("admin")
def event_create(request):
    if request.method == "POST":
        event_type = request.POST.get("event_type", "").strip()
        idempotency_key = request.POST.get("idempotency_key", "").strip()
        payload_text = request.POST.get("payload", "{}").strip()

        form_data = {
            "event_type": event_type,
            "idempotency_key": idempotency_key,
            "payload": payload_text,
        }

        if not event_type:
            messages.error(request, "Event type is required.")

            return render(
                request,
                "events/create.html",
                {
                    "form_data": form_data,
                    "active_page": "events",
                }
            )

        try:
            payload = json.loads(payload_text)

            if not isinstance(payload, dict):
                raise ValueError("Payload must be a JSON object.")

        except (json.JSONDecodeError, ValueError) as exc:
            messages.error(request, f"Invalid JSON payload: {exc}")

            return render(
                request,
                "events/create.html",
                {
                    "form_data": form_data,
                    "active_page": "events",
                }
            )

        event_data = {
            "event_type": event_type,
            "payload": payload,
        }

        if idempotency_key:
            event_data["idempotency_key"] = idempotency_key

        result, error = api_request(
            request,
            "POST",
            "/events/",
            json=event_data,
        )

        if error:
            messages.error(request, f"Could not create event: {error}")

            return render(
                request,
                "events/create.html",
                {
                    "form_data": form_data,
                    "active_page": "events",
                }
            )

        messages.success(request, "Event created successfully.")
        return redirect("event_list")

    return render(
        request,
        "events/create.html",
        {
            "active_page": "events",
        }
    )


# --------------------------------------------------
# Event Details
# --------------------------------------------------

@login_required
@role_required("admin", "carrier", "shipper")
def event_detail(request, event_id):
    event, error = api_request(
        request,
        "GET",
        f"/events/{event_id}",
    )

    if error:
        messages.error(request, f"Could not load event: {error}")
        return redirect("event_list")

    return render(
        request,
        "events/detail.html",
        {
            "event": event,
            "active_page": "events",
        }
    )
