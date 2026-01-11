"""Fix uploaded_at timezone.

Change uploaded_at from TIMESTAMP to TIMESTAMP WITH TIME ZONE
for consistency with expires_at and to prevent datetime comparison errors.

Revision ID: 010
Revises: 009
Create Date: 2026-01-11 16:00:00

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change uploaded_at from TIMESTAMP to TIMESTAMP WITH TIME ZONE."""
    op.execute("""
        ALTER TABLE user_files
        ALTER COLUMN uploaded_at
        TYPE TIMESTAMP WITH TIME ZONE
        USING uploaded_at AT TIME ZONE 'UTC'
    """)


def downgrade() -> None:
    """Revert uploaded_at to TIMESTAMP WITHOUT TIME ZONE."""
    op.execute("""
        ALTER TABLE user_files
        ALTER COLUMN uploaded_at
        TYPE TIMESTAMP WITHOUT TIME ZONE
    """)
