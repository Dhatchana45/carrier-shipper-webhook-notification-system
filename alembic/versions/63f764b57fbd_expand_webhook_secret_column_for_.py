
"""expand webhook secret column for encryption

Revision ID: 63f764b57fbd
Revises: 5cf06be9847f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "63f764b57fbd"
down_revision: Union[str, Sequence[str], None] = "5cf06be9847f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "webhooks",
        "secret",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    connection = op.get_bind()

    oversized_secrets = connection.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM webhooks
            WHERE secret IS NOT NULL
              AND length(secret) > 255
            """
        )
    ).scalar_one()

    if oversized_secrets:
        raise RuntimeError(
            "Cannot downgrade webhook.secret to VARCHAR(255): "
            "some stored secrets exceed 255 characters."
        )

    op.alter_column(
        "webhooks",
        "secret",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
