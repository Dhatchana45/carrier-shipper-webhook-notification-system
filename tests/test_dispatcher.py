from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import Delivery,DeliveryAttempt, Event, Webhook
from app.workers import dispatcher as dispatcher_tasks


@pytest.fixture
def dispatcher_data(test_engine, monkeypatch):
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        dispatcher_tasks,
        "SessionLocal",
        TestingSessionLocal,
    )

    sent_tasks = []

    def fake_send_task(name, args=None, **kwargs):
        sent_tasks.append({
            "name": name,
            "args": args,
        })

    monkeypatch.setattr(
        dispatcher_tasks.celery_app,
        "send_task",
        fake_send_task,
    )

    db = TestingSessionLocal()

    webhook = Webhook(
        name="Dispatcher Test Webhook",
        target_url="https://example.com/webhook",
        secret="dispatcher-test-secret",
        subscribed_event_types=["shipment.created"],
        is_active=True,
        circuit_state="closed",
        consecutive_failures=0,
    )

    event = Event(
        event_type="shipment.created",
        idempotency_key=f"DISPATCH-{uuid4()}",
        payload={
            "shipment_id": "SHIPMENT-DISPATCH-1001",
            "status": "created",
        },
        outbox_status="pending",
    )

    db.add_all([webhook, event])
    db.flush()

    delivery = Delivery(
        event_id=event.id,
        webhook_id=webhook.id,
        status="pending",
        attempt_count=0,
        max_attempts=8,
    )

    db.add(delivery)
    db.commit()

    result = {
        "webhook_id": str(webhook.id),
        "event_id": str(event.id),
        "delivery_id": str(delivery.id),
        "sent_tasks": sent_tasks,
    }

    db.close()

    yield result


def test_dispatcher_claims_pending_delivery(dispatcher_data):
    result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert result["dispatched_count"] == 1
    assert result["recovered_count"] == 0

    assert len(dispatcher_data["sent_tasks"]) == 1

    task = dispatcher_data["sent_tasks"][0]

    assert task["name"] == "app.workers.tasks.deliver_webhook"
    assert task["args"][0] == dispatcher_data["delivery_id"]
    assert task["args"][1] is not None

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        assert delivery.status == "processing"
        assert delivery.claim_token is not None
        assert delivery.processing_started_at is not None

        event = db.get(
            Event,
            UUID(dispatcher_data["event_id"]),
        )

        assert event.outbox_status == "published"
        assert event.published_at is not None

    finally:
        db.close()


def test_dispatcher_claims_due_retry(dispatcher_data):
    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        delivery.status = "retrying"
        delivery.next_attempt_at = (
            datetime.now(timezone.utc) - timedelta(seconds=10)
        )

        db.commit()

    finally:
        db.close()

    result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert result["dispatched_count"] == 1
    assert len(dispatcher_data["sent_tasks"]) == 1

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        assert delivery.status == "processing"
        assert delivery.claim_token is not None

    finally:
        db.close()



def test_dispatcher_recovers_stale_processing_delivery(
    dispatcher_data,
):
    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        stale_started_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )

        delivery.status = "processing"
        delivery.attempt_count = 1
        delivery.claim_token = uuid4()
        delivery.processing_started_at = stale_started_at

        attempt = DeliveryAttempt(
            delivery_id=delivery.id,
            attempt_number=1,
            started_at=stale_started_at,
            completed_at=None,
        )

        db.add(attempt)
        db.commit()

        attempt_id = attempt.id

    finally:
        db.close()

    # First cycle: recover the stale delivery.
    first_result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert first_result["recovered_count"] == 1
    assert first_result["dispatched_count"] == 0

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        assert delivery.status == "retrying"
        assert delivery.attempt_count == 1
        assert delivery.claim_token is None
        assert delivery.processing_started_at is None
        assert delivery.next_attempt_at is not None

        # Verify the interrupted attempt was closed.
        recovered_attempt = db.get(DeliveryAttempt, attempt_id)

        assert recovered_attempt is not None
        assert recovered_attempt.completed_at is not None
        assert "timed out" in recovered_attempt.error_message.lower()
        assert recovered_attempt.duration_ms is not None
        assert recovered_attempt.duration_ms >= 0

        # HTTP response details must remain untouched.
        assert recovered_attempt.http_status_code is None
        assert recovered_attempt.response_body is None

    finally:
        db.close()

    # Second cycle: dispatch the recovered retry.
    second_result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert second_result["dispatched_count"] == 1
    assert len(dispatcher_data["sent_tasks"]) == 1

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        assert delivery.status == "processing"
        assert delivery.attempt_count == 1
        assert delivery.claim_token is not None

    finally:
        db.close()


def test_dispatcher_fails_stale_delivery_at_max_attempts(
    dispatcher_data,
):
    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        delivery.status = "processing"
        delivery.attempt_count = 8
        delivery.max_attempts = 8
        delivery.claim_token = uuid4()
        delivery.processing_started_at = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )

        db.commit()

    finally:
        db.close()

    result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert result["recovered_count"] == 1
    assert result["dispatched_count"] == 0
    assert len(dispatcher_data["sent_tasks"]) == 0

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        assert delivery.status == "failed"
        assert delivery.claim_token is None
        assert delivery.next_attempt_at is None

    finally:
        db.close()


def test_dispatcher_pauses_inactive_webhook(dispatcher_data):
    db = dispatcher_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(dispatcher_data["webhook_id"]),
        )

        webhook.is_active = False
        db.commit()

    finally:
        db.close()

    result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert result["dispatched_count"] == 0
    assert len(dispatcher_data["sent_tasks"]) == 0

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        assert delivery.status == "paused"
        assert delivery.claim_token is None

    finally:
        db.close()


def test_dispatcher_does_not_claim_active_processing_delivery(
    dispatcher_data,
):
    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        delivery.status = "processing"
        delivery.claim_token = uuid4()
        delivery.processing_started_at = datetime.now(timezone.utc)

        db.commit()

    finally:
        db.close()

    result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert result["dispatched_count"] == 0
    assert len(dispatcher_data["sent_tasks"]) == 0

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        assert delivery.status == "processing"

    finally:
        db.close()


def test_dispatcher_defers_open_circuit_delivery(
    dispatcher_data,
    monkeypatch,
):
    class TestDateTime:
        @staticmethod
        def now(tz=None):
            # SQLite returns timezone-naive DateTime values.
            # Use a consistent naive UTC clock for this test.
            return datetime.now(timezone.utc).replace(tzinfo=None)

    monkeypatch.setattr(
        dispatcher_tasks,
        "datetime",
        TestDateTime,
    )

    db = dispatcher_tasks.SessionLocal()

    try:
        webhook = db.get(
            Webhook,
            UUID(dispatcher_data["webhook_id"]),
        )

        webhook.circuit_state = "open"
        webhook.circuit_opened_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(seconds=10)
        )

        db.commit()

    finally:
        db.close()

    result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert result["dispatched_count"] == 0
    assert len(dispatcher_data["sent_tasks"]) == 0

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        webhook = db.get(
            Webhook,
            UUID(dispatcher_data["webhook_id"]),
        )

        assert delivery.status == "retrying"
        assert delivery.next_attempt_at is not None
        assert webhook.circuit_state == "open"

    finally:
        db.close()


def test_dispatcher_restores_claim_when_enqueue_fails(
    dispatcher_data,
    monkeypatch,
):
    def failed_send_task(*args, **kwargs):
        raise RuntimeError("Redis enqueue failed")

    monkeypatch.setattr(
        dispatcher_tasks.celery_app,
        "send_task",
        failed_send_task,
    )

    result = dispatcher_tasks.dispatch_pending_deliveries.run()

    assert result["dispatched_count"] == 0

    db = dispatcher_tasks.SessionLocal()

    try:
        delivery = db.get(
            Delivery,
            UUID(dispatcher_data["delivery_id"]),
        )

        assert delivery.status == "pending"
        assert delivery.claim_token is None
        assert delivery.processing_started_at is None

        event = db.get(
            Event,
            UUID(dispatcher_data["event_id"]),
        )

        assert event.outbox_status == "pending"
        assert event.published_at is None

    finally:
        db.close()
