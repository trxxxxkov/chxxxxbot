"""Phase 1.4.1: Remove system_prompt from threads (prepare for Phase 1.4.2).

This migration removes threads.system_prompt column as preparation for
Phase 1.4.2 which will implement 3-level system prompt architecture:
- GLOBAL_SYSTEM_PROMPT (always cached)
- User.custom_prompt (per user, cached)
- Thread.files_context (per thread, dynamic)

Revision ID: 003
Revises: 002
Create Date: 2026-01-09 12:00:00.000000

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: drop threads.system_prompt column.

    System prompt will be composed in Phase 1.4.2 from:
    - GLOBAL_SYSTEM_PROMPT (config.py, always cached)
    - User.custom_prompt (per user, to be added)
    - Thread.files_context (per thread, to be added)
    """
    op.drop_column('threads', 'system_prompt')


def downgrade() -> None:
    """Downgrade schema: restore threads.system_prompt column."""
    op.add_column('threads', sa.Column('system_prompt', sa.Text, nullable=True))
