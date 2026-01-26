"""Add upload_context to user_files.

Stores the text message that accompanied a file upload, helping
the model understand what each file is about without analyzing it.

Example: User sends image with caption "Here's my math homework"
-> upload_context = "Here's my math homework"

Revision ID: 012
Revises: 011
Create Date: 2026-01-26 12:00:00

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '012'
down_revision: Union[str, None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add upload_context column to user_files."""
    op.add_column(
        'user_files',
        sa.Column(
            'upload_context',
            sa.String(),
            nullable=True,
            comment='Text message sent with the file (helps model identify it)')
    )


def downgrade() -> None:
    """Remove upload_context column."""
    op.drop_column('user_files', 'upload_context')
