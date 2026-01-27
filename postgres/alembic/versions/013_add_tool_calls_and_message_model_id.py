"""Add tool_calls table and model_id to messages.

Creates tool_calls table for tracking tool execution costs separately
from main conversation messages. Also adds model_id to messages for
accurate cost attribution.

Revision ID: 013
Revises: 012
Create Date: 2026-01-27 12:00:00

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '013'
down_revision: Union[str, None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tool_calls table and add model_id to messages."""
    # Create tool_calls table
    op.create_table(
        'tool_calls',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('thread_id', sa.BigInteger(), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('tool_name', sa.String(64), nullable=False),
        sa.Column('model_id', sa.String(64), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False, default=0),
        sa.Column('output_tokens', sa.Integer(), nullable=False, default=0),
        sa.Column('cache_read_tokens', sa.Integer(), nullable=False, default=0),
        sa.Column('cache_creation_tokens',
                  sa.Integer(),
                  nullable=False,
                  default=0),
        sa.Column('cost_usd', sa.Numeric(precision=12, scale=6),
                  nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, default=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.text('now()'),
                  nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['thread_id'], ['threads.id'],
                                ondelete='SET NULL'),
    )

    # Create indexes
    op.create_index('idx_tool_calls_user', 'tool_calls', ['user_id'])
    op.create_index('idx_tool_calls_chat', 'tool_calls', ['chat_id'])
    op.create_index('idx_tool_calls_created', 'tool_calls', ['created_at'])
    op.create_index('idx_tool_calls_tool_name', 'tool_calls', ['tool_name'])

    # Add model_id to messages table
    op.add_column(
        'messages',
        sa.Column(
            'model_id',
            sa.String(64),
            nullable=True,
            comment='Model used for this response (e.g., claude-sonnet-4-5)'))


def downgrade() -> None:
    """Remove tool_calls table and model_id from messages."""
    op.drop_column('messages', 'model_id')
    op.drop_index('idx_tool_calls_tool_name', table_name='tool_calls')
    op.drop_index('idx_tool_calls_created', table_name='tool_calls')
    op.drop_index('idx_tool_calls_chat', table_name='tool_calls')
    op.drop_index('idx_tool_calls_user', table_name='tool_calls')
    op.drop_table('tool_calls')
