"""Add is_cleared to threads.

Tracks whether a Telegram topic has been deleted via /clear command.
Threads are marked as cleared instead of deleted to preserve history.
Cleared threads are excluded from topic counts.

Revision ID: 015
Revises: 014
Create Date: 2026-01-28 12:00:00

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '015'
down_revision: Union[str, None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_cleared column to threads."""
    op.add_column(
        'threads',
        sa.Column('is_cleared',
                  sa.Boolean(),
                  nullable=False,
                  server_default='false',
                  comment='Whether topic has been deleted via /clear'))


def downgrade() -> None:
    """Remove is_cleared column."""
    op.drop_column('threads', 'is_cleared')
