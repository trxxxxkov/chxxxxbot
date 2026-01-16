"""Add user statistics fields for activity tracking.

This migration adds statistics fields to the users table:
- message_count: Total messages sent by user
- total_tokens_used: Total tokens consumed (input + output)

These enable metrics like top active users and usage tracking.

Revision ID: 009
Revises: 008_fix_expires_at
Create Date: 2026-01-11 14:00:00.000000

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, None] = '008_fix_expires_at'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add message_count and total_tokens_used columns to users."""
    op.add_column(
        'users',
        sa.Column(
            'message_count',
            sa.BigInteger(),
            nullable=False,
            server_default='0',
        ))
    op.add_column(
        'users',
        sa.Column(
            'total_tokens_used',
            sa.BigInteger(),
            nullable=False,
            server_default='0',
        ))


def downgrade() -> None:
    """Remove statistics columns from users."""
    op.drop_column('users', 'total_tokens_used')
    op.drop_column('users', 'message_count')
