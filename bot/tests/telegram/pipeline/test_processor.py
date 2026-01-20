"""Unit tests for pipeline processor.

Tests the processor's ability to save files and delegate to Claude handler.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import MessageMetadata
from telegram.pipeline.models import ProcessedMessage
from telegram.pipeline.models import UploadedFile


@pytest.fixture
def sample_metadata() -> MessageMetadata:
    """Create sample MessageMetadata."""
    return MessageMetadata(
        chat_id=123,
        user_id=456,
        message_id=100,
        message_thread_id=None,
        chat_type="private",
        date=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_message() -> MagicMock:
    """Create mock aiogram message."""
    msg = MagicMock()
    msg.message_id = 100
    msg.voice = None
    msg.video_note = None
    msg.audio = None
    msg.video = None
    msg.photo = None
    msg.document = None
    return msg


class TestMediaTypeToFileType:
    """Tests for database FileType conversion."""

    def test_convert_image(self) -> None:
        """Converts IMAGE to DbFileType."""
        from db.models.user_file import FileType as DbFileType
        from telegram.pipeline.processor import _media_type_to_file_type

        result = _media_type_to_file_type(MediaType.IMAGE)
        assert result == DbFileType.IMAGE

    def test_convert_pdf(self) -> None:
        """Converts PDF to DbFileType."""
        from db.models.user_file import FileType as DbFileType
        from telegram.pipeline.processor import _media_type_to_file_type

        result = _media_type_to_file_type(MediaType.PDF)
        assert result == DbFileType.PDF

    def test_convert_voice(self) -> None:
        """Converts VOICE to DbFileType."""
        from db.models.user_file import FileType as DbFileType
        from telegram.pipeline.processor import _media_type_to_file_type

        result = _media_type_to_file_type(MediaType.VOICE)
        assert result == DbFileType.VOICE


class TestProcessBatch:
    """Tests for batch processing."""

    @pytest.mark.asyncio
    @patch("telegram.handlers.claude._process_message_batch")
    @patch("telegram.pipeline.processor.get_session")
    async def test_process_batch_saves_files(
        self,
        mock_get_session: MagicMock,
        mock_legacy_process: AsyncMock,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Batch processing saves files to database."""
        from telegram.pipeline.processor import process_batch

        # Set up session context manager
        mock_session = AsyncMock()
        mock_file_repo = MagicMock()
        mock_file_repo.create = AsyncMock()

        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_session)
        mock_context.__aexit__ = AsyncMock(return_value=None)
        mock_get_session.return_value = mock_context

        # Create message with file
        file = UploadedFile(
            claude_file_id="file_123",
            telegram_file_id="tg_123",
            telegram_file_unique_id="unique_123",
            file_type=MediaType.IMAGE,
            filename="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=1024,
        )

        processed = ProcessedMessage(
            text="Caption",
            metadata=sample_metadata,
            original_message=mock_message,
            files=[file],
        )

        # Patch UserFileRepository
        with patch("telegram.pipeline.processor.UserFileRepository"
                  ) as mock_repo_class:
            mock_repo_class.return_value = mock_file_repo

            await process_batch(thread_id=1, messages=[processed])

            # Verify file was saved
            mock_file_repo.create.assert_called_once()
            call_kwargs = mock_file_repo.create.call_args[1]
            assert call_kwargs["claude_file_id"] == "file_123"
            assert call_kwargs["filename"] == "photo.jpg"

    @pytest.mark.asyncio
    @patch("telegram.handlers.claude._process_message_batch")
    @patch("telegram.pipeline.processor.get_session")
    async def test_process_batch_calls_handler(
        self,
        mock_get_session: MagicMock,
        mock_handler_process: AsyncMock,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Batch processing calls Claude handler with ProcessedMessage."""
        from telegram.pipeline.processor import process_batch

        # Set up session
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_context.__aexit__ = AsyncMock(return_value=None)
        mock_get_session.return_value = mock_context

        # Create text message
        processed = ProcessedMessage(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_message,
        )

        with patch("telegram.pipeline.processor.UserFileRepository"):
            await process_batch(thread_id=1, messages=[processed])

        # Verify handler was called with ProcessedMessage list
        mock_handler_process.assert_called_once()
        args = mock_handler_process.call_args[0]
        assert args[0] == 1  # thread_id
        assert len(args[1]) == 1  # messages
        assert isinstance(args[1][0], ProcessedMessage)

    @pytest.mark.asyncio
    async def test_process_batch_empty(self) -> None:
        """Empty batch is handled gracefully."""
        from telegram.pipeline.processor import process_batch

        # Should not raise
        await process_batch(thread_id=1, messages=[])
