"""grip type names are display names

Revision ID: d9106d3c8c92
Revises: d6cd3e963370
Create Date: 2026-07-03 15:41:25.119632

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'd9106d3c8c92'
down_revision: Union[str, Sequence[str], None] = 'd6cd3e963370'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Grip type names are display names: drop the underscores."""
    op.execute("UPDATE grip_types SET name = REPLACE(name, '_', ' ')")


def downgrade() -> None:
    op.execute("UPDATE grip_types SET name = REPLACE(name, ' ', '_')")
