
def create_organisation_webhook(client, name):
    payload = {
        "name": name,
        "target_url": "https://example.com/webhook",
        "subscribed_event_types": [
            "shipment.created",
            "shipment.delivered",
        ],
        "is_active": True,
    }

    response = client.post("/webhooks/", json=payload)

    assert response.status_code == 201, response.json()

    return response.json()


# ============================================================
# WEBHOOK ORGANISATION ISOLATION TESTS
# ============================================================

def test_carrier_cannot_list_another_carriers_webhooks(org_clients):
    carrier_a = org_clients["carrier_a"]
    carrier_b = org_clients["carrier_b"]

    create_organisation_webhook(
        carrier_a,
        "Carrier A Webhook",
    )

    create_organisation_webhook(
        carrier_b,
        "Carrier B Webhook",
    )

    response = carrier_a.get("/webhooks/")

    assert response.status_code == 200

    webhooks = response.json()

    assert len(webhooks) == 1
    assert webhooks[0]["name"] == "Carrier A Webhook"


def test_carrier_cannot_access_another_carriers_webhook(org_clients):
    carrier_a = org_clients["carrier_a"]
    carrier_b = org_clients["carrier_b"]

    webhook = create_organisation_webhook(
        carrier_b,
        "Carrier B Private Webhook",
    )

    response = carrier_a.get(
        f"/webhooks/{webhook['id']}"
    )

    assert response.status_code == 404


def test_shipper_cannot_list_another_shippers_webhooks(org_clients):
    shipper_a = org_clients["shipper_a"]
    shipper_b = org_clients["shipper_b"]

    create_organisation_webhook(
        shipper_a,
        "Shipper A Webhook",
    )

    create_organisation_webhook(
        shipper_b,
        "Shipper B Webhook",
    )

    response = shipper_a.get("/webhooks/")

    assert response.status_code == 200

    webhooks = response.json()

    assert len(webhooks) == 1
    assert webhooks[0]["name"] == "Shipper A Webhook"


def test_shipper_cannot_access_another_shippers_webhook(org_clients):
    shipper_a = org_clients["shipper_a"]
    shipper_b = org_clients["shipper_b"]

    webhook = create_organisation_webhook(
        shipper_b,
        "Shipper B Private Webhook",
    )

    response = shipper_a.get(
        f"/webhooks/{webhook['id']}"
    )

    assert response.status_code == 404


def test_admin_can_list_all_organisation_webhooks(org_clients):
    admin = org_clients["admin"]

    create_organisation_webhook(
        org_clients["carrier_a"],
        "Carrier A Webhook",
    )

    create_organisation_webhook(
        org_clients["carrier_b"],
        "Carrier B Webhook",
    )

    create_organisation_webhook(
        org_clients["shipper_a"],
        "Shipper A Webhook",
    )

    response = admin.get("/webhooks/")

    assert response.status_code == 200

    names = {
        webhook["name"]
        for webhook in response.json()
    }

    assert names == {
        "Carrier A Webhook",
        "Carrier B Webhook",
        "Shipper A Webhook",
    }


def test_unlinked_carrier_cannot_create_webhook(org_clients):
    response = org_clients["unlinked_carrier"].post(
        "/webhooks/",
        json={
            "name": "Unlinked Carrier Webhook",
            "target_url": "https://example.com/webhook",
            "subscribed_event_types": ["shipment.created"],
            "is_active": True,
        },
    )

    assert response.status_code == 403


def test_unlinked_shipper_cannot_create_webhook(org_clients):
    response = org_clients["unlinked_shipper"].post(
        "/webhooks/",
        json={
            "name": "Unlinked Shipper Webhook",
            "target_url": "https://example.com/webhook",
            "subscribed_event_types": ["shipment.created"],
            "is_active": True,
        },
    )

    assert response.status_code == 403


# ============================================================
# EVENT AND DELIVERY TEST DATA HELPER
# ============================================================

def create_security_delivery_records(org_clients):
    from uuid import UUID

    from app.models import Event, Delivery, DeliveryAttempt

    session_factory = org_clients["db_session_factory"]

    organisations = [
        ("carrier_a", "carrier_a", "carrier_id"),
        ("carrier_b", "carrier_b", "carrier_id"),
        ("shipper_a", "shipper_a", "shipper_id"),
        ("shipper_b", "shipper_b", "shipper_id"),
    ]

    records = {}

    with session_factory() as db:
        for client_key, organisation_key, owner_field in organisations:
            webhook = create_organisation_webhook(
                org_clients[client_key],
                f"Security Test {client_key} Webhook",
            )

            event = Event(
                event_type="shipment.created",
                payload={
                    "test": True,
                    "owner": client_key,
                },
                carrier_id=(
                    UUID(
                        str(
                            org_clients["organisation_ids"][organisation_key]
                        )
                    )
                    if owner_field == "carrier_id"
                    else None
                ),
                shipper_id=(
                    UUID(
                        str(
                            org_clients["organisation_ids"][organisation_key]
                        )
                    )
                    if owner_field == "shipper_id"
                    else None
                ),
                outbox_status="published",
            )

            db.add(event)
            db.flush()

            delivery = Delivery(
                event_id=event.id,
                webhook_id=UUID(str(webhook["id"])),
                status="succeeded",
                attempt_count=1,
                max_attempts=8,
            )

            db.add(delivery)
            db.flush()

            attempt = DeliveryAttempt(
                delivery_id=delivery.id,
                attempt_number=1,
                http_status_code=200,
                response_body="OK",
                duration_ms=25,
            )

            db.add(attempt)
            db.flush()

            records[client_key] = {
                "event_id": str(event.id),
                "delivery_id": str(delivery.id),
                "attempt_id": str(attempt.id),
            }

        db.commit()

    return records


# ============================================================
# EVENT ORGANISATION ISOLATION TESTS
# ============================================================

def test_carrier_cannot_list_another_carriers_events(org_clients):
    records = create_security_delivery_records(org_clients)

    response = org_clients["carrier_a"].get("/events/")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == records["carrier_a"]["event_id"]


def test_carrier_cannot_access_another_carriers_event(org_clients):
    records = create_security_delivery_records(org_clients)

    response = org_clients["carrier_a"].get(
        f"/events/{records['carrier_b']['event_id']}"
    )

    assert response.status_code == 404


def test_shipper_cannot_list_another_shippers_events(org_clients):
    records = create_security_delivery_records(org_clients)

    response = org_clients["shipper_a"].get("/events/")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == records["shipper_a"]["event_id"]


def test_shipper_cannot_access_another_shippers_event(org_clients):
    records = create_security_delivery_records(org_clients)

    response = org_clients["shipper_a"].get(
        f"/events/{records['shipper_b']['event_id']}"
    )

    assert response.status_code == 404


# ============================================================
# DELIVERY ORGANISATION ISOLATION TESTS
# ============================================================

def test_carrier_cannot_list_another_carriers_deliveries(org_clients):
    records = create_security_delivery_records(org_clients)

    response = org_clients["carrier_a"].get("/deliveries/")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == records["carrier_a"]["delivery_id"]


def test_carrier_cannot_access_another_carriers_delivery(org_clients):
    records = create_security_delivery_records(org_clients)

    response = org_clients["carrier_a"].get(
        f"/deliveries/{records['carrier_b']['delivery_id']}"
    )

    assert response.status_code == 404


def test_shipper_cannot_list_another_shippers_deliveries(org_clients):
    records = create_security_delivery_records(org_clients)

    response = org_clients["shipper_a"].get("/deliveries/")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == records["shipper_a"]["delivery_id"]


def test_shipper_cannot_access_another_shippers_delivery(org_clients):
    records = create_security_delivery_records(org_clients)

    response = org_clients["shipper_a"].get(
        f"/deliveries/{records['shipper_b']['delivery_id']}"
    )

    assert response.status_code == 404



# ============================================================
# LOAD AND DRIVER SECURITY TEST DATA HELPER
# ============================================================

def create_security_load_records(org_clients):
    admin = org_clients["admin"]

    records = {}

    organisations = [
        ("carrier_a", "shipper_a"),
        ("carrier_b", "shipper_b"),
    ]

    for carrier_key, shipper_key in organisations:
        driver_response = org_clients[carrier_key].post(
            "/drivers/",
            json={
                "name": f"Security Test Driver {carrier_key}",
                "phone": "9876543210",
                "license_number": f"SEC-LIC-{carrier_key.upper()}",
            },
        )

        assert driver_response.status_code == 201, driver_response.json()

        driver = driver_response.json()

        load_response = admin.post(
            "/loads/",
            json={
                "load_number": f"SECURITY-LOAD-{carrier_key.upper()}",
                "shipper_id": org_clients["organisation_ids"][shipper_key],
                "carrier_id": org_clients["organisation_ids"][carrier_key],
                "driver_id": driver["id"],
                "origin": "Coimbatore",
                "destination": "Chennai",
            },
        )

        assert load_response.status_code == 201, load_response.json()

        load = load_response.json()

        records[carrier_key] = {
            "load_id": load["id"],
            "driver_id": driver["id"],
            "shipper_key": shipper_key,
        }

    return records


# ============================================================
# LOAD ORGANISATION ISOLATION TESTS
# ============================================================

def test_carrier_cannot_list_another_carriers_loads(org_clients):
    records = create_security_load_records(org_clients)

    response = org_clients["carrier_a"].get("/loads/")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == records["carrier_a"]["load_id"]


def test_carrier_cannot_access_another_carriers_load(org_clients):
    records = create_security_load_records(org_clients)

    response = org_clients["carrier_a"].get(
        f"/loads/{records['carrier_b']['load_id']}"
    )

    assert response.status_code == 404


def test_shipper_cannot_list_another_shippers_loads(org_clients):
    records = create_security_load_records(org_clients)

    response = org_clients["shipper_a"].get("/loads/")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == records["carrier_a"]["load_id"]


def test_shipper_cannot_access_another_shippers_load(org_clients):
    records = create_security_load_records(org_clients)

    response = org_clients["shipper_a"].get(
        f"/loads/{records['carrier_b']['load_id']}"
    )

    assert response.status_code == 404


# ============================================================
# DRIVER ORGANISATION ISOLATION TESTS
# ============================================================

def test_carrier_cannot_list_another_carriers_drivers(org_clients):
    records = create_security_load_records(org_clients)

    response = org_clients["carrier_a"].get("/drivers/")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == records["carrier_a"]["driver_id"]


def test_shipper_cannot_list_drivers(org_clients):
    response = org_clients["shipper_a"].get("/drivers/")

    assert response.status_code == 403


def test_unlinked_carrier_cannot_create_driver(org_clients):
    response = org_clients["unlinked_carrier"].post(
        "/drivers/",
        json={
            "name": "Unlinked Test Driver",
            "phone": "9876543210",
            "license_number": "UNLINKED-LIC-001",
        },
    )

    assert response.status_code == 403


def test_shipper_cannot_create_driver(org_clients):
    response = org_clients["shipper_a"].post(
        "/drivers/",
        json={
            "name": "Shipper Test Driver",
            "phone": "9876543210",
            "license_number": "SHIPPER-LIC-001",
        },
    )

    assert response.status_code == 403


def test_carrier_cannot_create_driver_for_another_carrier(org_clients):
    carrier_a_id = org_clients["organisation_ids"]["carrier_a"]
    carrier_b_id = org_clients["organisation_ids"]["carrier_b"]

    response = org_clients["carrier_a"].post(
        "/drivers/",
        json={
            "carrier_id": carrier_b_id,
            "name": "Carrier A Ownership Test Driver",
            "phone": "9876543210",
            "license_number": "CROSS-CARRIER-LIC-001",
        },
    )

    assert response.status_code == 201

    driver = response.json()

    # The API must use the authenticated carrier's ID,
    # not the carrier_id supplied in the request.
    assert driver["carrier_id"] == carrier_a_id
    assert driver["carrier_id"] != carrier_b_id


# ============================================================
# CARRIER AND SHIPPER PROFILE ISOLATION TESTS
# ============================================================

def test_carrier_cannot_access_another_carrier_profile(org_clients):
    carrier_b_id = org_clients["organisation_ids"]["carrier_b"]

    response = org_clients["carrier_a"].get(
        f"/carriers/{carrier_b_id}"
    )

    assert response.status_code == 403


def test_shipper_cannot_access_another_shipper_profile(org_clients):
    shipper_b_id = org_clients["organisation_ids"]["shipper_b"]

    response = org_clients["shipper_a"].get(
        f"/shippers/{shipper_b_id}"
    )

    assert response.status_code == 403


# ============================================================
# LOAD ASSIGNMENT AND STATUS PERMISSION TESTS
# ============================================================

def test_carrier_cannot_assign_load(org_clients):
    records = create_security_load_records(org_clients)

    carrier_b_id = org_clients["organisation_ids"]["carrier_b"]

    response = org_clients["carrier_a"].patch(
        f"/loads/{records['carrier_a']['load_id']}/assign",
        json={
            "carrier_id": carrier_b_id,
            "driver_id": records["carrier_b"]["driver_id"],
        },
    )

    assert response.status_code == 403


def test_shipper_cannot_update_load_status(org_clients):
    records = create_security_load_records(org_clients)

    response = org_clients["shipper_a"].patch(
        f"/loads/{records['carrier_a']['load_id']}/status",
        json={
            "status": "cancelled",
        },
    )

    assert response.status_code == 403


def test_carrier_cannot_update_another_carriers_load_status(org_clients):
    records = create_security_load_records(org_clients)

    response = org_clients["carrier_a"].patch(
        f"/loads/{records['carrier_b']['load_id']}/status",
        json={
            "status": "cancelled",
        },
    )

    assert response.status_code == 404



# ============================================================
# LOAD CREATION AND OWNERSHIP SECURITY TESTS
# ============================================================

def test_shipper_cannot_create_load_for_another_shipper(org_clients):
    shipper_b_id = org_clients["organisation_ids"]["shipper_b"]

    response = org_clients["shipper_a"].post(
        "/loads/",
        json={
            "load_number": "SECURITY-CROSS-SHIPPER-001",
            "shipper_id": shipper_b_id,
            "origin": "Coimbatore",
            "destination": "Chennai",
        },
    )

    assert response.status_code == 403


def test_shipper_cannot_assign_carrier_during_load_creation(org_clients):
    shipper_a_id = org_clients["organisation_ids"]["shipper_a"]
    carrier_a_id = org_clients["organisation_ids"]["carrier_a"]

    response = org_clients["shipper_a"].post(
        "/loads/",
        json={
            "load_number": "SECURITY-SHIPPER-CARRIER-001",
            "shipper_id": shipper_a_id,
            "carrier_id": carrier_a_id,
            "origin": "Coimbatore",
            "destination": "Chennai",
        },
    )

    assert response.status_code == 403


def test_shipper_cannot_assign_driver_during_load_creation(org_clients):
    shipper_a_id = org_clients["organisation_ids"]["shipper_a"]

    response = org_clients["shipper_a"].post(
        "/loads/",
        json={
            "load_number": "SECURITY-SHIPPER-DRIVER-001",
            "shipper_id": shipper_a_id,
            "driver_id": "00000000-0000-0000-0000-000000000001",
            "origin": "Coimbatore",
            "destination": "Chennai",
        },
    )

    assert response.status_code == 403


def test_carrier_cannot_create_load(org_clients):
    shipper_a_id = org_clients["organisation_ids"]["shipper_a"]

    response = org_clients["carrier_a"].post(
        "/loads/",
        json={
            "load_number": "SECURITY-CARRIER-CREATE-001",
            "shipper_id": shipper_a_id,
            "origin": "Coimbatore",
            "destination": "Chennai",
        },
    )

    assert response.status_code == 403


def test_unlinked_shipper_cannot_create_load(org_clients):
    shipper_a_id = org_clients["organisation_ids"]["shipper_a"]

    response = org_clients["unlinked_shipper"].post(
        "/loads/",
        json={
            "load_number": "SECURITY-UNLINKED-SHIPPER-001",
            "shipper_id": shipper_a_id,
            "origin": "Coimbatore",
            "destination": "Chennai",
        },
    )

    assert response.status_code == 403


def test_admin_can_list_loads_from_all_organisations(org_clients):
    records = create_security_load_records(org_clients)

    response = org_clients["admin"].get("/loads/")

    assert response.status_code == 200

    returned_load_ids = {
        load["id"]
        for load in response.json()
    }

    assert records["carrier_a"]["load_id"] in returned_load_ids
    assert records["carrier_b"]["load_id"] in returned_load_ids


# ============================================================
# LOAD ASSIGNMENT VALIDATION TEST HELPER
# ============================================================

def create_unassigned_security_load(org_clients):
    response = org_clients["admin"].post(
        "/loads/",
        json={
            "load_number": "ASSIGN-TEST-" + __import__("uuid").uuid4().hex[:12],
            "shipper_id": org_clients["organisation_ids"]["shipper_a"],
            "origin": "Coimbatore",
            "destination": "Chennai",
        },
    )

    assert response.status_code == 201, response.json()

    return response.json()


# ============================================================
# LOAD ASSIGNMENT VALIDATION TESTS
# ============================================================

def test_admin_cannot_assign_inactive_carrier(org_clients):
    from uuid import UUID

    from app.models import Carrier

    load = create_unassigned_security_load(org_clients)
    records = create_security_load_records(org_clients)

    carrier_id = UUID(org_clients["organisation_ids"]["carrier_a"])

    db = org_clients["db_session_factory"]()

    try:
        carrier = db.get(Carrier, carrier_id)
        carrier.is_active = False
        db.commit()
    finally:
        db.close()

    response = org_clients["admin"].patch(
        f"/loads/{load['id']}/assign",
        json={
            "carrier_id": str(carrier_id),
            "driver_id": records["carrier_a"]["driver_id"],
        },
    )

    assert response.status_code == 404

    detail_response = org_clients["admin"].get(
        f"/loads/{load['id']}"
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["carrier_id"] is None
    assert detail_response.json()["driver_id"] is None


def test_admin_cannot_assign_inactive_driver(org_clients):
    from uuid import UUID

    from app.models import Driver

    load = create_unassigned_security_load(org_clients)
    records = create_security_load_records(org_clients)

    driver_id = UUID(records["carrier_a"]["driver_id"])

    db = org_clients["db_session_factory"]()

    try:
        driver = db.get(Driver, driver_id)
        driver.is_active = False
        db.commit()
    finally:
        db.close()

    response = org_clients["admin"].patch(
        f"/loads/{load['id']}/assign",
        json={
            "carrier_id": org_clients["organisation_ids"]["carrier_a"],
            "driver_id": str(driver_id),
        },
    )

    assert response.status_code == 422

    detail_response = org_clients["admin"].get(
        f"/loads/{load['id']}"
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["carrier_id"] is None
    assert detail_response.json()["driver_id"] is None


def test_admin_cannot_assign_driver_from_another_carrier(org_clients):
    load = create_unassigned_security_load(org_clients)
    records = create_security_load_records(org_clients)

    response = org_clients["admin"].patch(
        f"/loads/{load['id']}/assign",
        json={
            "carrier_id": org_clients["organisation_ids"]["carrier_a"],
            "driver_id": records["carrier_b"]["driver_id"],
        },
    )

    assert response.status_code == 422

    detail_response = org_clients["admin"].get(
        f"/loads/{load['id']}"
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["carrier_id"] is None
    assert detail_response.json()["driver_id"] is None


def test_admin_cannot_assign_driver_without_carrier(org_clients):
    load = create_unassigned_security_load(org_clients)
    records = create_security_load_records(org_clients)

    response = org_clients["admin"].patch(
        f"/loads/{load['id']}/assign",
        json={
            "driver_id": records["carrier_a"]["driver_id"],
        },
    )

    # carrier_id is required by the LoadAssignment schema.
    assert response.status_code == 422


def test_admin_can_reassign_load_to_another_valid_carrier(org_clients):
    load = create_unassigned_security_load(org_clients)
    records = create_security_load_records(org_clients)

    response = org_clients["admin"].patch(
        f"/loads/{load['id']}/assign",
        json={
            "carrier_id": org_clients["organisation_ids"]["carrier_a"],
            "driver_id": records["carrier_a"]["driver_id"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "assigned"

    # Reassign the same load to another valid carrier and driver.
    reassignment_response = org_clients["admin"].patch(
        f"/loads/{load['id']}/assign",
        json={
            "carrier_id": org_clients["organisation_ids"]["carrier_b"],
            "driver_id": records["carrier_b"]["driver_id"],
        },
    )

    assert reassignment_response.status_code == 200
    assert reassignment_response.json()["status"] == "assigned"
    assert (
        reassignment_response.json()["carrier_id"]
        == org_clients["organisation_ids"]["carrier_b"]
    )
    assert (
        reassignment_response.json()["driver_id"]
        == records["carrier_b"]["driver_id"]
    )
