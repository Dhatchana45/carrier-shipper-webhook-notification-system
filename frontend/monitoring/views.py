
import time

from django.shortcuts import render

from core.api import api_request
from core.decorators import login_required, role_required


# --------------------------------------------------
# Prometheus Metrics Parser
# --------------------------------------------------

def parse_prometheus_metrics(metrics_text):
    """Parse Prometheus text format into metric name/value pairs."""
    metrics = {}

    if not isinstance(metrics_text, str):
        return metrics

    for line in metrics_text.splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        try:
            metric_part, value_part = line.rsplit(None, 1)
            value = float(value_part)

            # Remove labels to group values by metric name.
            metric_name = metric_part.split("{", 1)[0]
            metrics.setdefault(metric_name, []).append(value)

        except (ValueError, IndexError):
            continue

    return metrics


# --------------------------------------------------
# Authenticated FastAPI Request With Timing
# --------------------------------------------------

def api_get(request, endpoint):
    """Fetch data from FastAPI and measure response time."""
    start = time.perf_counter()

    data, error = api_request(
        request,
        "GET",
        endpoint,
    )

    response_time = round(
        (time.perf_counter() - start) * 1000,
        2
    )

    if error:
        return None, response_time, error

    return data, response_time, None


# --------------------------------------------------
# Monitoring Dashboard
# --------------------------------------------------

@login_required
@role_required("admin", "carrier", "shipper")
def monitoring_dashboard(request):

    # FastAPI health
    health_data, health_time, health_error = api_get(
        request,
        "/health"
    )

    # Database health
    database_data, database_time, database_error = api_get(
        request,
        "/health/database"
    )

    # Prometheus metrics
    metrics_data, metrics_time, metrics_error = api_get(
        request,
        "/metrics"
    )

    def get_status(data, error):
        if error or data is None:
            return "Unavailable"

        if isinstance(data, dict):
            status = str(data.get("status", "")).lower()

            if status in ["healthy", "ok", "connected", "up"]:
                return "Healthy"

            if status in ["unhealthy", "error", "down", "disconnected"]:
                return "Unhealthy"

        return "Available"

    metrics = parse_prometheus_metrics(metrics_data)

    metric_summary = []

    for name, values in metrics.items():
        metric_summary.append({
            "name": name,
            "value": round(sum(values), 3),
            "samples": len(values),
        })

    context = {
        "active_page": "monitoring",

        # API health
        "health_data": health_data,
        "health_status": get_status(
            health_data,
            health_error
        ),
        "health_time": health_time,
        "health_error": health_error,

        # Database health
        "database_data": database_data,
        "database_status": get_status(
            database_data,
            database_error
        ),
        "database_time": database_time,
        "database_error": database_error,

        # Prometheus metrics
        "metrics_status": (
            "Available"
            if not metrics_error and metrics_data is not None
            else "Unavailable"
        ),
        "metrics_time": metrics_time,
        "metrics_error": metrics_error,
        "metric_summary": metric_summary,
        "metric_count": len(metrics),

        # Monitoring URLs
        "grafana_url": "http://localhost:3001",
        "prometheus_url": "http://localhost:9090",
    }

    return render(
        request,
        "monitoring/index.html",
        context
    )
