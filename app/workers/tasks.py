
import hashlib
import hmac
import json
import logging
import random
import time

from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx

from sqlalchemy import select

from app.security.webhook_url import (
    validate_webhook_url,
    WebhookURLValidationError,
)
from app.security.webhook_secrets import decrypt_webhook_secret

from app.database import SessionLocal
from app.models import Delivery, DeliveryAttempt, Webhook
from app.observability.logging_config import configure_logging
from app.workers.celery_app import celery_app


configure_logging()

logger = logging.getLogger(__name__)

CIRCUIT_FAILURE_THRESHOLD = 5
CIRCUIT_COOLDOWN_SECONDS = 60


@celery_app.task(name="app.workers.tasks.deliver_webhook")
def deliver_webhook(delivery_id: str, claim_token: str):

    logger.info(
        "delivery_task_started",
        extra={"delivery_id": delivery_id},
    )

    db = SessionLocal()

    try:
        delivery_uuid = UUID(delivery_id)
        token_uuid = UUID(claim_token)

        # 1. Fetch and lock the delivery.
        delivery = db.scalar(
            select(Delivery)
            .where(Delivery.id == delivery_uuid)
            .with_for_update()
        )

        if delivery is None:
            logger.warning(
                "delivery_not_found",
                extra={"delivery_id": delivery_id},
            )
            return {
                "status": "not_found",
                "delivery_id": delivery_id,
            }

        # 2. Validate claim ownership.
        if (
            delivery.status != "processing"
            or delivery.claim_token != token_uuid
        ):
            logger.warning(
                "delivery_claim_rejected",
                extra={"delivery_id": delivery_id},
            )
            return {
                "status": "claim_rejected",
                "delivery_id": delivery_id,
                "message": "Delivery is no longer owned by this task.",
            }

        webhook = delivery.webhook
        event = delivery.event

        # 3. Check whether webhook is active.
        if not webhook.is_active:
            delivery.status = "paused"
            delivery.next_attempt_at = None
            delivery.processing_started_at = None
            delivery.claim_token = None

            db.commit()

            logger.warning(
                "delivery_paused",
                extra={
                    "delivery_id": delivery_id,
                    "webhook_id": str(webhook.id),
                    "reason": "webhook_inactive",
                },
            )

            return {
                "status": "paused",
                "reason": "Webhook is inactive",
            }

        # Capture request data before committing.
        target_url = webhook.target_url
        webhook_secret = decrypt_webhook_secret(webhook.secret)
        event_type = event.event_type
        event_payload = event.payload
        webhook_id = webhook.id

        # Remember whether this is a half-open test request.
        was_half_open = webhook.circuit_state == "half_open"

        if not webhook_secret:
            raise ValueError(
                "Webhook secret is missing. Cannot generate signature."
            )

        # 4. Record a new delivery attempt.
        started_at = datetime.now(timezone.utc)

        delivery.attempt_count += 1
        attempt_number = delivery.attempt_count

        attempt = DeliveryAttempt(
            delivery_id=delivery.id,
            attempt_number=attempt_number,
            started_at=started_at,
        )

        db.add(attempt)
        db.commit()

        # 5. Prepare payload and timestamp-based HMAC signature.
        payload_bytes = json.dumps(
            event_payload,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        # Generate a fresh timestamp for every delivery attempt.
        timestamp = str(int(time.time()))

        signed_payload = (
            timestamp.encode("utf-8")
            + b"."
            + payload_bytes
        )

        signature = hmac.new(
            webhook_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Event": event_type,
            "X-Webhook-Delivery": delivery_id,
        }

        # 6. Validate destination and send webhook request.
        response = None
        error_message = None
        status_code = None
        response_body = None
        retryable = False

        request_started = time.perf_counter()

        try:
            # Revalidate URL immediately before sending.
            validate_webhook_url(target_url)

            response = httpx.post(
                target_url,
                content=payload_bytes,
                headers=headers,
                timeout=15.0,
                follow_redirects=False,
            )

            status_code = response.status_code
            response_body = response.text[:10000]

            if 200 <= status_code < 300:
                retryable = False

            elif status_code == 429 or status_code >= 500:
                retryable = True
                error_message = (
                    f"HTTP {status_code}: {response_body[:1000]}"
                )

            else:
                retryable = False
                error_message = (
                    f"HTTP {status_code}: {response_body[:1000]}"
                )

        except WebhookURLValidationError as exc:
            # Unsafe destinations are permanent failures.
            retryable = False
            error_message = f"Webhook URL blocked: {exc}"

        except httpx.RequestError as exc:
            retryable = True
            error_message = str(exc)[:2000]

        # Record request completion time and duration.
        completed_at = datetime.now(timezone.utc)
        duration_ms = int(
            (time.perf_counter() - request_started) * 1000
        )

        # 7. Update attempt history.
        attempt.completed_at = completed_at
        attempt.http_status_code = status_code
        attempt.response_body = response_body
        attempt.error_message = error_message
        attempt.duration_ms = duration_ms

        # 8. Re-fetch and validate delivery ownership.
        current_delivery = db.scalar(
            select(Delivery)
            .where(Delivery.id == delivery_uuid)
            .with_for_update()
        )

        if (
            current_delivery is None
            or current_delivery.status != "processing"
            or current_delivery.claim_token != token_uuid
        ):
            db.commit()

            logger.warning(
                "delivery_claim_expired_during_request",
                extra={
                    "delivery_id": delivery_id,
                    "attempt_number": attempt_number,
                    "http_status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )

            return {
                "status": "claim_rejected",
                "delivery_id": delivery_id,
                "message": "Claim expired while the request was running.",
            }

        delivery = current_delivery

        # Lock webhook before changing circuit-breaker state.
        webhook = db.scalar(
            select(Webhook)
            .where(Webhook.id == webhook_id)
            .with_for_update()
        )

        if webhook is None:
            db.commit()

            logger.warning(
                "delivery_webhook_not_found",
                extra={"delivery_id": delivery_id},
            )

            return {
                "status": "webhook_not_found",
                "delivery_id": delivery_id,
            }

        delivery.last_status_code = status_code
        delivery.last_error = error_message

        # 9. Successful delivery: close the circuit.
        if response is not None and 200 <= status_code < 300:

            delivery.status = "succeeded"
            delivery.delivered_at = completed_at
            delivery.next_attempt_at = None
            delivery.processing_started_at = None
            delivery.claim_token = None

            webhook.circuit_state = "closed"
            webhook.consecutive_failures = 0
            webhook.circuit_opened_at = None

            logger.info(
                "delivery_succeeded",
                extra={
                    "delivery_id": delivery_id,
                    "webhook_id": str(webhook.id),
                    "event_type": event_type,
                    "attempt_number": attempt_number,
                    "http_status_code": status_code,
                    "duration_ms": duration_ms,
                    "circuit_state": "closed",
                },
            )

            db.commit()

            return {
                "status": "succeeded",
                "delivery_id": delivery_id,
                "http_status_code": status_code,
                "attempt_number": attempt_number,
                "circuit_state": "closed",
            }

        # 10. Update consecutive failure count.
        if retryable:
            webhook.consecutive_failures += 1

        # 11. Decide whether to open or reopen the circuit.
        circuit_opened = False

        if was_half_open:
            # A failed half-open test reopens the circuit.
            webhook.circuit_state = "open"
            webhook.circuit_opened_at = completed_at

            webhook.consecutive_failures = max(
                webhook.consecutive_failures,
                CIRCUIT_FAILURE_THRESHOLD,
            )

            circuit_opened = True

        elif (
            retryable
            and webhook.consecutive_failures
            >= CIRCUIT_FAILURE_THRESHOLD
        ):
            webhook.circuit_state = "open"
            webhook.circuit_opened_at = completed_at

            circuit_opened = True

        # 12. Permanent failure or maximum attempts reached.
        if not retryable or attempt_number >= delivery.max_attempts:

            delivery.status = "failed"
            delivery.next_attempt_at = None
            delivery.processing_started_at = None
            delivery.claim_token = None

            logger.error(
                "delivery_failed",
                extra={
                    "delivery_id": delivery_id,
                    "webhook_id": str(webhook.id),
                    "event_type": event_type,
                    "attempt_number": attempt_number,
                    "http_status_code": status_code,
                    "duration_ms": duration_ms,
                    "error": error_message,
                    "circuit_state": webhook.circuit_state,
                },
            )

            db.commit()

            return {
                "status": "failed",
                "delivery_id": delivery_id,
                "http_status_code": status_code,
                "error": error_message,
                "attempt_number": attempt_number,
                "circuit_state": webhook.circuit_state,
            }

        # 13. Schedule the next retry.
        if circuit_opened:
            retry_delay = CIRCUIT_COOLDOWN_SECONDS

        else:
            base_delay = min(
                2 ** (attempt_number - 1),
                300,
            )

            jitter = random.uniform(0, 1)
            retry_delay = base_delay + jitter

        delivery.status = "retrying"
        delivery.next_attempt_at = (
            completed_at + timedelta(seconds=retry_delay)
        )
        delivery.processing_started_at = None
        delivery.claim_token = None

        logger.warning(
            "delivery_retry_scheduled",
            extra={
                "delivery_id": delivery_id,
                "webhook_id": str(webhook.id),
                "event_type": event_type,
                "attempt_number": attempt_number,
                "http_status_code": status_code,
                "duration_ms": duration_ms,
                "retry_in_seconds": round(retry_delay, 2),
                "circuit_state": webhook.circuit_state,
                "consecutive_failures": webhook.consecutive_failures,
            },
        )

        db.commit()

        return {
            "status": "retrying",
            "delivery_id": delivery_id,
            "attempt_number": attempt_number,
            "retry_in_seconds": round(retry_delay, 2),
            "next_attempt_at": delivery.next_attempt_at.isoformat(),
            "circuit_state": webhook.circuit_state,
            "consecutive_failures": webhook.consecutive_failures,
        }

    except Exception:
        db.rollback()

        logger.exception(
            "delivery_task_exception",
            extra={"delivery_id": delivery_id},
        )

        raise

    finally:
        db.close()
