
import hashlib
import hmac
import importlib
import time

import pytest
import redis

from fastapi.testclient import TestClient


TEST_SECRET = "local-hmac-test-secret-2026"


class FakeRedis:
    def __init__(self):
        self.values = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return None

        self.values[key] = value
        return True


@pytest.fixture
def receiver_module(monkeypatch):
    monkeypatch.setenv("WEBHOOK_TEST_SECRET", TEST_SECRET)

    import receiver

    receiver = importlib.reload(receiver)
    monkeypatch.setattr(receiver, "redis_client", FakeRedis())

    return receiver


@pytest.fixture
def client(receiver_module):
    with TestClient(receiver_module.app) as test_client:
        yield test_client


def generate_signature(body: bytes, timestamp: str) -> str:
    signed_payload = timestamp.encode("utf-8") + b"." + body

    digest = hmac.new(
        TEST_SECRET.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return f"sha256={digest}"


def make_headers(
    body: bytes,
    delivery_id="test-delivery-001",
    timestamp=None,
):
    if timestamp is None:
        timestamp = str(int(time.time()))

    return {
        "Content-Type": "application/json",
        "X-Webhook-Signature": generate_signature(body, timestamp),
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Event": "load.in_transit",
        "X-Webhook-Delivery": delivery_id,
    }


def test_valid_signature_is_accepted(client):
    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'

    response = client.post(
        "/receiver",
        content=body,
        headers=make_headers(body),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "signature_verified"


def test_invalid_signature_is_rejected(client):
    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'

    headers = make_headers(body)
    headers["X-Webhook-Signature"] = "sha256=invalid-signature"

    response = client.post(
        "/receiver",
        content=body,
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature"


def test_missing_signature_is_rejected(client):
    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'
    headers = make_headers(body)
    headers.pop("X-Webhook-Signature")

    response = client.post(
        "/receiver",
        content=body,
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing webhook signature"


def test_missing_timestamp_is_rejected(client):
    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'
    headers = make_headers(body)
    headers.pop("X-Webhook-Timestamp")

    response = client.post(
        "/receiver",
        content=body,
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing webhook timestamp"


def test_invalid_timestamp_is_rejected(client):
    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'
    headers = make_headers(body)
    headers["X-Webhook-Timestamp"] = "not-a-timestamp"

    response = client.post(
        "/receiver",
        content=body,
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook timestamp"


@pytest.mark.parametrize(
    "timestamp",
    [
        str(int(time.time()) - 600),
        str(int(time.time()) + 600),
    ],
)
def test_expired_or_future_timestamp_is_rejected(client, timestamp):
    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'

    response = client.post(
        "/receiver",
        content=body,
        headers=make_headers(body, timestamp=timestamp),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Webhook timestamp expired"


def test_timestamp_is_part_of_signature(client):
    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'
    headers = make_headers(body)

    # Change the timestamp without recalculating the signature.
    headers["X-Webhook-Timestamp"] = str(int(time.time()) - 10)

    response = client.post(
        "/receiver",
        content=body,
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature"


def test_invalid_json_is_rejected(client):
    body = b'{"load_number":'

    response = client.post(
        "/receiver",
        content=body,
        headers=make_headers(body),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON payload"


def test_duplicate_delivery_is_ignored(client):
    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'
    headers = make_headers(
        body,
        delivery_id="duplicate-delivery-001",
    )

    first_response = client.post(
        "/receiver",
        content=body,
        headers=headers,
    )

    second_response = client.post(
        "/receiver",
        content=body,
        headers=headers,
    )

    assert first_response.status_code == 200
    assert first_response.json()["status"] == "signature_verified"

    assert second_response.status_code == 200
    assert second_response.json()["status"] == "duplicate_ignored"


def test_redis_failure_returns_503(client, receiver_module, monkeypatch):
    class BrokenRedis:
        def set(self, *args, **kwargs):
            raise redis.RedisError("Redis unavailable")

    monkeypatch.setattr(
        receiver_module,
        "redis_client",
        BrokenRedis(),
    )

    body = b'{"load_number":"LOAD-1004","status":"in_transit"}'

    response = client.post(
        "/receiver",
        content=body,
        headers=make_headers(body),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Replay protection service unavailable"
    )
