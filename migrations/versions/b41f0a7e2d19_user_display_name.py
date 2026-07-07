"""user display name

Revision ID: b41f0a7e2d19
Revises: d9106d3c8c92
Create Date: 2026-07-07 09:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b41f0a7e2d19'
down_revision: Union[str, Sequence[str], None] = 'd9106d3c8c92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Optional display name; existing rows stay NULL (valid: no name set)."""
    op.add_column(
        "users",
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("name")
