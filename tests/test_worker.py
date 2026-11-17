import hashlib
import hmac
import time
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Delivery, DeliveryAttempt, Event, Webhook
from app.workers import tasks as worker_tasks


@pytest.fixture
def worker_delivery(test_engine, monkeypatch):
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    # The worker uses this SessionLocal directly.
    monkeypatch.setattr(
        worker_tasks,
        "SessionLocal",
        TestingSessionLocal,
    )

    db = TestingSessionLocal()

    webhook = Webhook(
        name="Worker Test Webhook",
        target_url="https://example.com/webhook",
        secret="worker-test-secret",
        subscribed_event_types=["shipment.created"],
        is_active=True,
        circuit_state="closed",
        consecutive_failures=0,
    )

    event = Event(
        event_type="shipment.created",
        idempotency_key=f"WORKER-{uuid4()}",
        payload={
            "shipment_id": "SHIPMENT-WORKER-1001",
            "status": "created",
            "origin": "Coimbatore",
            "destination": "Chennai",
        },
    )

    db.add_all([webhook, event])
    db.flush()

    claim_token = uuid4()

    delivery = Delivery(
        event_id=event.id,
        webhook_id=webhook.id,
        status="processing",
        attempt_count=0,
        max_attempts=8,
        claim_token=claim_token,
        processing_started_at=datetime.now(timezone.utc),
    )

    db.add(delivery)
    db.commit()

    result = {
        "delivery_id": str(delivery.id),
        "webhook_id": str(webhook.id),
        "event_id": str(event.id),
        "claim_token": str(claim_token),
    }

    db.close()

    yield result

    # The test database is cleaned by the test_engine fixture.


def mock_http_response(status_code=200, text="OK"):
    return SimpleNamespace(
        status_code=status_code,
        text=text,
    )


def test_worker_successful_delivery(worker_delivery, monkeypatch):
    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(200, "Delivered"),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "succeeded"
    assert result["http_status_code"] == 200
    assert result["attempt_number"] == 1
    assert result["circuit_state"] == "closed"

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "succeeded"
        assert delivery.attempt_count == 1
        assert delivery.claim_token is None
        assert delivery.delivered_at is not None

        attempts = db.scalars(
            select(DeliveryAttempt).where(
                DeliveryAttempt.delivery_id == delivery.id
            )
        ).all()

        assert len(attempts) == 1
        assert attempts[0].http_status_code == 200
        assert attempts[0].completed_at is not None

    finally:
        db.close()


def test_worker_http_500_schedules_retry(worker_delivery, monkeypatch):
    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(500, "Server Error"),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "retrying"
    assert result["attempt_number"] == 1
    assert result["circuit_state"] == "closed"

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "retrying"
        assert delivery.attempt_count == 1
        assert delivery.next_attempt_at is not None
        assert delivery.last_status_code == 500

    finally:
        db.close()


def test_worker_maximum_attempts_marks_failed(
    worker_delivery,
    monkeypatch,
):
    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )
        delivery.attempt_count = 7
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(500, "Server Error"),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "failed"
    assert result["attempt_number"] == 8

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "failed"
        assert delivery.attempt_count == 8
        assert delivery.next_attempt_at is None
        assert delivery.claim_token is None

    finally:
        db.close()


def test_worker_generates_valid_hmac_signature(
    worker_delivery,
    monkeypatch,
):
    captured_request = {}

    def fake_post(url, **kwargs):
        captured_request["url"] = url
        captured_request.update(kwargs)
        return mock_http_response(200, "OK")

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        fake_post,
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "succeeded"

    db = worker_tasks.SessionLocal()

    try:
        event = db.get(
            Event,
            UUID(worker_delivery["event_id"]),
        )

        expected_payload = json.dumps(
            event.payload,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    finally:
        db.close()

    # Read the timestamp generated by the worker.
    timestamp = captured_request["headers"]["X-Webhook-Timestamp"]

    # The timestamp must be a valid Unix timestamp.
    assert timestamp.isdigit()
    assert abs(int(time.time()) - int(timestamp)) <= 5

    # Verify the signature over timestamp + "." + request body.
    signed_payload = (
        timestamp.encode("utf-8")
        + b"."
        + expected_payload
    )

    expected_signature = hmac.new(
        b"worker-test-secret",
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    assert captured_request["content"] == expected_payload

    assert (
        captured_request["headers"]["X-Webhook-Signature"]
        == f"sha256={expected_signature}"
    )

    assert (
        captured_request["headers"]["X-Webhook-Event"]
        == "shipment.created"
    )

    assert (
        captured_request["headers"]["X-Webhook-Delivery"]
        == worker_delivery["delivery_id"]
    )



def test_worker_opens_circuit_after_failure_threshold(
    worker_delivery,
    monkeypatch,
):
    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )
        webhook.consecutive_failures = 4
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(500, "Server Error"),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "retrying"
    assert result["circuit_state"] == "open"
    assert result["consecutive_failures"] == 5

    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )

        assert webhook.circuit_state == "open"
        assert webhook.consecutive_failures == 5
        assert webhook.circuit_opened_at is not None

    finally:
        db.close()


def test_worker_success_resets_circuit_breaker(
    worker_delivery,
    monkeypatch,
):
    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )
        webhook.consecutive_failures = 4
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(200, "Recovered"),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "succeeded"
    assert result["circuit_state"] == "closed"

    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )

        assert webhook.circuit_state == "closed"
        assert webhook.consecutive_failures == 0
        assert webhook.circuit_opened_at is None

    finally:
        db.close()

def test_worker_network_timeout(worker_delivery, monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise worker_tasks.httpx.TimeoutException("Connection timed out")

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        raise_timeout,
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "retrying"

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "retrying"
        assert delivery.attempt_count == 1
        assert delivery.last_error is not None
    finally:
        db.close()


def test_worker_half_open_failure_reopens_circuit(
    worker_delivery,
    monkeypatch,
):
    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )
        webhook.circuit_state = "half_open"
        webhook.consecutive_failures = 5
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(500, "Server Error"),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "retrying"
    assert result["circuit_state"] == "open"

    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )

        assert webhook.circuit_state == "open"
        assert webhook.consecutive_failures >= 5
        assert webhook.circuit_opened_at is not None
    finally:
        db.close()


def test_worker_rejects_invalid_claim_token(
    worker_delivery,
    monkeypatch,
):
    request_called = False

    def fake_post(*args, **kwargs):
        nonlocal request_called
        request_called = True
        return mock_http_response(200, "OK")

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        fake_post,
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        str(uuid4()),
    )

    assert result["status"] == "claim_rejected"
    assert request_called is False

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "processing"
        assert delivery.attempt_count == 0
    finally:
        db.close()


def test_worker_pauses_inactive_webhook(
    worker_delivery,
    monkeypatch,
):
    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )
        webhook.is_active = False
        db.commit()
    finally:
        db.close()

    request_called = False

    def fake_post(*args, **kwargs):
        nonlocal request_called
        request_called = True
        return mock_http_response(200, "OK")

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        fake_post,
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "paused"
    assert request_called is False

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "paused"
        assert delivery.attempt_count == 0
        assert delivery.claim_token is None
    finally:
        db.close()



@pytest.mark.parametrize("status_code", [400, 404])
def test_worker_permanent_http_failure(
    worker_delivery,
    monkeypatch,
    status_code,
):
    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(
            status_code,
            "Permanent client error",
        ),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "failed"
    assert result["http_status_code"] == status_code
    assert result["attempt_number"] == 1

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "failed"
        assert delivery.attempt_count == 1
        assert delivery.next_attempt_at is None
        assert delivery.last_status_code == status_code

        attempts = db.scalars(
            select(DeliveryAttempt).where(
                DeliveryAttempt.delivery_id == delivery.id
            )
        ).all()

        assert len(attempts) == 1
        assert attempts[0].http_status_code == status_code
        assert attempts[0].error_message is not None
        assert attempts[0].completed_at is not None

    finally:
        db.close()



def test_worker_http_429_schedules_retry(
    worker_delivery,
    monkeypatch,
):
    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(
            429,
            "Too Many Requests",
        ),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "retrying"
    assert result["attempt_number"] == 1
    assert result["retry_in_seconds"] > 0
    assert result["circuit_state"] == "closed"

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "retrying"
        assert delivery.attempt_count == 1
        assert delivery.last_status_code == 429
        assert delivery.next_attempt_at is not None

        attempt = db.scalar(
            select(DeliveryAttempt).where(
                DeliveryAttempt.delivery_id == delivery.id
            )
        )

        assert attempt is not None
        assert attempt.http_status_code == 429
        assert attempt.error_message is not None

    finally:
        db.close()


def test_worker_retry_uses_exponential_backoff_with_jitter(
    worker_delivery,
    monkeypatch,
):
    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(
            500,
            "Server Error",
        ),
    )

    monkeypatch.setattr(
        worker_tasks.random,
        "uniform",
        lambda minimum, maximum: 0.5,
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    # First retry: 2 ** (1 - 1) + 0.5 = 1.5 seconds.
    assert result["status"] == "retrying"
    assert result["retry_in_seconds"] == 1.5

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        assert delivery.status == "retrying"
        assert delivery.next_attempt_at is not None

    finally:
        db.close()


def test_worker_half_open_success_closes_circuit(
    worker_delivery,
    monkeypatch,
):
    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )

        webhook.circuit_state = "half_open"
        webhook.consecutive_failures = 5

        db.commit()

    finally:
        db.close()

    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(
            200,
            "Recovery successful",
        ),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "succeeded"
    assert result["circuit_state"] == "closed"

    db = worker_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(worker_delivery["webhook_id"]),
        )

        assert webhook.circuit_state == "closed"
        assert webhook.consecutive_failures == 0
        assert webhook.circuit_opened_at is None

    finally:
        db.close()


def test_worker_records_attempt_response_details(
    worker_delivery,
    monkeypatch,
):
    monkeypatch.setattr(
        worker_tasks.httpx,
        "post",
        lambda *args, **kwargs: mock_http_response(
            500,
            "Temporary server failure",
        ),
    )

    result = worker_tasks.deliver_webhook.run(
        worker_delivery["delivery_id"],
        worker_delivery["claim_token"],
    )

    assert result["status"] == "retrying"

    db = worker_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(worker_delivery["delivery_id"]),
        )

        attempts = db.scalars(
            select(DeliveryAttempt).where(
                DeliveryAttempt.delivery_id == delivery.id
            )
        ).all()

        assert len(attempts) == 1

        attempt = attempts[0]

        assert attempt.attempt_number == 1
        assert attempt.http_status_code == 500
        assert attempt.response_body == "Temporary server failure"
        assert attempt.error_message is not None
        assert attempt.started_at is not None
        assert attempt.completed_at is not None
        assert attempt.duration_ms >= 0

    finally:
        db.close()
