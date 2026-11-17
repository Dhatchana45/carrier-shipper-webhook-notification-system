
from django.contrib import messages
from django.shortcuts import render

from core.api import api_request, get_api_list
from core.decorators import login_required, role_required


# --------------------------------------------------
# Delivery List
# --------------------------------------------------

@login_required
@role_required("admin", "carrier", "shipper")
def delivery_list(request):
    deliveries, error = get_api_list(request, "/deliveries/")

    if error:
        messages.error(request, f"Could not load deliveries: {error}")
        deliveries = []

    successful_count = sum(
        1 for delivery in deliveries
        if str(delivery.get("status", "")).lower() == "succeeded"
    )

    failed_count = sum(
        1 for delivery in deliveries
        if str(delivery.get("status", "")).lower() == "failed"
    )

    pending_count = sum(
        1 for delivery in deliveries
        if str(delivery.get("status", "")).lower()
        in ["pending", "retrying", "processing", "paused"]
    )

    return render(
        request,
        "deliveries/list.html",
        {
            "deliveries": deliveries,
            "successful_count": successful_count,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "active_page": "deliveries",
        }
    )


# --------------------------------------------------
# Delivery Details
# --------------------------------------------------

@login_required
@role_required("admin", "carrier", "shipper")
def delivery_detail(request, delivery_id):
    delivery, error = api_request(
        request,
        "GET",
        f"/deliveries/{delivery_id}",
    )

    if error:
        messages.error(request, f"Could not load delivery: {error}")

        return render(
            request,
            "deliveries/detail.html",
            {
                "delivery": None,
                "attempts": [],
                "active_page": "deliveries",
                "error": error,
            }
        )

    attempts, attempts_error = get_api_list(
        request,
        f"/deliveries/{delivery_id}/attempts",
    )

    if attempts_error:
        messages.warning(
            request,
            f"Could not load attempt history: {attempts_error}"
        )
        attempts = []

    # Determine each attempt's result in Python.
    for attempt in attempts:
        status_code = attempt.get("http_status_code")
        error_message = attempt.get("error_message")

        if error_message:
            attempt["result_status"] = "Failed"
            attempt["result_class"] = "failed"

        elif isinstance(status_code, int) and 200 <= status_code < 300:
            attempt["result_status"] = "Success"
            attempt["result_class"] = "success"

        elif status_code is not None:
            attempt["result_status"] = "HTTP Error"
            attempt["result_class"] = "failed"

        else:
            attempt["result_status"] = "No Response"
            attempt["result_class"] = "pending"

    return render(
        request,
        "deliveries/detail.html",
        {
            "delivery": delivery,
            "attempts": attempts,
            "active_page": "deliveries",
        }
    )
