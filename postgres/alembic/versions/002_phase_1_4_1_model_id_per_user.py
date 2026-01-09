"""Phase 1.4.1: Move model_id from Thread to User (per user, not per thread).

This migration moves model selection from per-thread to per-user:
- Rename users.current_model -> users.model_id
- Update format from "claude" to "claude:sonnet"
- Drop threads.model_id (no longer needed)

Revision ID: 002
Revises: 001
Create Date: 2026-01-09 12:00:00.000000

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: move model_id from Thread to User.

    Steps:
    1. Rename users.current_model to users.model_id
    2. Increase column length from 50 to 100
    3. Update existing data: "claude" -> "claude:sonnet"
    4. Update default value: "claude" -> "claude:sonnet"
    5. Drop threads.model_id column
    """
    # Step 1: Rename column in users table
    op.alter_column('users', 'current_model', new_column_name='model_id')

    # Step 2: Increase column length
    op.alter_column('users',
                    'model_id',
                    type_=sa.String(100),
                    existing_type=sa.String(50),
                    existing_nullable=False)

    # Step 3: Update existing data (legacy "claude" -> new "claude:sonnet")
    op.execute("UPDATE users SET model_id = 'claude:sonnet' "
               "WHERE model_id = 'claude'")

    # Step 4: Update default value
    op.alter_column('users',
                    'model_id',
                    server_default='claude:sonnet',
                    existing_type=sa.String(100),
                    existing_nullable=False)

    # Step 5: Drop model_id from threads table (no longer per-thread)
    op.drop_column('threads', 'model_id')


def downgrade() -> None:
    """Downgrade schema: move model_id back from User to Thread.

    Steps:
    1. Add threads.model_id column back
    2. Update users data: "claude:sonnet" -> "claude"
    3. Update users default value: "claude:sonnet" -> "claude"
    4. Decrease users.model_id length back to 50
    5. Rename users.model_id back to users.current_model
    """
    # Step 1: Add model_id column back to threads
    op.add_column(
        'threads',
        sa.Column('model_id',
                  sa.String(100),
                  nullable=False,
                  server_default='claude:sonnet'))

    # Step 2: Update users data (any claude model -> "claude")
    op.execute(
        "UPDATE users SET model_id = 'claude' WHERE model_id LIKE 'claude:%'")

    # Step 3: Update users default value
    op.alter_column('users',
                    'model_id',
                    server_default='claude',
                    existing_type=sa.String(100),
                    existing_nullable=False)

    # Step 4: Decrease column length
    op.alter_column('users',
                    'model_id',
                    type_=sa.String(50),
                    existing_type=sa.String(100),
                    existing_nullable=False)

    # Step 5: Rename column back
    op.alter_column('users', 'model_id', new_column_name='current_model')
