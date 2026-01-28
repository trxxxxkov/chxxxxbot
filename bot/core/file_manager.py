"""Unified file manager for all file operations.

This module provides a centralized interface for file handling across the bot:
- Download from Telegram storage
- Download from Claude Files API
- Download from exec_cache (temporary generated files)
- Redis caching (automatic)
- Database metadata queries

NO __init__.py - use direct import:
    from core.file_manager import FileManager
"""

import asyncio
from typing import Any, Optional, TYPE_CHECKING

from cache.file_cache import cache_file
from cache.file_cache import get_cached_file
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class FileManager:
    """Unified file manager for all download and caching operations.

    Provides consistent interface for:
    - Downloading files from Telegram by telegram_file_id
    - Downloading files by claude_file_id (auto-resolves to Telegram)
    - Automatic Redis caching
    - Parallel downloads

    Usage:
        manager = FileManager(bot, session)
        content = await manager.download_by_claude_id(file_id)
        contents = await manager.download_many([file_id1, file_id2])
    """

    def __init__(self, bot: 'Bot', session: 'AsyncSession'):
        """Initialize file manager.

        Args:
            bot: Telegram Bot instance.
            session: Database session for metadata queries.
        """
        self.bot = bot
        self.session = session

    async def download_by_telegram_id(
        self,
        telegram_file_id: str,
        use_cache: bool = True,
    ) -> bytes:
        """Download file from Telegram by telegram_file_id.

        Args:
            telegram_file_id: Telegram file ID.
            use_cache: Check Redis cache first. Defaults to True.

        Returns:
            File content as bytes.

        Raises:
            TelegramAPIError: If download fails.
        """
        # Import here to avoid circular dependencies
        from aiogram.exceptions import \
            TelegramAPIError  # pylint: disable=import-outside-toplevel

        # Check cache first
        if use_cache:
            cached = await get_cached_file(telegram_file_id)
            if cached:
                logger.debug(
                    "file_manager.cache_hit",
                    telegram_file_id=telegram_file_id,
                )
                return cached

        try:
            logger.info(
                "file_manager.downloading",
                telegram_file_id=telegram_file_id,
            )

            # Download from Telegram
            file_info = await self.bot.get_file(telegram_file_id)
            file_bytes_io = await self.bot.download_file(file_info.file_path)
            content = file_bytes_io.read()

            logger.info(
                "file_manager.download_success",
                telegram_file_id=telegram_file_id,
                size_bytes=len(content),
            )

            # Cache for future use
            if use_cache:
                await cache_file(telegram_file_id, content)

            return content

        except TelegramAPIError as e:
            logger.info(
                "file_manager.telegram_download_failed",
                telegram_file_id=telegram_file_id,
                error=str(e),
            )
            raise

    async def download_by_claude_id(
        self,
        claude_file_id: str,
        filename: Optional[str] = None,
        use_cache: bool = True,
    ) -> bytes:
        """Download file by Claude file_id.

        Resolves Claude file_id to telegram_file_id via database,
        then downloads from Telegram storage.

        Args:
            claude_file_id: Claude Files API file ID.
            filename: Optional filename for logging. Defaults to None.
            use_cache: Check Redis cache first. Defaults to True.

        Returns:
            File content as bytes.

        Raises:
            ValueError: If file not found in database.
            TelegramAPIError: If download fails.
        """
        # Import here to avoid circular dependencies
        from db.repositories.user_file_repository import \
            UserFileRepository  # pylint: disable=import-outside-toplevel

        logger.info(
            "file_manager.resolving_claude_id",
            claude_file_id=claude_file_id,
            filename=filename,
        )

        # Get file metadata from database
        repo = UserFileRepository(self.session)
        file_record = await repo.get_by_claude_file_id(claude_file_id)

        if not file_record:
            raise ValueError(f"File not found in database: {claude_file_id}")

        if not file_record.telegram_file_id:
            raise ValueError(
                f"No telegram_file_id for file {claude_file_id} ({filename}). "
                "Cannot download from Telegram.")

        logger.info(
            "file_manager.resolved",
            claude_file_id=claude_file_id,
            telegram_file_id=file_record.telegram_file_id,
            source=file_record.source.value if file_record.source else None,
        )

        return await self.download_by_telegram_id(
            file_record.telegram_file_id,
            use_cache=use_cache,
        )

    async def download_many_by_claude_id(
        self,
        file_infos: list[dict],
        use_cache: bool = True,
    ) -> dict[str, bytes]:
        """Download multiple files in parallel by Claude file_id.

        Two-phase approach to avoid SQLAlchemy concurrent session errors:
        1. Sequential: Resolve all claude_file_ids to telegram_file_ids via DB
        2. Parallel: Download all files from Telegram simultaneously

        Args:
            file_infos: List of dicts with 'file_id' and optional 'name' keys.
            use_cache: Check Redis cache first. Defaults to True.

        Returns:
            Dict mapping filename to content bytes.

        Raises:
            ValueError: If any file not found in database.
            TelegramAPIError: If any download fails.
        """
        if not file_infos:
            return {}

        logger.info(
            "file_manager.downloading_many",
            count=len(file_infos),
        )

        # Import here to avoid circular dependencies
        from db.repositories.user_file_repository import \
            UserFileRepository  # pylint: disable=import-outside-toplevel

        # Phase 1: Sequential DB queries to resolve telegram_file_ids
        # (SQLAlchemy AsyncSession doesn't support concurrent operations)
        repo = UserFileRepository(self.session)
        resolved_files: list[tuple[str, str]] = []  # (name, telegram_file_id)

        for file_info in file_infos:
            claude_file_id = file_info["file_id"]
            name = file_info.get("name", claude_file_id)

            file_record = await repo.get_by_claude_file_id(claude_file_id)

            if not file_record:
                raise ValueError(
                    f"File not found in database: {claude_file_id}")

            if not file_record.telegram_file_id:
                raise ValueError(
                    f"No telegram_file_id for file {claude_file_id} ({name}). "
                    "Cannot download from Telegram.")

            resolved_files.append((name, file_record.telegram_file_id))

        logger.debug(
            "file_manager.resolved_all",
            count=len(resolved_files),
        )

        # Phase 2: Parallel downloads from Telegram
        # (This is safe - only uses Bot API, no DB session)
        async def download_one(name: str,
                               telegram_file_id: str) -> tuple[str, bytes]:
            """Download single file and return (name, content)."""
            content = await self.download_by_telegram_id(
                telegram_file_id,
                use_cache=use_cache,
            )
            return name, content

        results = await asyncio.gather(
            *[download_one(name, tg_id) for name, tg_id in resolved_files],
            return_exceptions=True,
        )

        # Process results
        downloaded = {}
        for result in results:
            if isinstance(result, BaseException):
                raise result
            name, content = result  # type: ignore[misc]
            downloaded[name] = content

        logger.info(
            "file_manager.download_many_success",
            count=len(downloaded),
            total_bytes=sum(len(c) for c in downloaded.values()),
        )

        return downloaded

    async def download_from_files_api(
        self,
        claude_file_id: str,
    ) -> bytes:
        """Download file directly from Claude Files API.

        Use this only for files that don't have telegram_file_id.
        Runs in thread pool to avoid blocking event loop.

        Args:
            claude_file_id: Claude Files API file ID.

        Returns:
            File content as bytes.

        Raises:
            anthropic.NotFoundError: If file not found.
            anthropic.APIError: If API call fails.
        """
        # Import here to avoid circular dependencies
        from core.clients import \
            get_anthropic_client  # pylint: disable=import-outside-toplevel

        def _download_sync() -> bytes:
            """Sync download function for thread pool."""
            client = get_anthropic_client()
            result = client.beta.files.download(file_id=claude_file_id)
            # Result is a binary response, read content
            return result.content

        logger.info(
            "file_manager.files_api_download",
            claude_file_id=claude_file_id,
        )

        content = await asyncio.to_thread(_download_sync)

        logger.info(
            "file_manager.files_api_download_success",
            claude_file_id=claude_file_id,
            size_bytes=len(content),
        )

        return content

    async def get_file_content(
        self,
        file_id: str,
        use_cache: bool = True,
    ) -> tuple[bytes, dict[str, Any]]:
        """Unified file retrieval from any source.

        Routes by file_id prefix:
        - exec_* → exec_cache (temporary generated files)
        - file_* → DB lookup → Telegram or Files API
        - other  → Telegram download (assumes telegram_file_id)

        Args:
            file_id: Any supported file ID format.
            use_cache: Use Redis cache for Telegram files.

        Returns:
            Tuple of (content_bytes, metadata_dict).
            Metadata contains:
            - filename: str
            - mime_type: str
            - file_size: int
            - source: "exec_cache" | "telegram" | "files_api"
            - context: str | None (only for exec_cache)
            - preview: str | None (only for exec_cache)
            - claude_file_id: str | None (only for DB files)

        Raises:
            FileNotFoundError: If file not found in any source.
        """
        logger.info(
            "file_manager.get_file_content",
            file_id=file_id,
            use_cache=use_cache,
        )

        # Route by prefix
        if file_id.startswith("exec_"):
            return await self._get_from_exec_cache(file_id)

        if file_id.startswith("file_"):
            return await self._get_from_db_by_claude_id(file_id, use_cache)

        # Assume telegram_file_id - try DB first, then direct download
        return await self._get_from_db_or_telegram(file_id, use_cache)

    async def _get_from_exec_cache(
        self,
        temp_id: str,
    ) -> tuple[bytes, dict[str, Any]]:
        """Get file from exec_cache (temporary generated files).

        Args:
            temp_id: Temporary file ID (exec_xxx).

        Returns:
            Tuple of (content, metadata).

        Raises:
            FileNotFoundError: If file not found or expired.
        """
        # Import here to avoid circular dependencies
        from cache.exec_cache import \
            get_exec_file  # pylint: disable=import-outside-toplevel
        from cache.exec_cache import \
            get_exec_meta  # pylint: disable=import-outside-toplevel

        metadata = await get_exec_meta(temp_id)
        if not metadata:
            logger.info("file_manager.exec_cache_miss", temp_id=temp_id)
            raise FileNotFoundError(
                f"File '{temp_id}' not found or expired (30 min TTL)")

        content = await get_exec_file(temp_id)
        if not content:
            logger.info("file_manager.exec_cache_content_miss", temp_id=temp_id)
            raise FileNotFoundError(
                f"File '{temp_id}' content not found (may have expired)")

        logger.info(
            "file_manager.exec_cache_hit",
            temp_id=temp_id,
            filename=metadata.get("filename"),
            size_bytes=len(content),
        )

        return content, {
            "filename": metadata.get("filename", "unknown"),
            "mime_type": metadata.get("mime_type", "application/octet-stream"),
            "file_size": len(content),
            "source": "exec_cache",
            "context": metadata.get("context"),
            "preview": metadata.get("preview"),
        }

    async def _get_from_db_by_claude_id(
        self,
        claude_file_id: str,
        use_cache: bool,
    ) -> tuple[bytes, dict[str, Any]]:
        """Get file by Claude file_id from database.

        Args:
            claude_file_id: Claude Files API file ID.
            use_cache: Use Redis cache for Telegram files.

        Returns:
            Tuple of (content, metadata).

        Raises:
            FileNotFoundError: If file not found.
        """
        # Import here to avoid circular dependencies
        from db.repositories.user_file_repository import \
            UserFileRepository  # pylint: disable=import-outside-toplevel

        repo = UserFileRepository(self.session)
        user_file = await repo.get_by_claude_file_id(claude_file_id)

        if not user_file:
            logger.info(
                "file_manager.db_miss",
                claude_file_id=claude_file_id,
            )
            raise FileNotFoundError(
                f"File '{claude_file_id}' not found in database")

        return await self._download_user_file(user_file, use_cache)

    async def _get_from_db_or_telegram(
        self,
        file_id: str,
        use_cache: bool,
    ) -> tuple[bytes, dict[str, Any]]:
        """Get file by telegram_file_id - try DB first, then direct download.

        Args:
            file_id: Telegram file_id or unknown format.
            use_cache: Use Redis cache.

        Returns:
            Tuple of (content, metadata).

        Raises:
            FileNotFoundError: If file not found.
        """
        # Import here to avoid circular dependencies
        from db.repositories.user_file_repository import \
            UserFileRepository  # pylint: disable=import-outside-toplevel

        repo = UserFileRepository(self.session)

        # Try to find by telegram_file_id in database
        user_file = await repo.get_by_telegram_file_id(file_id)

        if user_file:
            return await self._download_user_file(user_file, use_cache)

        # Not in DB - try direct Telegram download
        try:
            content = await self.download_by_telegram_id(
                file_id,
                use_cache=use_cache,
            )
            return content, {
                "filename": "unknown",
                "mime_type": "application/octet-stream",
                "file_size": len(content),
                "source": "telegram",
                "claude_file_id": None,
            }
        except Exception as e:
            logger.info(
                "file_manager.telegram_download_failed",
                file_id=file_id,
                error=str(e),
            )
            raise FileNotFoundError(
                f"File '{file_id}' not found in database or Telegram") from e

    async def _download_user_file(
        self,
        user_file: Any,
        use_cache: bool,
    ) -> tuple[bytes, dict[str, Any]]:
        """Download content for a UserFile record.

        Args:
            user_file: UserFile database record.
            use_cache: Use Redis cache for Telegram files.

        Returns:
            Tuple of (content, metadata).
        """
        metadata = {
            "filename":
                user_file.filename,
            "mime_type":
                user_file.mime_type,
            "file_size":
                user_file.file_size,
            "claude_file_id":
                user_file.claude_file_id,
            "file_type":
                user_file.file_type.value if user_file.file_type else None,
        }

        # Prefer Telegram download if available
        if user_file.telegram_file_id:
            content = await self.download_by_telegram_id(
                user_file.telegram_file_id,
                use_cache=use_cache,
            )
            metadata["source"] = "telegram"
            logger.info(
                "file_manager.downloaded_from_telegram",
                claude_file_id=user_file.claude_file_id,
                telegram_file_id=user_file.telegram_file_id,
                size_bytes=len(content),
            )
            return content, metadata

        # Fallback to Files API
        content = await self.download_from_files_api(user_file.claude_file_id)
        metadata["source"] = "files_api"
        logger.info(
            "file_manager.downloaded_from_files_api",
            claude_file_id=user_file.claude_file_id,
            size_bytes=len(content),
        )
        return content, metadata
