"""Phase 1.4.1: Rename model_name to model_id in threads table.

This migration renames the column and updates the data format from
legacy "claude" to new composite format "claude:sonnet".

Revision ID: 001
Revises:
Create Date: 2026-01-09 12:00:00.000000

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: rename model_name to model_id and update data format.

    Steps:
    1. Rename column model_name to model_id
    2. Increase column length from 50 to 100 (for "provider:alias" format)
    3. Update existing data: "claude" -> "claude:sonnet"
    4. Update default value: "claude" -> "claude:sonnet"
    """
    # Step 1: Rename column
    op.alter_column('threads', 'model_name', new_column_name='model_id')

    # Step 2: Increase column length
    op.alter_column('threads',
                    'model_id',
                    type_=sa.String(100),
                    existing_type=sa.String(50),
                    existing_nullable=False)

    # Step 3: Update existing data (legacy "claude" -> new "claude:sonnet")
    op.execute("UPDATE threads "
               "SET model_id = 'claude:sonnet' "
               "WHERE model_id = 'claude'")

    # Step 4: Update default value
    op.alter_column('threads',
                    'model_id',
                    server_default='claude:sonnet',
                    existing_type=sa.String(100),
                    existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema: revert model_id back to model_name.

    Steps:
    1. Update data: "claude:sonnet" -> "claude", "claude:haiku" -> "claude", etc.
    2. Update default value: "claude:sonnet" -> "claude"
    3. Decrease column length back to 50
    4. Rename column back to model_name
    """
    # Step 1: Update data (any claude model -> "claude")
    op.execute("UPDATE threads "
               "SET model_id = 'claude' "
               "WHERE model_id LIKE 'claude:%'")

    # Step 2: Update default value
    op.alter_column('threads',
                    'model_id',
                    server_default='claude',
                    existing_type=sa.String(100),
                    existing_nullable=False)

    # Step 3: Decrease column length
    op.alter_column('threads',
                    'model_id',
                    type_=sa.String(50),
                    existing_type=sa.String(100),
                    existing_nullable=False)

    # Step 4: Rename column back
    op.alter_column('threads', 'model_id', new_column_name='model_name')
