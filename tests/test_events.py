from types import SimpleNamespace

import pytest

from app.api import events as events_api


@pytest.fixture(autouse=True)
def disable_celery_dispatch(monkeypatch):
    # Prevent tests from sending real Celery tasks.
    fake_task = SimpleNamespace(delay=lambda: None)

    monkeypatch.setattr(
        events_api,
        "dispatch_pending_deliveries",
        fake_task
    )


def create_test_webhook(client):
    payload = {
        "name": "Test Shipment Webhook",
        "target_url": "https://example.com/webhook",
        "subscribed_event_types": [
            "shipment.created",
            "shipment.delivered"
        ],
        "is_active": True
    }

    response = client.post("/webhooks/", json=payload)

    assert response.status_code == 201

    return response.json()


def create_test_event(client, idempotency_key="SHIPMENT-2001-CREATED"):
    payload = {
        "event_type": "shipment.created",
        "idempotency_key": idempotency_key,
        "payload": {
            "shipment_id": "SHIPMENT-2001",
            "carrier": "ABC Logistics",
            "shipper": "XYZ Manufacturing",
            "origin": "Coimbatore",
            "destination": "Chennai",
            "status": "created"
        }
    }

    return client.post("/events/", json=payload)


def test_create_event(client):
    response = create_test_event(client)

    assert response.status_code == 201

    data = response.json()

    assert data["event_type"] == "shipment.created"
    assert data["idempotency_key"] == "SHIPMENT-2001-CREATED"
    assert data["payload"]["shipment_id"] == "SHIPMENT-2001"
    assert data["outbox_status"] == "pending"
    assert data["id"] is not None


def test_create_event_generates_delivery(client):
    create_test_webhook(client)

    event_response = create_test_event(client)

    assert event_response.status_code == 201

    event_id = event_response.json()["id"]

    delivery_response = client.get("/deliveries/")

    assert delivery_response.status_code == 200

    deliveries = delivery_response.json()

    matching_deliveries = [
        delivery for delivery in deliveries
        if delivery["event_id"] == event_id
    ]

    assert len(matching_deliveries) == 1

    delivery = matching_deliveries[0]

    assert delivery["status"] == "pending"
    assert delivery["attempt_count"] == 0
    assert delivery["max_attempts"] == 8


def test_duplicate_event_idempotency(client):
    create_test_webhook(client)

    first_response = create_test_event(
        client,
        "SHIPMENT-3001-CREATED"
    )

    second_response = create_test_event(
        client,
        "SHIPMENT-3001-CREATED"
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    first_event = first_response.json()
    second_event = second_response.json()

    # Both requests must return the same event.
    assert first_event["id"] == second_event["id"]

    # The original event payload must be preserved.
    assert second_event["payload"]["shipment_id"] == "SHIPMENT-2001"

    delivery_response = client.get("/deliveries/")

    deliveries = [
        delivery for delivery in delivery_response.json()
        if delivery["event_id"] == first_event["id"]
    ]

    # Repeated submissions must not create duplicate deliveries.
    assert len(deliveries) == 1


def test_different_idempotency_keys_create_different_events(client):
    first_response = create_test_event(
        client,
        "SHIPMENT-4001-CREATED"
    )

    second_response = create_test_event(
        client,
        "SHIPMENT-4002-CREATED"
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    assert first_response.json()["id"] != second_response.json()["id"]


def test_list_events(client):
    create_test_event(client, "SHIPMENT-5001-CREATED")
    create_test_event(client, "SHIPMENT-5002-CREATED")

    response = client.get("/events/")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_event(client):
    create_response = create_test_event(
        client,
        "SHIPMENT-6001-CREATED"
    )

    event_id = create_response.json()["id"]

    response = client.get(f"/events/{event_id}")

    assert response.status_code == 200
    assert response.json()["id"] == event_id
    assert response.json()["event_type"] == "shipment.created"


def test_get_nonexistent_event(client):
    response = client.get(
        "/events/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Event not found"


def test_invalid_event_data(client):
    payload = {
        "event_type": "x",
        "idempotency_key": "A",
        "payload": {}
    }

    response = client.post("/events/", json=payload)

    assert response.status_code == 422
