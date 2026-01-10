"""Fix expires_at timezone.

Revision ID: 008_fix_expires_at
Revises: 317c14d820cd
Create Date: 2026-01-10 23:45:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '008_fix_expires_at'
down_revision = '317c14d820cd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Change expires_at from TIMESTAMP to TIMESTAMP WITH TIME ZONE."""
    # Alter column to add timezone
    op.execute("""
        ALTER TABLE user_files
        ALTER COLUMN expires_at
        TYPE TIMESTAMP WITH TIME ZONE
        USING expires_at AT TIME ZONE 'UTC'
    """)


def downgrade() -> None:
    """Revert expires_at to TIMESTAMP WITHOUT TIME ZONE."""
    # Remove timezone
    op.execute("""
        ALTER TABLE user_files
        ALTER COLUMN expires_at
        TYPE TIMESTAMP WITHOUT TIME ZONE
    """)
