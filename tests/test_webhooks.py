
def create_webhook(client, name="Test Carrier Webhook"):
    payload = {
        "name": name,
        "target_url": "https://example.com/webhook",
        "subscribed_event_types": [
            "shipment.created",
            "shipment.delivered",
        ],
        "is_active": True,
    }

    return client.post("/webhooks/", json=payload)


def test_create_webhook(client):
    response = create_webhook(client)

    assert response.status_code == 201, response.json()

    data = response.json()

    assert data["name"] == "Test Carrier Webhook"
    assert data["target_url"].startswith("https://example.com")
    assert data["subscribed_event_types"] == [
        "shipment.created",
        "shipment.delivered",
    ]
    assert data["is_active"] is True
    assert data["circuit_state"] == "closed"
    assert data["consecutive_failures"] == 0

    # Secret must not be exposed in the API response.
    assert "secret" not in data


def test_list_webhooks(client):
    first = create_webhook(client, "Carrier One")
    second = create_webhook(client, "Carrier Two")

    assert first.status_code == 201, first.json()
    assert second.status_code == 201, second.json()

    response = client.get("/webhooks/")

    assert response.status_code == 200, response.json()
    assert len(response.json()) == 2


def test_get_webhook(client):
    create_response = create_webhook(client)
    assert create_response.status_code == 201, create_response.json()

    webhook_id = create_response.json()["id"]

    response = client.get(f"/webhooks/{webhook_id}")

    assert response.status_code == 200
    assert response.json()["id"] == webhook_id
    assert response.json()["name"] == "Test Carrier Webhook"


def test_update_webhook(client):
    create_response = create_webhook(client)
    assert create_response.status_code == 201, create_response.json()

    webhook_id = create_response.json()["id"]

    update_payload = {
        "name": "Updated Carrier Webhook",
        "is_active": False,
    }

    response = client.patch(
        f"/webhooks/{webhook_id}",
        json=update_payload,
    )

    assert response.status_code == 200, response.json()
    assert response.json()["name"] == "Updated Carrier Webhook"
    assert response.json()["is_active"] is False


def test_soft_delete_webhook(client):
    create_response = create_webhook(client)
    assert create_response.status_code == 201, create_response.json()

    webhook_id = create_response.json()["id"]

    delete_response = client.delete(f"/webhooks/{webhook_id}")

    assert delete_response.status_code == 204

    # The record should still exist but be inactive.
    get_response = client.get(f"/webhooks/{webhook_id}")

    assert get_response.status_code == 200
    assert get_response.json()["is_active"] is False


def test_get_nonexistent_webhook(client):
    response = client.get(
        "/webhooks/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Webhook not found"


def test_update_nonexistent_webhook(client):
    response = client.patch(
        "/webhooks/00000000-0000-0000-0000-000000000001",
        json={"name": "Updated Webhook"},
    )

    assert response.status_code == 404


def test_delete_nonexistent_webhook(client):
    response = client.delete(
        "/webhooks/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404


def test_invalid_webhook_data(client):
    payload = {
        "name": "A",
        "target_url": "not-a-valid-url",
        "subscribed_event_types": [],
        "is_active": True,
    }

    response = client.post("/webhooks/", json=payload)

    assert response.status_code == 422
