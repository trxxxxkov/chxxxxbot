"""Phase 1.5: Add user_files table and Extended Thinking support.

This migration adds:
1. user_files table for Files API integration (images, PDFs, documents)
2. thinking_blocks column in messages for Extended Thinking
3. Cache tracking columns in messages (cache_creation, cache_read, thinking tokens)

Files API lifecycle:
- User uploads file → Telegram → Files API → user_files table
- Files expire after FILES_API_TTL_HOURS (default: 24h)
- Cleanup cron job deletes expired files

Extended Thinking:
- thinking_blocks: Full thinking content from Claude (can be large)
- thinking_tokens: Token count for thinking (for billing)
- CRITICAL: Must include thinking blocks with tool_result (cryptographic signature)

Revision ID: 005
Revises: 004
Create Date: 2026-01-09 16:00:00.000000

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add user_files table and thinking/cache columns.

    1. Create user_files table for Files API integration
    2. Add thinking_blocks to messages (Extended Thinking content)
    3. Add cache tracking columns to messages (Phase 1.4.2)
    4. Add thinking_tokens to messages (Extended Thinking billing)
    """
    # 1. Create user_files table
    op.create_table(
        'user_files',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('message_id', sa.BigInteger, nullable=False),

        # Telegram data
        sa.Column('telegram_file_id', sa.String, nullable=True),
        sa.Column('telegram_file_unique_id', sa.String, nullable=True),

        # Claude Files API data
        sa.Column('claude_file_id', sa.String, nullable=False, unique=True),

        # Metadata
        sa.Column('filename', sa.String, nullable=False),
        sa.Column('file_type',
                  sa.Enum('image',
                          'pdf',
                          'document',
                          'generated',
                          name='filetype'),
                  nullable=False),
        sa.Column('mime_type', sa.String, nullable=False),
        sa.Column('file_size', sa.Integer, nullable=False),

        # Lifecycle
        sa.Column('uploaded_at',
                  sa.DateTime,
                  server_default=sa.func.now(),
                  nullable=False),
        sa.Column('expires_at', sa.DateTime, nullable=False),

        # Source
        sa.Column('source',
                  sa.Enum('user', 'assistant', name='filesource'),
                  nullable=False),

        # Optional metadata (JSONB)
        sa.Column('metadata', JSONB, nullable=True),
    )

    # Create indexes for user_files
    op.create_index('idx_user_files_message_id', 'user_files', ['message_id'])
    op.create_index('idx_user_files_claude_file_id',
                    'user_files', ['claude_file_id'],
                    unique=True)
    op.create_index('idx_user_files_expires_at', 'user_files', ['expires_at'])
    op.create_index('idx_user_files_file_type', 'user_files', ['file_type'])

    # 2. Add thinking_blocks to messages (Extended Thinking)
    op.add_column('messages',
                  sa.Column('thinking_blocks', sa.Text, nullable=True))

    # 3. Add cache tracking columns to messages (Phase 1.4.2)
    op.add_column(
        'messages',
        sa.Column('cache_creation_input_tokens', sa.Integer, nullable=True))
    op.add_column(
        'messages',
        sa.Column('cache_read_input_tokens', sa.Integer, nullable=True))

    # 4. Add thinking_tokens to messages (Extended Thinking billing)
    op.add_column('messages',
                  sa.Column('thinking_tokens', sa.Integer, nullable=True))


def downgrade() -> None:
    """Downgrade schema: remove user_files table and thinking/cache columns."""
    # Remove columns from messages
    op.drop_column('messages', 'thinking_tokens')
    op.drop_column('messages', 'cache_read_input_tokens')
    op.drop_column('messages', 'cache_creation_input_tokens')
    op.drop_column('messages', 'thinking_blocks')

    # Drop indexes for user_files
    op.drop_index('idx_user_files_file_type', 'user_files')
    op.drop_index('idx_user_files_expires_at', 'user_files')
    op.drop_index('idx_user_files_claude_file_id', 'user_files')
    op.drop_index('idx_user_files_message_id', 'user_files')

    # Drop user_files table
    op.drop_table('user_files')

    # Drop enums (PostgreSQL requires explicit drop)
    op.execute('DROP TYPE IF EXISTS filesource')
    op.execute('DROP TYPE IF EXISTS filetype')
