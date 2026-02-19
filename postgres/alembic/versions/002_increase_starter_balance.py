"""Increase starter balance from $0.10 to $0.50.

Revision ID: 002
Revises: 001
Create Date: 2026-02-19
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change server_default for users.balance from 0.1000 to 0.5000."""
    op.alter_column(
        'users',
        'balance',
        server_default='0.5000',
    )


def downgrade() -> None:
    """Revert server_default for users.balance to 0.1000."""
    op.alter_column(
        'users',
        'balance',
        server_default='0.1000',
    )
