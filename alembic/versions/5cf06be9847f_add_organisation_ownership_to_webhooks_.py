
"""add organisation ownership to webhooks and events

Revision ID: 5cf06be9847f
Revises: 8b38bf9567a9
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5cf06be9847f"
down_revision: Union[str, Sequence[str], None] = "8b38bf9567a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Event ownership
    op.add_column(
        "events",
        sa.Column("carrier_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("shipper_id", sa.Uuid(), nullable=True),
    )

    op.create_index(
        "ix_events_carrier_id", "events", ["carrier_id"]
    )
    op.create_index(
        "ix_events_shipper_id", "events", ["shipper_id"]
    )

    op.create_foreign_key(
        "fk_events_carrier_id_carriers",
        "events",
        "carriers",
        ["carrier_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_events_shipper_id_shippers",
        "events",
        "shippers",
        ["shipper_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Webhook ownership
    op.add_column(
        "webhooks",
        sa.Column("carrier_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "webhooks",
        sa.Column("shipper_id", sa.Uuid(), nullable=True),
    )

    op.create_index(
        "ix_webhooks_carrier_id", "webhooks", ["carrier_id"]
    )
    op.create_index(
        "ix_webhooks_shipper_id", "webhooks", ["shipper_id"]
    )

    op.create_foreign_key(
        "fk_webhooks_carrier_id_carriers",
        "webhooks",
        "carriers",
        ["carrier_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_webhooks_shipper_id_shippers",
        "webhooks",
        "shippers",
        ["shipper_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        "ck_webhooks_single_organisation_owner",
        "webhooks",
        "carrier_id IS NULL OR shipper_id IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_webhooks_single_organisation_owner",
        "webhooks",
        type_="check",
    )

    op.drop_constraint(
        "fk_webhooks_shipper_id_shippers",
        "webhooks",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_webhooks_carrier_id_carriers",
        "webhooks",
        type_="foreignkey",
    )

    op.drop_index("ix_webhooks_shipper_id", table_name="webhooks")
    op.drop_index("ix_webhooks_carrier_id", table_name="webhooks")

    op.drop_column("webhooks", "shipper_id")
    op.drop_column("webhooks", "carrier_id")

    op.drop_constraint(
        "fk_events_shipper_id_shippers",
        "events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_events_carrier_id_carriers",
        "events",
        type_="foreignkey",
    )

    op.drop_index("ix_events_shipper_id", table_name="events")
    op.drop_index("ix_events_carrier_id", table_name="events")

    op.drop_column("events", "shipper_id")
    op.drop_column("events", "carrier_id")
