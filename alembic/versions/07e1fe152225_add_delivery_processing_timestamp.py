"""add delivery processing timestamp

Revision ID: 07e1fe152225
Revises: 125e34fec6ef
Create Date: 2026-11-02 14:11:48.003581
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "07e1fe152225"
down_revision: Union[str, Sequence[str], None] = "125e34fec6ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deliveries",
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("deliveries", "processing_started_at")