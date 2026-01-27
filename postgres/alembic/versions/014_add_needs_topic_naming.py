"""Add needs_topic_naming to threads.

Bot API 9.3 added topics in private chats. This field tracks whether
a topic needs LLM-generated naming after the first bot response.

Set True on thread creation (for topics), False after naming.

Revision ID: 014
Revises: 013
Create Date: 2026-01-27 12:00:00

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '014'
down_revision: Union[str, None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add needs_topic_naming column to threads."""
    op.add_column(
        'threads',
        sa.Column('needs_topic_naming',
                  sa.Boolean(),
                  nullable=False,
                  server_default='false',
                  comment='Whether topic needs LLM-generated name'))


def downgrade() -> None:
    """Remove needs_topic_naming column."""
    op.drop_column('threads', 'needs_topic_naming')
