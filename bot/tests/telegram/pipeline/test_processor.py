"""Unit tests for pipeline processor.

Tests the processor's ability to bridge between ProcessedMessage
and the existing Claude handler.
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
from telegram.pipeline.models import TranscriptInfo
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


class TestMediaTypeConversion:
    """Tests for media type conversion functions."""

    def test_convert_voice_type(self) -> None:
        """Converts VOICE to old MediaType."""
        from telegram.media_processor import MediaType as OldMediaType
        from telegram.pipeline.processor import _media_type_to_old

        result = _media_type_to_old(MediaType.VOICE)
        assert result == OldMediaType.VOICE

    def test_convert_image_type(self) -> None:
        """Converts IMAGE to old MediaType."""
        from telegram.media_processor import MediaType as OldMediaType
        from telegram.pipeline.processor import _media_type_to_old

        result = _media_type_to_old(MediaType.IMAGE)
        assert result == OldMediaType.IMAGE

    def test_convert_pdf_to_document(self) -> None:
        """Converts PDF to DOCUMENT (old type)."""
        from telegram.media_processor import MediaType as OldMediaType
        from telegram.pipeline.processor import _media_type_to_old

        result = _media_type_to_old(MediaType.PDF)
        assert result == OldMediaType.DOCUMENT


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


class TestConvertToMediaContent:
    """Tests for ProcessedMessage to MediaContent conversion."""

    def test_convert_transcript(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Converts message with transcript."""
        from telegram.pipeline.processor import _convert_to_media_content

        # Set up voice message
        mock_message.voice = MagicMock()
        mock_message.voice.duration = 5

        transcript = TranscriptInfo(
            text="Hello from voice",
            duration_seconds=5.0,
            detected_language="en",
            cost_usd=0.001,
        )

        processed = ProcessedMessage(
            text=None,
            metadata=sample_metadata,
            original_message=mock_message,
            transcript=transcript,
        )

        result = _convert_to_media_content(processed)

        assert result is not None
        assert result.text_content == "Hello from voice"
        assert result.file_id is None
        assert result.metadata["duration"] == 5
        assert result.metadata["cost_usd"] == 0.001

    def test_convert_file(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Converts message with uploaded file."""
        from telegram.pipeline.processor import _convert_to_media_content

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

        result = _convert_to_media_content(processed)

        assert result is not None
        assert result.file_id == "file_123"
        assert result.text_content is None
        assert result.metadata["filename"] == "photo.jpg"

    def test_convert_text_only(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Converts text-only message (returns None)."""
        from telegram.pipeline.processor import _convert_to_media_content

        processed = ProcessedMessage(
            text="Just text",
            metadata=sample_metadata,
            original_message=mock_message,
        )

        result = _convert_to_media_content(processed)

        assert result is None


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
    async def test_process_batch_calls_legacy(
        self,
        mock_get_session: MagicMock,
        mock_legacy_process: AsyncMock,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Batch processing calls legacy handler."""
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

        # Verify legacy handler was called
        mock_legacy_process.assert_called_once()
        args = mock_legacy_process.call_args[0]
        assert args[0] == 1  # thread_id
        assert len(args[1]) == 1  # messages

    @pytest.mark.asyncio
    async def test_process_batch_empty(self) -> None:
        """Empty batch is handled gracefully."""
        from telegram.pipeline.processor import process_batch

        # Should not raise
        await process_batch(thread_id=1, messages=[])
