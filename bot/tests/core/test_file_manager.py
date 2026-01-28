"""Tests for unified FileManager.

Tests the FileManager.get_file_content() unified file retrieval:
- exec_* files from Redis exec_cache
- file_* files from DB -> Telegram or Files API
- telegram_file_id direct download
- Error handling for missing files
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


class TestGetFileContentFromExecCache:
    """Tests for get_file_content() with exec_* prefix."""

    @pytest.mark.asyncio
    async def test_get_file_content_from_exec_cache_success(self):
        """Test successful retrieval from exec_cache."""
        from core.file_manager import FileManager

        mock_meta = {
            "filename": "output.png",
            "mime_type": "image/png",
            "context": "Generated chart",
            "preview": "Image 1024x768",
        }
        mock_content = b"fake_image_bytes"

        with patch("cache.exec_cache.get_exec_meta",
                   new_callable=AsyncMock) as mock_get_meta, \
             patch("cache.exec_cache.get_exec_file",
                   new_callable=AsyncMock) as mock_get_file:

            mock_get_meta.return_value = mock_meta
            mock_get_file.return_value = mock_content

            manager = FileManager(bot=MagicMock(), session=AsyncMock())
            content, metadata = await manager.get_file_content("exec_abc123")

            assert content == mock_content
            assert metadata["filename"] == "output.png"
            assert metadata["mime_type"] == "image/png"
            assert metadata["source"] == "exec_cache"
            assert metadata["context"] == "Generated chart"
            assert metadata["preview"] == "Image 1024x768"
            assert metadata["file_size"] == len(mock_content)

    @pytest.mark.asyncio
    async def test_get_file_content_exec_not_found_metadata(self):
        """Test FileNotFoundError when exec_cache metadata missing."""
        from core.file_manager import FileManager

        with patch("cache.exec_cache.get_exec_meta",
                   new_callable=AsyncMock) as mock_get_meta:
            mock_get_meta.return_value = None

            manager = FileManager(bot=MagicMock(), session=AsyncMock())

            with pytest.raises(FileNotFoundError) as exc_info:
                await manager.get_file_content("exec_notfound")

            assert "not found or expired" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_file_content_exec_not_found_content(self):
        """Test FileNotFoundError when exec_cache content missing."""
        from core.file_manager import FileManager

        with patch("cache.exec_cache.get_exec_meta",
                   new_callable=AsyncMock) as mock_get_meta, \
             patch("cache.exec_cache.get_exec_file",
                   new_callable=AsyncMock) as mock_get_file:

            mock_get_meta.return_value = {"filename": "test.txt"}
            mock_get_file.return_value = None

            manager = FileManager(bot=MagicMock(), session=AsyncMock())

            with pytest.raises(FileNotFoundError) as exc_info:
                await manager.get_file_content("exec_expired")

            assert "content not found" in str(exc_info.value)


class TestGetFileContentFromTelegram:
    """Tests for get_file_content() with telegram downloads."""

    @pytest.mark.asyncio
    async def test_get_file_content_from_telegram_via_db(self):
        """Test retrieval via telegram_file_id found in database."""
        from core.file_manager import FileManager

        # Mock database record
        mock_user_file = MagicMock()
        mock_user_file.filename = "photo.jpg"
        mock_user_file.mime_type = "image/jpeg"
        mock_user_file.file_size = 50000
        mock_user_file.claude_file_id = "file_abc123"
        mock_user_file.telegram_file_id = "AgACAgIAAxkB..."
        mock_user_file.file_type = MagicMock(value="image")

        mock_repo = MagicMock()
        mock_repo.get_by_telegram_file_id = AsyncMock(
            return_value=mock_user_file)

        # Mock bot download
        mock_bot = MagicMock()
        mock_file_info = MagicMock()
        mock_file_info.file_path = "photos/file_123.jpg"
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)

        mock_bytes_io = MagicMock()
        mock_bytes_io.read.return_value = b"jpeg_image_bytes"
        mock_bot.download_file = AsyncMock(return_value=mock_bytes_io)

        with patch("db.repositories.user_file_repository.UserFileRepository",
                   return_value=mock_repo), \
             patch("cache.file_cache.get_cached_file",
                   new_callable=AsyncMock, return_value=None), \
             patch("cache.file_cache.cache_file",
                   new_callable=AsyncMock):

            manager = FileManager(bot=mock_bot, session=AsyncMock())
            content, metadata = await manager.get_file_content("AgACAgIAAxkB..."
                                                              )

            assert content == b"jpeg_image_bytes"
            assert metadata["filename"] == "photo.jpg"
            assert metadata["mime_type"] == "image/jpeg"
            assert metadata["source"] == "telegram"
            assert metadata["claude_file_id"] == "file_abc123"

    @pytest.mark.asyncio
    async def test_get_file_content_direct_telegram_download(self):
        """Test direct Telegram download when not in database."""
        from core.file_manager import FileManager

        mock_repo = MagicMock()
        mock_repo.get_by_telegram_file_id = AsyncMock(return_value=None)

        # Mock bot download
        mock_bot = MagicMock()
        mock_file_info = MagicMock()
        mock_file_info.file_path = "documents/file_456.pdf"
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)

        mock_bytes_io = MagicMock()
        mock_bytes_io.read.return_value = b"pdf_content"
        mock_bot.download_file = AsyncMock(return_value=mock_bytes_io)

        with patch("db.repositories.user_file_repository.UserFileRepository",
                   return_value=mock_repo), \
             patch("cache.file_cache.get_cached_file",
                   new_callable=AsyncMock, return_value=None), \
             patch("cache.file_cache.cache_file",
                   new_callable=AsyncMock):

            manager = FileManager(bot=mock_bot, session=AsyncMock())
            content, metadata = await manager.get_file_content("BQACAgIAAxkD..."
                                                              )

            assert content == b"pdf_content"
            assert metadata["source"] == "telegram"
            assert metadata["claude_file_id"] is None


class TestGetFileContentFromFilesAPI:
    """Tests for get_file_content() with file_* prefix (Files API)."""

    @pytest.mark.asyncio
    async def test_get_file_content_from_files_api(self):
        """Test retrieval from Files API when no telegram_file_id."""
        from core.file_manager import FileManager

        # Mock database record without telegram_file_id
        mock_user_file = MagicMock()
        mock_user_file.filename = "document.pdf"
        mock_user_file.mime_type = "application/pdf"
        mock_user_file.file_size = 100000
        mock_user_file.claude_file_id = "file_xyz789"
        mock_user_file.telegram_file_id = None  # No Telegram backup
        mock_user_file.file_type = MagicMock(value="document")

        mock_repo = MagicMock()
        mock_repo.get_by_claude_file_id = AsyncMock(return_value=mock_user_file)

        # Mock Files API download
        mock_client = MagicMock()
        mock_client.beta.files.download.return_value = MagicMock(
            content=b"pdf_from_files_api")

        with patch("db.repositories.user_file_repository.UserFileRepository",
                   return_value=mock_repo), \
             patch("core.clients.get_anthropic_client",
                   return_value=mock_client):

            manager = FileManager(bot=MagicMock(), session=AsyncMock())
            content, metadata = await manager.get_file_content("file_xyz789")

            assert content == b"pdf_from_files_api"
            assert metadata["filename"] == "document.pdf"
            assert metadata["mime_type"] == "application/pdf"
            assert metadata["source"] == "files_api"
            assert metadata["claude_file_id"] == "file_xyz789"

    @pytest.mark.asyncio
    async def test_get_file_content_file_not_in_db(self):
        """Test FileNotFoundError when file_* not in database."""
        from core.file_manager import FileManager

        mock_repo = MagicMock()
        mock_repo.get_by_claude_file_id = AsyncMock(return_value=None)

        with patch("db.repositories.user_file_repository.UserFileRepository",
                   return_value=mock_repo):

            manager = FileManager(bot=MagicMock(), session=AsyncMock())

            with pytest.raises(FileNotFoundError) as exc_info:
                await manager.get_file_content("file_notfound")

            assert "not found in database" in str(exc_info.value)


class TestGetFileContentNotFound:
    """Tests for get_file_content() error handling."""

    @pytest.mark.asyncio
    async def test_get_file_content_not_found_anywhere(self):
        """Test FileNotFoundError when file not found in any source."""
        from aiogram.exceptions import TelegramAPIError
        from core.file_manager import FileManager

        mock_repo = MagicMock()
        mock_repo.get_by_telegram_file_id = AsyncMock(return_value=None)

        mock_bot = MagicMock()
        mock_bot.get_file = AsyncMock(side_effect=TelegramAPIError(
            method=MagicMock(), message="Bad Request: file not found"))

        with patch("db.repositories.user_file_repository.UserFileRepository",
                   return_value=mock_repo):

            manager = FileManager(bot=mock_bot, session=AsyncMock())

            with pytest.raises(FileNotFoundError) as exc_info:
                await manager.get_file_content("nonexistent_file_id")

            assert "not found" in str(exc_info.value)


class TestGetFileContentCaching:
    """Tests for get_file_content() cache behavior."""

    @pytest.mark.asyncio
    async def test_get_file_content_uses_cache(self):
        """Test that cache is checked before Telegram download.

        When file is found in cache (and not in DB), the content comes
        from cache but metadata is generic since we don't have DB record.
        """
        from core.file_manager import FileManager

        mock_repo = MagicMock()
        mock_repo.get_by_telegram_file_id = AsyncMock(return_value=None)

        mock_bot = MagicMock()

        cached_content = b"cached_file_content"

        # Patch at the module level where get_cached_file is imported
        with patch("db.repositories.user_file_repository.UserFileRepository",
                   return_value=mock_repo), \
             patch("core.file_manager.get_cached_file",
                   new_callable=AsyncMock,
                   return_value=cached_content):

            manager = FileManager(bot=mock_bot, session=AsyncMock())
            content, metadata = await manager.get_file_content(
                "AgACAgIAAxkB...",
                use_cache=True,
            )

            assert content == cached_content
            assert metadata["source"] == "telegram"
            # Bot download should not be called when cache hit
            mock_bot.get_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_file_content_bypass_cache(self):
        """Test that cache can be bypassed."""
        from core.file_manager import FileManager

        mock_repo = MagicMock()
        mock_repo.get_by_telegram_file_id = AsyncMock(return_value=None)

        mock_bot = MagicMock()
        mock_file_info = MagicMock()
        mock_file_info.file_path = "photos/file.jpg"
        mock_bot.get_file = AsyncMock(return_value=mock_file_info)

        mock_bytes_io = MagicMock()
        mock_bytes_io.read.return_value = b"fresh_content"
        mock_bot.download_file = AsyncMock(return_value=mock_bytes_io)

        with patch("db.repositories.user_file_repository.UserFileRepository",
                   return_value=mock_repo), \
             patch("cache.file_cache.get_cached_file",
                   new_callable=AsyncMock) as mock_cache, \
             patch("cache.file_cache.cache_file",
                   new_callable=AsyncMock):

            manager = FileManager(bot=mock_bot, session=AsyncMock())
            content, metadata = await manager.get_file_content(
                "AgACAgIAAxkB...",
                use_cache=False,
            )

            assert content == b"fresh_content"
            # Cache should not be checked
            mock_cache.assert_not_called()
