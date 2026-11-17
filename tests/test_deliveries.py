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
        "name": "Delivery Test Webhook",
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


def create_test_event(client, idempotency_key="SHIPMENT-7001-CREATED"):
    payload = {
        "event_type": "shipment.created",
        "idempotency_key": idempotency_key,
        "payload": {
            "shipment_id": "SHIPMENT-7001",
            "carrier": "ABC Logistics",
            "shipper": "XYZ Manufacturing",
            "origin": "Coimbatore",
            "destination": "Chennai",
            "status": "created"
        }
    }

    return client.post("/events/", json=payload)


def create_test_delivery(client, idempotency_key="SHIPMENT-7001-CREATED"):
    create_test_webhook(client)

    event_response = create_test_event(client, idempotency_key)

    assert event_response.status_code == 201

    event_id = event_response.json()["id"]

    delivery_response = client.get("/deliveries/")

    assert delivery_response.status_code == 200

    matching_deliveries = [
        delivery
        for delivery in delivery_response.json()
        if delivery["event_id"] == event_id
    ]

    assert len(matching_deliveries) == 1

    return matching_deliveries[0]


def test_list_deliveries(client):
    # Create only one webhook for both events.
    create_test_webhook(client)

    first_event = create_test_event(
        client,
        "SHIPMENT-7001-CREATED"
    )

    second_event = create_test_event(
        client,
        "SHIPMENT-7002-CREATED"
    )

    assert first_event.status_code == 201
    assert second_event.status_code == 201

    response = client.get("/deliveries/")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_delivery(client):
    delivery = create_test_delivery(client)

    delivery_id = delivery["id"]

    response = client.get(f"/deliveries/{delivery_id}")

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == delivery_id
    assert data["status"] == "pending"
    assert data["attempt_count"] == 0
    assert data["max_attempts"] == 8


def test_get_delivery_attempts(client):
    delivery = create_test_delivery(client)

    delivery_id = delivery["id"]

    response = client.get(
        f"/deliveries/{delivery_id}/attempts"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_get_nonexistent_delivery(client):
    response = client.get(
        "/deliveries/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Delivery not found"


def test_get_attempts_for_nonexistent_delivery(client):
    response = client.get(
        "/deliveries/00000000-0000-0000-0000-000000000001/attempts"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Delivery not found"
