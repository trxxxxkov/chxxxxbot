"""Unified file manager for all file operations.

This module provides a centralized interface for file handling across the bot:
- Download from Telegram storage
- Download from Claude Files API
- Redis caching (automatic)
- Database metadata queries

NO __init__.py - use direct import:
    from core.file_manager import FileManager
"""

import asyncio
from typing import Optional, TYPE_CHECKING

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
