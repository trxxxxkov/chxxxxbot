"""Phase 1.6: Add audio/video file types to FileType enum.

This migration adds new file types for Phase 1.6 multimodal support:
- AUDIO: Audio files (MP3, FLAC, WAV, M4A, etc.)
- VOICE: Voice messages (OGG/OPUS format from Telegram)
- VIDEO: Video files (MP4, MOV, AVI, etc.)

These types enable transcribe_audio tool and universal media architecture.

Revision ID: 006
Revises: 005
Create Date: 2026-01-10 12:30:00.000000

"""
# pylint: disable=invalid-name
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add audio/video types to FileType enum.

    PostgreSQL allows adding new enum values with ALTER TYPE ... ADD VALUE.
    Each ADD VALUE must be a separate statement and cannot run in a transaction,
    so we use op.execute() with autocommit.
    """
    # Add AUDIO type
    op.execute("ALTER TYPE filetype ADD VALUE IF NOT EXISTS 'audio'")

    # Add VOICE type
    op.execute("ALTER TYPE filetype ADD VALUE IF NOT EXISTS 'voice'")

    # Add VIDEO type
    op.execute("ALTER TYPE filetype ADD VALUE IF NOT EXISTS 'video'")


def downgrade() -> None:
    """Downgrade schema: remove audio/video types.

    WARNING: PostgreSQL does NOT support removing enum values without
    recreating the entire enum type. This would require:
    1. Create new enum type without audio/video/voice
    2. Convert column to text
    3. Drop old enum
    4. Rename new enum
    5. Convert column back to enum

    This is complex and risky for production data. Instead, we leave
    the enum values in place. They will simply be unused if downgraded.

    If you MUST remove them, manually recreate the enum type.
    """
    # Cannot remove enum values in PostgreSQL without recreating type
    # Leaving as no-op for safety
    pass
