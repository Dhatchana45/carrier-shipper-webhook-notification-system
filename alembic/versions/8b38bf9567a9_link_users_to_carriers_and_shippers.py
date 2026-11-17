
"""link users to carriers and shippers

Revision ID: 8b38bf9567a9
Revises: 0f776d5d635f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8b38bf9567a9"
down_revision: Union[str, Sequence[str], None] = "0f776d5d635f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("carrier_id", sa.Uuid(), nullable=True),
    )

    op.add_column(
        "users",
        sa.Column("shipper_id", sa.Uuid(), nullable=True),
    )

    op.create_index(
        "ix_users_carrier_id",
        "users",
        ["carrier_id"],
        unique=False,
    )

    op.create_index(
        "ix_users_shipper_id",
        "users",
        ["shipper_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_users_carrier_id_carriers",
        "users",
        "carriers",
        ["carrier_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_foreign_key(
        "fk_users_shipper_id_shippers",
        "users",
        "shippers",
        ["shipper_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_users_shipper_id_shippers",
        "users",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_users_carrier_id_carriers",
        "users",
        type_="foreignkey",
    )

    op.drop_index("ix_users_shipper_id", table_name="users")
    op.drop_index("ix_users_carrier_id", table_name="users")

    op.drop_column("users", "shipper_id")
    op.drop_column("users", "carrier_id")
