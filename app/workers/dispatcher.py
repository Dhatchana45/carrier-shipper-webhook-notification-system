
import logging
import uuid

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from app.database import SessionLocal
from app.models import Delivery, DeliveryAttempt, Event, Webhook
from app.observability.logging_config import configure_logging
from app.workers.celery_app import celery_app


configure_logging()
logger = logging.getLogger(__name__)

STALE_PROCESSING_MINUTES = 2

CIRCUIT_COOLDOWN_SECONDS = 60
HALF_OPEN_RECHECK_SECONDS = 30


@celery_app.task(name="app.workers.dispatcher.dispatch_pending_deliveries")
def dispatch_pending_deliveries():
    db = SessionLocal()

    try:
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(minutes=STALE_PROCESSING_MINUTES)

        logger.info(
            "dispatcher_started",
            extra={"event": "dispatcher_started"},
        )

        # 1. Find stale processing deliveries.
        stale_statement = (
            select(Delivery)
            .where(
                Delivery.status == "processing",
                Delivery.processing_started_at.is_not(None),
                Delivery.processing_started_at < stale_before,
            )
            .order_by(Delivery.processing_started_at.asc())
            .limit(100)
            .with_for_update(skip_locked=True)
        )

        stale_deliveries = db.scalars(stale_statement).all()
        recovered_count = 0

        # 2. Recover stale deliveries and invalidate old tokens.
        for delivery in stale_deliveries:
            previous_status = delivery.status

            # Close the unfinished attempt left by the interrupted worker.
            interrupted_attempt = db.scalar(
                select(DeliveryAttempt)
                .where(
                    DeliveryAttempt.delivery_id == delivery.id,
                    DeliveryAttempt.completed_at.is_(None),
                )
                .order_by(DeliveryAttempt.attempt_number.desc())
                .limit(1)
                .with_for_update()
            )

            if interrupted_attempt is not None:
                started_at = interrupted_attempt.started_at

                # SQLite may return naive datetimes in tests.
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)

                interrupted_attempt.completed_at = now
                interrupted_attempt.error_message = (
                    "Worker processing timed out; "
                    "delivery recovered by dispatcher."
                )
                interrupted_attempt.duration_ms = max(
                    0,
                    int((now - started_at).total_seconds() * 1000),
                )

            delivery.claim_token = None
            delivery.processing_started_at = None

            if delivery.attempt_count >= delivery.max_attempts:
                delivery.status = "failed"
                delivery.last_error = (
                    "Processing timed out after maximum attempts."
                )
                delivery.next_attempt_at = None

            elif delivery.attempt_count == 0:
                delivery.status = "pending"
                delivery.next_attempt_at = None

            else:
                delivery.status = "retrying"
                delivery.next_attempt_at = now

            recovered_count += 1

            logger.warning(
                "stale_delivery_recovered",
                extra={
                    "event": "stale_delivery_recovered",
                    "delivery_id": str(delivery.id),
                    "previous_status": previous_status,
                    "new_status": delivery.status,
                    "attempt_count": delivery.attempt_count,
                    "max_attempts": delivery.max_attempts,
                },
            )

        # 3. Find pending and due retry deliveries.
        statement = (
            select(Delivery)
            .where(
                or_(
                    Delivery.status == "pending",
                    and_(
                        Delivery.status == "retrying",
                        Delivery.next_attempt_at <= now,
                    ),
                )
            )
            .order_by(Delivery.created_at.asc())
            .limit(100)
            .with_for_update(skip_locked=True)
        )

        deliveries = db.scalars(statement).all()

        if not deliveries:
            db.commit()

            logger.info(
                "dispatcher_no_deliveries",
                extra={
                    "event": "dispatcher_no_deliveries",
                    "recovered_count": recovered_count,
                },
            )

            return {
                "dispatched_count": 0,
                "recovered_count": recovered_count,
                "message": "No pending or due retry deliveries.",
            }

        # 4. Prepare claim information.
        previous_states = {}
        claim_tokens = {}

        dispatched_candidates = []
        locked_webhooks = {}
        half_open_claimed = set()

        # 5. Check circuit breaker before claiming each delivery.
        for delivery in deliveries:
            webhook_id = delivery.webhook_id

            # Lock each webhook row once per dispatcher transaction.
            webhook = locked_webhooks.get(webhook_id)

            if webhook is None:
                webhook = db.scalar(
                    select(Webhook)
                    .where(Webhook.id == webhook_id)
                    .with_for_update()
                )

                if webhook is None:
                    logger.warning(
                        "delivery_webhook_not_found",
                        extra={
                            "event": "delivery_webhook_not_found",
                            "delivery_id": str(delivery.id),
                            "webhook_id": str(webhook_id),
                        },
                    )
                    continue

                locked_webhooks[webhook_id] = webhook

            # Inactive webhook.
            if not webhook.is_active:
                delivery.status = "paused"
                delivery.next_attempt_at = None
                delivery.processing_started_at = None
                delivery.claim_token = None

                logger.info(
                    "delivery_paused_inactive_webhook",
                    extra={
                        "event": "delivery_paused_inactive_webhook",
                        "delivery_id": str(delivery.id),
                        "webhook_id": str(webhook_id),
                    },
                )
                continue

            circuit_state = webhook.circuit_state

            # 6. OPEN circuit: wait for cooldown.
            if circuit_state == "open":
                if webhook.circuit_opened_at is None:
                    webhook.circuit_opened_at = now

                reopen_at = webhook.circuit_opened_at + timedelta(
                    seconds=CIRCUIT_COOLDOWN_SECONDS
                )

                if now < reopen_at:
                    delivery.status = "retrying"
                    delivery.next_attempt_at = reopen_at

                    logger.info(
                        "delivery_deferred_circuit_open",
                        extra={
                            "event": "delivery_deferred_circuit_open",
                            "delivery_id": str(delivery.id),
                            "webhook_id": str(webhook_id),
                            "retry_at": reopen_at.isoformat(),
                        },
                    )
                    continue

                # Cooldown finished. Move to HALF-OPEN.
                webhook.circuit_state = "half_open"
                circuit_state = "half_open"

                logger.info(
                    "circuit_breaker_half_open",
                    extra={
                        "event": "circuit_breaker_half_open",
                        "webhook_id": str(webhook_id),
                    },
                )

            # 7. HALF-OPEN circuit: allow only one test delivery.
            if circuit_state == "half_open":
                if webhook_id in half_open_claimed:
                    delivery.status = "retrying"
                    delivery.next_attempt_at = now + timedelta(
                        seconds=HALF_OPEN_RECHECK_SECONDS
                    )

                    logger.info(
                        "delivery_deferred_half_open_test_claimed",
                        extra={
                            "event": "delivery_deferred_half_open_test_claimed",
                            "delivery_id": str(delivery.id),
                            "webhook_id": str(webhook_id),
                            "retry_at": delivery.next_attempt_at.isoformat(),
                        },
                    )
                    continue

                # Check whether another half-open test is already running.
                active_test = db.scalar(
                    select(Delivery.id)
                    .where(
                        Delivery.webhook_id == webhook_id,
                        Delivery.status == "processing",
                        Delivery.claim_token.is_not(None),
                    )
                    .limit(1)
                )

                if active_test is not None:
                    delivery.status = "retrying"
                    delivery.next_attempt_at = now + timedelta(
                        seconds=HALF_OPEN_RECHECK_SECONDS
                    )

                    logger.info(
                        "delivery_deferred_half_open_test_running",
                        extra={
                            "event": "delivery_deferred_half_open_test_running",
                            "delivery_id": str(delivery.id),
                            "webhook_id": str(webhook_id),
                            "active_test_delivery_id": str(active_test),
                            "retry_at": delivery.next_attempt_at.isoformat(),
                        },
                    )
                    continue

                # Reserve this webhook's single half-open test.
                half_open_claimed.add(webhook_id)

            # 8. Save the previous delivery state.
            previous_states[delivery.id] = {
                "status": delivery.status,
                "next_attempt_at": delivery.next_attempt_at,
                "processing_started_at": delivery.processing_started_at,
                "claim_token": delivery.claim_token,
            }

            # 9. Generate a unique claim token.
            token = uuid.uuid4()

            delivery.status = "processing"
            delivery.processing_started_at = now
            delivery.claim_token = token

            claim_tokens[delivery.id] = token
            dispatched_candidates.append(delivery)

        # Commit delivery claims and circuit state changes.
        db.commit()

        logger.info(
            "delivery_claims_committed",
            extra={
                "event": "delivery_claims_committed",
                "candidate_count": len(dispatched_candidates),
                "recovered_count": recovered_count,
            },
        )

        dispatched_ids = []
        affected_event_ids = set()

        # 10. Dispatch claimed deliveries to Celery.
        for delivery in dispatched_candidates:
            token = claim_tokens[delivery.id]

            try:
                celery_app.send_task(
                    "app.workers.tasks.deliver_webhook",
                    args=[
                        str(delivery.id),
                        str(token),
                    ],
                )

                dispatched_ids.append(str(delivery.id))
                affected_event_ids.add(delivery.event_id)

                logger.info(
                    "delivery_task_enqueued",
                    extra={
                        "event": "delivery_task_enqueued",
                        "delivery_id": str(delivery.id),
                        "event_id": str(delivery.event_id),
                        "webhook_id": str(delivery.webhook_id),
                    },
                )

            except Exception:
                logger.exception(
                    "delivery_task_enqueue_failed",
                    extra={
                        "event": "delivery_task_enqueue_failed",
                        "delivery_id": str(delivery.id),
                        "event_id": str(delivery.event_id),
                        "webhook_id": str(delivery.webhook_id),
                    },
                )

                db.rollback()

                failed_delivery = db.get(Delivery, delivery.id)

                # Restore only if this claim is still current.
                if (
                    failed_delivery
                    and failed_delivery.claim_token == token
                    and failed_delivery.status == "processing"
                ):
                    previous = previous_states[delivery.id]

                    failed_delivery.status = previous["status"]
                    failed_delivery.next_attempt_at = previous[
                        "next_attempt_at"
                    ]
                    failed_delivery.processing_started_at = previous[
                        "processing_started_at"
                    ]
                    failed_delivery.claim_token = previous["claim_token"]

                    db.commit()

                    logger.warning(
                        "delivery_claim_restored_after_enqueue_failure",
                        extra={
                            "event": "delivery_claim_restored_after_enqueue_failure",
                            "delivery_id": str(delivery.id),
                            "restored_status": previous["status"],
                        },
                    )

        # 11. Mark dispatched events as published.
        for event_id in affected_event_ids:
            event = db.get(Event, event_id)

            if event:
                event.outbox_status = "published"
                event.published_at = datetime.now(timezone.utc)

        db.commit()

        logger.info(
            "dispatcher_completed",
            extra={
                "event": "dispatcher_completed",
                "dispatched_count": len(dispatched_ids),
                "recovered_count": recovered_count,
            },
        )

        return {
            "dispatched_count": len(dispatched_ids),
            "recovered_count": recovered_count,
            "delivery_ids": dispatched_ids,
        }

    except Exception:
        db.rollback()

        logger.exception(
            "dispatcher_failed",
            extra={"event": "dispatcher_failed"},
        )
        raise

    finally:
        db.close()
