
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from prometheus_client.core import (
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
)

from app.models import Delivery, DeliveryAttempt, Webhook


class DatabaseMetricsCollector:
    """
    Collects persistent application metrics directly from PostgreSQL.

    This allows Prometheus to observe delivery activity performed by
    both the FastAPI process and separate Celery worker processes.
    """

    LATENCY_BUCKETS = [
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
        15.0,
        30.0,
        60.0,
    ]

    def __init__(self, db: Session):
        self.db = db

    def collect(self):

        # --------------------------------------------------
        # 1. Current delivery counts by status
        # --------------------------------------------------

        delivery_metric = GaugeMetricFamily(
            "webhook_deliveries_current",
            "Current number of deliveries grouped by status.",
            labels=["status"],
        )

        delivery_counts = self.db.execute(
            select(
                Delivery.status,
                func.count(Delivery.id),
            ).group_by(Delivery.status)
        ).all()

        delivery_statuses = {
            status: count for status, count in delivery_counts
        }

        for status in [
            "pending",
            "processing",
            "retrying",
            "succeeded",
            "failed",
            "paused",
        ]:
            delivery_metric.add_metric(
                [status],
                delivery_statuses.get(status, 0),
            )

        yield delivery_metric

        # --------------------------------------------------
        # 2. Delivery attempts grouped by result
        # --------------------------------------------------

        result_expression = case(
            (
                DeliveryAttempt.http_status_code.between(200, 299),
                "success",
            ),
            (
                DeliveryAttempt.http_status_code.between(400, 499),
                "http_4xx",
            ),
            (
                DeliveryAttempt.http_status_code.between(500, 599),
                "http_5xx",
            ),
            (
                DeliveryAttempt.http_status_code.is_(None)
                & DeliveryAttempt.error_message.is_not(None),
                "network_error",
            ),
            else_="other",
        )

        attempt_counts = self.db.execute(
            select(
                result_expression.label("result"),
                func.count(DeliveryAttempt.id),
            ).group_by(result_expression)
        ).all()

        attempt_metric = CounterMetricFamily(
            "webhook_delivery_attempts",
            "Total recorded webhook delivery attempts by result.",
            labels=["result"],
        )

        attempt_results = {
            result: count for result, count in attempt_counts
        }

        for result in [
            "success",
            "http_4xx",
            "http_5xx",
            "network_error",
            "other",
        ]:
            attempt_metric.add_metric(
                [result],
                attempt_results.get(result, 0),
            )

        yield attempt_metric

        # --------------------------------------------------
        # 3. Retry attempts
        # --------------------------------------------------

        retry_count = self.db.scalar(
            select(func.count(DeliveryAttempt.id)).where(
                DeliveryAttempt.attempt_number > 1
            )
        ) or 0

        retry_metric = CounterMetricFamily(
            "webhook_delivery_retries",
            "Total delivery attempts that were retries.",
        )

        retry_metric.add_metric([], retry_count)

        yield retry_metric

        # --------------------------------------------------
        # 4. Circuit breaker states
        # --------------------------------------------------

        circuit_metric = GaugeMetricFamily(
            "webhook_circuit_breakers",
            "Number of webhooks grouped by circuit breaker state.",
            labels=["state"],
        )

        circuit_counts = self.db.execute(
            select(
                Webhook.circuit_state,
                func.count(Webhook.id),
            ).group_by(Webhook.circuit_state)
        ).all()

        circuit_states = {
            state: count for state, count in circuit_counts
        }

        for state in ["closed", "open", "half_open"]:
            circuit_metric.add_metric(
                [state],
                circuit_states.get(state, 0),
            )

        yield circuit_metric

        # --------------------------------------------------
        # 5. Delivery latency histogram
        # --------------------------------------------------

        bucket_expressions = [
            func.coalesce(
                func.sum(
                    case(
                        (
                            DeliveryAttempt.duration_ms <= boundary * 1000,
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
            for boundary in self.LATENCY_BUCKETS
        ]

        latency_query = select(
            func.count(DeliveryAttempt.id),
            func.coalesce(func.sum(DeliveryAttempt.duration_ms), 0),
            *bucket_expressions,
        ).where(
            DeliveryAttempt.duration_ms.is_not(None)
        )

        latency_result = self.db.execute(
            latency_query
        ).one()

        total_count = latency_result[0]
        total_duration_ms = latency_result[1]
        bucket_counts = latency_result[2:]

        latency_metric = HistogramMetricFamily(
            "webhook_delivery_duration_seconds",
            "Webhook HTTP delivery duration in seconds.",
        )

        cumulative_buckets = [
            (str(boundary), count)
            for boundary, count in zip(
                self.LATENCY_BUCKETS,
                bucket_counts,
            )
        ]

        cumulative_buckets.append(
            ("+Inf", total_count)
        )

        latency_metric.add_metric(
            [],
            cumulative_buckets,
            sum_value=total_duration_ms / 1000,
        )

        yield latency_metric
