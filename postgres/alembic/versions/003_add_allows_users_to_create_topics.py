"""Add allows_users_to_create_topics column to users table.

Bot API 9.4 introduced this field on User objects. Stores whether
the bot allows users to create topics in private chat.

Revision ID: 003
Create Date: 2026-02-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add allows_users_to_create_topics column."""
    op.add_column(
        'users',
        sa.Column(
            'allows_users_to_create_topics',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade() -> None:
    """Remove allows_users_to_create_topics column."""
    op.drop_column('users', 'allows_users_to_create_topics')
