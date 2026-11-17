import hashlib
import hmac
import json
import os
import time
import logging
import redis

from fastapi import FastAPI, Header, HTTPException, Request

logger = logging.getLogger("webhook.receiver")

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Webhook Signature Verification Receiver",
    version="2.1.0",
)

WEBHOOK_SECRET = os.getenv("WEBHOOK_TEST_SECRET")

if not WEBHOOK_SECRET:
    raise RuntimeError(
        "WEBHOOK_TEST_SECRET environment variable is not configured."
    )

REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://127.0.0.1:6379/0",
)

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)

TIMESTAMP_TOLERANCE_SECONDS = 300
REPLAY_TTL_SECONDS = 86400


@app.get("/health")
def health():
    return {"status": "receiver_ready"}


@app.post("/receiver")
async def receive_webhook(
    request: Request,
    signature: str | None = Header(
        default=None,
        alias="X-Webhook-Signature",
    ),
    timestamp: str | None = Header(
        default=None,
        alias="X-Webhook-Timestamp",
    ),
    event_type: str | None = Header(
        default=None,
        alias="X-Webhook-Event",
    ),
    delivery_id: str | None = Header(
        default=None,
        alias="X-Webhook-Delivery",
    ),
):
    raw_body = await request.body()

    # 1. Require authentication headers.
    if not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing webhook signature",
        )

    if not timestamp:
        raise HTTPException(
            status_code=401,
            detail="Missing webhook timestamp",
        )

    if not delivery_id:
        raise HTTPException(
            status_code=400,
            detail="Missing delivery ID",
        )

    # 2. Validate timestamp format and clock skew.
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook timestamp",
        )

    current_timestamp = int(time.time())

    if abs(current_timestamp - timestamp_value) > TIMESTAMP_TOLERANCE_SECONDS:
        raise HTTPException(
            status_code=401,
            detail="Webhook timestamp expired",
        )

    # 3. Verify HMAC over timestamp + "." + raw body.
    signed_payload = timestamp.encode("utf-8") + b"." + raw_body

    expected_digest = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    expected_signature = f"sha256={expected_digest}"

    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        )

    # 4. Validate JSON before processing.
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload",
        )

    # 5. Controlled HTTP 500 for retry testing.
    # Only explicitly marked test events are affected.
    if (
        payload.get("retry_test") is True
        and os.getenv(
            "RECEIVER_FORCE_HTTP_500",
            "false",
        ).lower() == "true"
    ):
        logger.warning(
            "retry_test_forced_http_500",
            extra={
                "event_type": event_type,
                "delivery_id": delivery_id,
            },
        )

        raise HTTPException(
            status_code=500,
            detail="Temporary HTTP 500 for retry testing",
        )

    # 6. Atomically record delivery ID in Redis.
    # Failed retry-test requests are not recorded.
    replay_key = f"webhook:receiver:processed:{delivery_id}"

    try:
        is_new_delivery = redis_client.set(
            replay_key,
            "1",
            nx=True,
            ex=REPLAY_TTL_SECONDS,
        )
    except redis.RedisError:
        raise HTTPException(
            status_code=503,
            detail="Replay protection service unavailable",
        )

    # 7. Ignore duplicate deliveries.
    if not is_new_delivery:
        return {
            "status": "duplicate_ignored",
            "delivery_id": delivery_id,
        }

    # 8. Log successful signature verification.
    logger.info(
        "webhook_signature_verified",
        extra={
            "event_type": event_type,
            "delivery_id": delivery_id,
        },
    )

    # 9. Return successful response.
    return {
        "status": "signature_verified",
        "event_type": event_type,
        "delivery_id": delivery_id,
        "payload": payload,
    }