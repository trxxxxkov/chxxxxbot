"""Phase 1.4.2: Add custom_prompt and files_context for 3-level system prompt.

This migration adds fields for 3-level system prompt architecture:
1. GLOBAL_SYSTEM_PROMPT (config.py, always cached) - same for all users
2. User.custom_prompt (per user, cached) - personal preferences/personality
3. Thread.files_context (per thread, NOT cached) - list of available files

Final prompt = GLOBAL + custom_prompt + files_context

Revision ID: 004
Revises: 003
Create Date: 2026-01-09 14:00:00.000000

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add custom_prompt to users, files_context to threads.

    - User.custom_prompt: Personal instructions (personality, tone, style)
    - Thread.files_context: Auto-generated list of files available in thread
    """
    # Add custom_prompt to users table
    op.add_column('users', sa.Column('custom_prompt', sa.Text, nullable=True))

    # Add files_context to threads table
    op.add_column('threads', sa.Column('files_context', sa.Text, nullable=True))


def downgrade() -> None:
    """Downgrade schema: remove custom_prompt and files_context."""
    # Remove files_context from threads
    op.drop_column('threads', 'files_context')

    # Remove custom_prompt from users
    op.drop_column('users', 'custom_prompt')
