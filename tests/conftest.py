
from contextlib import ExitStack

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app as fastapi_app
from app.models import User, Carrier, Shipper
from app.auth_service import create_access_token


@pytest.fixture
def test_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def client(test_engine):
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db

    db = TestingSessionLocal()

    try:
        test_admin = User(
            username="test_admin",
            email="test_admin@example.com",
            hashed_password="test-only-password-hash",
            role="admin",
            is_active=True,
        )

        db.add(test_admin)
        db.commit()
        db.refresh(test_admin)

        access_token = create_access_token(
            data={"sub": str(test_admin.id)}
        )

    finally:
        db.close()

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    try:
        with TestClient(
            fastapi_app,
            headers=headers,
        ) as test_client:
            yield test_client

    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def org_clients(test_engine):
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db

    db = TestingSessionLocal()

    try:
        carrier_a = Carrier(
            name="Test Carrier A",
            code="TEST-CARRIER-A",
            is_active=True,
        )

        carrier_b = Carrier(
            name="Test Carrier B",
            code="TEST-CARRIER-B",
            is_active=True,
        )

        shipper_a = Shipper(
            name="Test Shipper A",
            code="TEST-SHIPPER-A",
            is_active=True,
        )

        shipper_b = Shipper(
            name="Test Shipper B",
            code="TEST-SHIPPER-B",
            is_active=True,
        )

        db.add_all([
            carrier_a,
            carrier_b,
            shipper_a,
            shipper_b,
        ])

        db.flush()

        users = {
            "admin": User(
                username="security_admin",
                email="security_admin@example.com",
                hashed_password="test-only-password-hash",
                role="admin",
                is_active=True,
            ),
            "carrier_a": User(
                username="security_carrier_a",
                email="security_carrier_a@example.com",
                hashed_password="test-only-password-hash",
                role="carrier",
                carrier_id=carrier_a.id,
                is_active=True,
            ),
            "carrier_b": User(
                username="security_carrier_b",
                email="security_carrier_b@example.com",
                hashed_password="test-only-password-hash",
                role="carrier",
                carrier_id=carrier_b.id,
                is_active=True,
            ),
            "shipper_a": User(
                username="security_shipper_a",
                email="security_shipper_a@example.com",
                hashed_password="test-only-password-hash",
                role="shipper",
                shipper_id=shipper_a.id,
                is_active=True,
            ),
            "shipper_b": User(
                username="security_shipper_b",
                email="security_shipper_b@example.com",
                hashed_password="test-only-password-hash",
                role="shipper",
                shipper_id=shipper_b.id,
                is_active=True,
            ),
            "unlinked_carrier": User(
                username="security_unlinked_carrier",
                email="security_unlinked_carrier@example.com",
                hashed_password="test-only-password-hash",
                role="carrier",
                is_active=True,
            ),
            "unlinked_shipper": User(
                username="security_unlinked_shipper",
                email="security_unlinked_shipper@example.com",
                hashed_password="test-only-password-hash",
                role="shipper",
                is_active=True,
            ),
        }

        db.add_all(users.values())
        db.commit()

        for user in users.values():
            db.refresh(user)

        user_ids = {
            name: str(user.id)
            for name, user in users.items()
        }

        organisation_ids = {
            "carrier_a": str(carrier_a.id),
            "carrier_b": str(carrier_b.id),
            "shipper_a": str(shipper_a.id),
            "shipper_b": str(shipper_b.id),
        }

        tokens = {
            name: create_access_token(
                data={"sub": str(user.id)}
            )
            for name, user in users.items()
        }

    finally:
        db.close()

    clients = {}

    try:
        with ExitStack() as stack:
            for name, token in tokens.items():
                clients[name] = stack.enter_context(
                    TestClient(
                        fastapi_app,
                        headers={
                            "Authorization": f"Bearer {token}"
                        },
                    )
                )

            yield {
    **clients,
    "user_ids": user_ids,
    "organisation_ids": organisation_ids,
    "db_session_factory": TestingSessionLocal,
}
    finally:
        fastapi_app.dependency_overrides.clear()
