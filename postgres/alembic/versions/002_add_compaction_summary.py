"""Add compaction_summary column to messages table.

Opus 4.6 server-side compaction stores a summary of prior context.
When present, the API ignores all messages before the compacted one.

Revision ID: 002
Create Date: 2026-02-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add compaction_summary column."""
    op.add_column(
        'messages',
        sa.Column('compaction_summary', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove compaction_summary column."""
    op.drop_column('messages', 'compaction_summary')
