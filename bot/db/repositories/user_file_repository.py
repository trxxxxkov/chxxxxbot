"""Repository for UserFile model (Phase 1.5: Files API).

This module provides CRUD operations for user_files table.

NO __init__.py - use direct import:
    from db.repositories.user_file_repository import UserFileRepository
"""

from datetime import datetime
from typing import Optional

from db.models.user_file import FileSource
from db.models.user_file import FileType
from db.models.user_file import UserFile
from db.repositories.base import BaseRepository
from sqlalchemy import and_
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class UserFileRepository(BaseRepository[UserFile]):
    """Repository for UserFile model.

    Provides CRUD operations and queries for user_files table.
    Handles file uploads, expiration queries, and cleanup.
    """

    def __init__(self, session: AsyncSession):
        """Initialize repository with database session.

        Args:
            session: Async SQLAlchemy session.
        """
        super().__init__(session, UserFile)

    # pylint: disable=arguments-differ
    async def create(
        self,
        message_id: int,
        claude_file_id: str,
        filename: str,
        file_type: FileType,
        mime_type: str,
        file_size: int,
        expires_at: datetime,
        source: FileSource,
        telegram_file_id: Optional[str] = None,
        telegram_file_unique_id: Optional[str] = None,
        file_metadata: Optional[dict] = None,
    ) -> UserFile:
        """Create new user file record.

        Args:
            message_id: Message ID that contains this file.
            claude_file_id: Files API file ID (unique).
            filename: Original filename.
            file_type: Type classification (image/pdf/document/generated).
            mime_type: MIME type (e.g., 'image/jpeg').
            file_size: Size in bytes.
            expires_at: Expiration timestamp.
            source: Who created the file (user/assistant).
            telegram_file_id: Telegram file ID (for user uploads).
            telegram_file_unique_id: Telegram unique file ID.
            file_metadata: Optional metadata (width, height, page_count, etc.).

        Returns:
            Created UserFile instance.

        Examples:
            >>> file = await user_file_repo.create(
            ...     message_id=123456,
            ...     claude_file_id="file_abc123...",
            ...     filename="photo.jpg",
            ...     file_type=FileType.IMAGE,
            ...     mime_type="image/jpeg",
            ...     file_size=150000,
            ...     expires_at=datetime.now() + timedelta(hours=24),
            ...     source=FileSource.USER,
            ...     telegram_file_id="AgACAgIAAxkB...",
            ...     metadata={"width": 1920, "height": 1080}
            ... )
        """
        file = UserFile(
            message_id=message_id,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            claude_file_id=claude_file_id,
            filename=filename,
            file_type=file_type,
            mime_type=mime_type,
            file_size=file_size,
            expires_at=expires_at,
            source=source,
            file_metadata=file_metadata or {},
        )

        self.session.add(file)
        await self.session.flush()

        return file

    async def get_by_claude_file_id(self,
                                    claude_file_id: str) -> Optional[UserFile]:
        """Get file by Claude Files API ID.

        Args:
            claude_file_id: Files API file ID.

        Returns:
            UserFile instance or None if not found.

        Examples:
            >>> file = await user_file_repo.get_by_claude_file_id("file_abc...")
            >>> if file:
            ...     print(f"Found: {file.filename}")
        """
        stmt = select(UserFile).where(UserFile.claude_file_id == claude_file_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_message_id(self, message_id: int) -> list[UserFile]:
        """Get all files for a message.

        Args:
            message_id: Message ID.

        Returns:
            List of UserFile instances (may be empty).

        Examples:
            >>> files = await user_file_repo.get_by_message_id(123456)
            >>> for file in files:
            ...     print(f"File: {file.filename}")
        """
        stmt = select(UserFile).where(
            UserFile.message_id == message_id).order_by(
                UserFile.uploaded_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_thread_id(self, thread_id: int) -> list[UserFile]:
        """Get all files for a thread (via messages).

        Joins with messages table to find files for all messages in thread.
        Used for generating "Available files" section in system prompt.

        Args:
            thread_id: Thread ID.

        Returns:
            List of UserFile instances (may be empty).

        Examples:
            >>> files = await user_file_repo.get_by_thread_id(42)
            >>> for file in files:
            ...     print(f"{file.filename} (uploaded {file.uploaded_at})")
        """
        # Import here to avoid circular dependency
        from db.models.message import \
            Message  # pylint: disable=import-outside-toplevel
        from utils.structured_logging import \
            get_logger  # pylint: disable=import-outside-toplevel

        logger = get_logger(__name__)
        logger.debug("user_file_repo.get_by_thread_id.start",
                     thread_id=thread_id)

        stmt = (select(UserFile).join(
            Message, UserFile.message_id == Message.message_id).where(
                Message.thread_id == thread_id).order_by(
                    UserFile.uploaded_at.desc()))

        logger.debug("user_file_repo.get_by_thread_id.executing",
                     thread_id=thread_id)
        result = await self.session.execute(stmt)

        logger.debug("user_file_repo.get_by_thread_id.extracting",
                     thread_id=thread_id)
        files = list(result.scalars().all())

        logger.debug("user_file_repo.get_by_thread_id.complete",
                     thread_id=thread_id,
                     file_count=len(files))

        return files

    async def get_expired_files(self) -> list[UserFile]:
        """Get all expired files (expires_at < now).

        Used by cleanup cron job to delete expired files.

        Returns:
            List of expired UserFile instances (may be empty).

        Examples:
            >>> expired = await user_file_repo.get_expired_files()
            >>> print(f"Found {len(expired)} expired files")
        """
        stmt = select(UserFile).where(
            UserFile.expires_at < datetime.utcnow()).order_by(
                UserFile.expires_at.asc())

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_file_type(self,
                               file_type: FileType,
                               limit: int = 100) -> list[UserFile]:
        """Get files by type.

        Args:
            file_type: Type to filter (IMAGE, PDF, DOCUMENT, GENERATED).
            limit: Maximum number of files to return.

        Returns:
            List of UserFile instances (may be empty).

        Examples:
            >>> images = await user_file_repo.get_by_file_type(FileType.IMAGE)
            >>> pdfs = await user_file_repo.get_by_file_type(FileType.PDF)
        """
        stmt = select(UserFile).where(UserFile.file_type == file_type).order_by(
            UserFile.uploaded_at.desc()).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent_files(self,
                               source: Optional[FileSource] = None,
                               limit: int = 50) -> list[UserFile]:
        """Get recent files, optionally filtered by source.

        Args:
            source: Optional source filter (USER, ASSISTANT).
            limit: Maximum number of files to return.

        Returns:
            List of UserFile instances (may be empty).

        Examples:
            >>> recent = await user_file_repo.get_recent_files(limit=10)
            >>> user_files = await user_file_repo.get_recent_files(
            ...     source=FileSource.USER, limit=20
            ... )
        """
        conditions = []
        if source:
            conditions.append(UserFile.source == source)

        stmt = select(UserFile)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.order_by(UserFile.uploaded_at.desc()).limit(limit)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_files(self) -> int:
        """Count total number of files.

        Returns:
            Total file count.

        Examples:
            >>> total = await user_file_repo.count_files()
            >>> print(f"Total files: {total}")
        """
        return await self.count()

    async def get_total_size(self) -> int:
        """Calculate total size of all files in bytes.

        Returns:
            Total size in bytes.

        Examples:
            >>> total_bytes = await user_file_repo.get_total_size()
            >>> total_mb = total_bytes / (1024 * 1024)
            >>> print(f"Total: {total_mb:.2f} MB")
        """
        from sqlalchemy import func  # pylint: disable=import-outside-toplevel

        stmt = select(func.sum(UserFile.file_size))
        result = await self.session.execute(stmt)
        total = result.scalar_one_or_none()

        return total or 0
