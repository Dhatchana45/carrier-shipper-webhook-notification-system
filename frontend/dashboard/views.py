
import logging

from django.shortcuts import render

from core.api import get_api_list
from core.decorators import login_required


logger = logging.getLogger(__name__)


def get_created_at(item):
    return str(item.get("created_at") or "")


def get_attempt_time(item):
    return str(item.get("started_at") or "")


def safe_int(value, default=0):
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


@login_required
def dashboard_home(request):

    role = request.session.get("api_role", "")

    # --------------------------------------------------
    # Fetch role-accessible authenticated data
    # --------------------------------------------------

    endpoints = {
        "webhooks": "/webhooks/",
        "events": "/events/",
        "deliveries": "/deliveries/",
        "attempts": "/deliveries/attempts/all",
        "loads": "/loads/",
    }

    if role == "admin":
        endpoints.update({
            "carriers": "/carriers/",
            "drivers": "/drivers/",
        })

    elif role == "carrier":
        endpoints["drivers"] = "/drivers/"

    api_data = {
        "webhooks": [],
        "events": [],
        "deliveries": [],
        "attempts": [],
        "loads": [],
        "carriers": [],
        "drivers": [],
    }

    for key, endpoint in endpoints.items():
        data, error = get_api_list(request, endpoint)

        if error:
            logger.warning(
                "Dashboard API request failed for %s: %s",
                endpoint,
                error,
            )
        else:
            api_data[key] = data

    webhooks = api_data["webhooks"]
    events = api_data["events"]
    deliveries = api_data["deliveries"]
    attempts = api_data["attempts"]
    loads = api_data["loads"]
    carriers = api_data["carriers"]
    drivers = api_data["drivers"]

    # --------------------------------------------------
    # Webhook statistics
    # --------------------------------------------------

    active_webhooks = [
        webhook for webhook in webhooks
        if webhook.get("is_active") is True
    ]

    inactive_webhooks = [
        webhook for webhook in webhooks
        if webhook.get("is_active") is False
    ]

    open_circuits = [
        webhook for webhook in webhooks
        if str(webhook.get("circuit_state", "")).lower() == "open"
    ]

    half_open_circuits = [
        webhook for webhook in webhooks
        if str(webhook.get("circuit_state", "")).lower() == "half_open"
    ]

    # --------------------------------------------------
    # Event statistics
    # --------------------------------------------------

    event_type_counts = {}

    for event in events:
        event_type = event.get("event_type") or "unknown"
        event_type_counts[event_type] = (
            event_type_counts.get(event_type, 0) + 1
        )

    event_chart_data = [
        {"event_type": event_type, "count": count}
        for event_type, count in sorted(
            event_type_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:8]
    ]

    event_lookup = {
        str(event.get("id")): event
        for event in events
        if event.get("id")
    }

    # --------------------------------------------------
    # Delivery statistics
    # --------------------------------------------------

    successful_statuses = {
        "success",
        "succeeded",
        "delivered",
    }

    failed_statuses = {
        "failed",
        "dead",
        "permanently_failed",
    }

    pending_statuses = {
        "pending",
        "retrying",
        "processing",
        "in_progress",
        "paused",
    }

    successful = 0
    failed = 0
    pending = 0
    other_deliveries = 0
    total_delivery_attempts = 0

    for delivery in deliveries:
        status = str(delivery.get("status", "")).lower()

        total_delivery_attempts += safe_int(
            delivery.get("attempt_count")
        )

        if status in successful_statuses or delivery.get("delivered_at"):
            successful += 1

        elif status in failed_statuses:
            failed += 1

        elif status in pending_statuses:
            pending += 1

        else:
            other_deliveries += 1

    total_deliveries = len(deliveries)

    success_rate = (
        round(successful / total_deliveries * 100, 1)
        if total_deliveries else 0
    )

    enriched_deliveries = []

    for delivery in deliveries:
        item = dict(delivery)

        event = event_lookup.get(
            str(delivery.get("event_id"))
        )

        item["event_type"] = (
            event.get("event_type")
            if event else "Event unavailable"
        )

        enriched_deliveries.append(item)

    recent_deliveries = sorted(
        enriched_deliveries,
        key=get_created_at,
        reverse=True,
    )[:8]

    # --------------------------------------------------
    # Delivery attempt analytics
    # --------------------------------------------------

    total_attempts = len(attempts)

    def is_successful_attempt(attempt):
        status_code = safe_int(
            attempt.get("http_status_code"),
            -1,
        )

        return (
            200 <= status_code < 300
            and not attempt.get("error_message")
        )

    successful_attempts = [
        attempt for attempt in attempts
        if is_successful_attempt(attempt)
    ]

    failed_attempts = [
        attempt for attempt in attempts
        if not is_successful_attempt(attempt)
    ]

    successful_attempt_count = len(successful_attempts)
    failed_attempt_count = len(failed_attempts)

    attempt_success_rate = (
        round(successful_attempt_count / total_attempts * 100, 2)
        if total_attempts else 0
    )

    # HTTP status distribution

    http_status_counts = {}

    for attempt in attempts:
        status_code = attempt.get("http_status_code")

        status_label = (
            str(status_code)
            if status_code is not None
            else "No response"
        )

        http_status_counts[status_label] = (
            http_status_counts.get(status_label, 0) + 1
        )

    http_status_chart_data = [
        {"label": status, "count": count}
        for status, count in sorted(
            http_status_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )
    ]

    # Response time statistics

    response_times = [
        safe_int(attempt.get("duration_ms"))
        for attempt in attempts
        if (
            attempt.get("duration_ms") is not None
            and safe_int(attempt.get("duration_ms")) >= 0
        )
    ]

    average_response_time = (
        round(sum(response_times) / len(response_times), 2)
        if response_times else 0
    )

    minimum_response_time = (
        min(response_times) if response_times else 0
    )

    maximum_response_time = (
        max(response_times) if response_times else 0
    )

    # Retry analysis

    attempts_per_delivery = {}

    for attempt in attempts:
        delivery_id = attempt.get("delivery_id")

        if delivery_id:
            attempts_per_delivery[delivery_id] = (
                attempts_per_delivery.get(delivery_id, 0) + 1
            )

    retried_deliveries = sum(
        1 for count in attempts_per_delivery.values()
        if count > 1
    )

    maximum_delivery_attempts = max(
        attempts_per_delivery.values(),
        default=0,
    )

    maximum_retries = max(
        (count - 1 for count in attempts_per_delivery.values()),
        default=0,
    )

    recent_failed_attempts = sorted(
        failed_attempts,
        key=get_attempt_time,
        reverse=True,
    )[:8]

    # --------------------------------------------------
    # Load statistics
    # --------------------------------------------------

    load_statuses = [
        "created",
        "assigned",
        "dispatched",
        "at_pickup",
        "picked_up",
        "in_transit",
        "detention",
        "at_delivery",
        "delivered",
        "cancelled",
    ]

    load_status_counts = {
        status: sum(
            1 for load in loads
            if str(load.get("status", "created")).lower() == status
        )
        for status in load_statuses
    }

    active_loads = sum(
        1 for load in loads
        if str(load.get("status", "")).lower()
        not in ("delivered", "cancelled")
    )

    # --------------------------------------------------
    # Recent activity
    # --------------------------------------------------

    recent_events = sorted(
        events,
        key=get_created_at,
        reverse=True,
    )[:8]

    recent_loads = sorted(
        loads,
        key=get_created_at,
        reverse=True,
    )[:8]

    # --------------------------------------------------
    # Chart data
    # --------------------------------------------------

    delivery_chart_data = [
        {"label": "Successful", "count": successful},
        {"label": "Failed", "count": failed},
        {"label": "Pending / Retrying", "count": pending},
        {"label": "Other", "count": other_deliveries},
    ]

    load_chart_data = [
        {
            "label": status.replace("_", " ").title(),
            "count": count,
        }
        for status, count in load_status_counts.items()
        if count > 0
    ]

    # --------------------------------------------------
    # Dashboard context
    # --------------------------------------------------

    context = {
        "user_role": role,

        # Webhook KPIs
        "total_webhooks": len(webhooks),
        "active_webhooks": len(active_webhooks),
        "inactive_webhooks": len(inactive_webhooks),
        "open_circuits": len(open_circuits),
        "half_open_circuits": len(half_open_circuits),

        # Event KPIs
        "total_events": len(events),
        "event_type_counts": event_chart_data,
        "recent_events": recent_events,

        # Delivery KPIs
        "total_deliveries": total_deliveries,
        "successful": successful,
        "failed": failed,
        "pending": pending,
        "other_deliveries": other_deliveries,
        "total_attempts": total_delivery_attempts,
        "success_rate": success_rate,
        "recent_deliveries": recent_deliveries,
        "delivery_chart_data": delivery_chart_data,

        # Delivery reliability
        "total_attempt_records": total_attempts,
        "successful_attempts": successful_attempt_count,
        "failed_attempts": failed_attempt_count,
        "attempt_success_rate": attempt_success_rate,
        "http_status_chart_data": http_status_chart_data,
        "http_status_counts": http_status_counts,
        "average_response_time": average_response_time,
        "minimum_response_time": minimum_response_time,
        "maximum_response_time": maximum_response_time,
        "retried_deliveries": retried_deliveries,
        "maximum_retries": maximum_retries,
        "maximum_delivery_attempts": maximum_delivery_attempts,
        "recent_failed_attempts": recent_failed_attempts,

        # Trucking KPIs
        "total_loads": len(loads),
        "active_loads": active_loads,
        "total_carriers": len(carriers),
        "total_drivers": len(drivers),
        "load_status_counts": load_status_counts,
        "load_chart_data": load_chart_data,
        "recent_loads": recent_loads,

        # Circuit breaker
        "circuit_breaker_webhooks": open_circuits,
    }

    return render(
        request,
        "dashboard/index.html",
        context,
    )
