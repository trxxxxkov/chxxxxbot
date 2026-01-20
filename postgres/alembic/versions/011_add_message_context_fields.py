"""Add message context fields for Telegram features.

Adds fields for:
- Forward origin (forwarded messages context)
- Reply context (snippet and sender display for replied messages)
- Quote data (quoted text in replies)
- Sender display (cached @username or "First Last")
- Edit tracking (count and original content)

Revision ID: 011
Revises: 010
Create Date: 2026-01-20 12:00:00

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add message context fields."""
    # Forward context
    op.add_column(
        'messages',
        sa.Column(
            'forward_origin',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=
            'Forward origin: {type, display, date, chat_id?, message_id?}'))

    # Reply context (denormalized for performance)
    op.add_column(
        'messages',
        sa.Column('reply_snippet',
                  sa.Text(),
                  nullable=True,
                  comment='First 200 chars of replied message'))
    op.add_column(
        'messages',
        sa.Column(
            'reply_sender_display',
            sa.Text(),
            nullable=True,
            comment='@username or "First Last" of replied message sender'))

    # Quote data
    op.add_column(
        'messages',
        sa.Column('quote_data',
                  postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True,
                  comment='Quote: {text, position, is_manual}'))

    # Sender display (cached)
    op.add_column(
        'messages',
        sa.Column('sender_display',
                  sa.Text(),
                  nullable=True,
                  comment='@username or "First Last" for message sender'))

    # Edit tracking
    op.add_column(
        'messages',
        sa.Column('edit_count',
                  sa.Integer(),
                  nullable=False,
                  server_default='0',
                  comment='Number of times message was edited'))
    op.add_column(
        'messages',
        sa.Column('original_content',
                  sa.Text(),
                  nullable=True,
                  comment='First version of text before any edits'))


def downgrade() -> None:
    """Remove message context fields."""
    op.drop_column('messages', 'original_content')
    op.drop_column('messages', 'edit_count')
    op.drop_column('messages', 'sender_display')
    op.drop_column('messages', 'quote_data')
    op.drop_column('messages', 'reply_sender_display')
    op.drop_column('messages', 'reply_snippet')
    op.drop_column('messages', 'forward_origin')
