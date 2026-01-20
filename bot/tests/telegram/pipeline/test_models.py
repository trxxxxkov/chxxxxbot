"""Unit tests for pipeline data structures.

Tests all dataclasses and their methods in telegram.pipeline.models.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock

import pytest
from telegram.pipeline.models import _format_size
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import MessageMetadata
from telegram.pipeline.models import ProcessedMessage
from telegram.pipeline.models import ReplyContext
from telegram.pipeline.models import TranscriptInfo
from telegram.pipeline.models import UploadedFile


class TestMediaType:
    """Tests for MediaType enum."""

    def test_media_type_values(self) -> None:
        """MediaType enum has expected values."""
        assert MediaType.VOICE.value == "voice"
        assert MediaType.VIDEO_NOTE.value == "video_note"
        assert MediaType.AUDIO.value == "audio"
        assert MediaType.VIDEO.value == "video"
        assert MediaType.IMAGE.value == "image"
        assert MediaType.DOCUMENT.value == "document"
        assert MediaType.PDF.value == "pdf"

    def test_media_type_is_string(self) -> None:
        """MediaType values are strings."""
        for media_type in MediaType:
            assert isinstance(media_type.value, str)

    def test_all_media_types_count(self) -> None:
        """All expected media types are defined."""
        assert len(MediaType) == 7


class TestTranscriptInfo:
    """Tests for TranscriptInfo dataclass."""

    def test_create_transcript_info(self) -> None:
        """TranscriptInfo can be created with required fields."""
        info = TranscriptInfo(
            text="Hello, world!",
            duration_seconds=5.5,
            detected_language="en",
            cost_usd=0.001,
        )

        assert info.text == "Hello, world!"
        assert info.duration_seconds == 5.5
        assert info.detected_language == "en"
        assert info.cost_usd == 0.001

    def test_transcript_info_with_empty_text(self) -> None:
        """TranscriptInfo accepts empty text."""
        info = TranscriptInfo(
            text="",
            duration_seconds=1.0,
            detected_language="en",
            cost_usd=0.0,
        )

        assert info.text == ""

    def test_transcript_info_with_long_text(self) -> None:
        """TranscriptInfo handles long text."""
        long_text = "a" * 10000
        info = TranscriptInfo(
            text=long_text,
            duration_seconds=300.0,
            detected_language="ru",
            cost_usd=0.03,
        )

        assert len(info.text) == 10000


class TestUploadedFile:
    """Tests for UploadedFile dataclass."""

    def test_create_uploaded_file_minimal(self) -> None:
        """UploadedFile can be created with required fields."""
        file = UploadedFile(
            claude_file_id="file_abc123",
            telegram_file_id="tg_file_xyz",
            telegram_file_unique_id="unique_123",
            file_type=MediaType.IMAGE,
            filename="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=1024,
        )

        assert file.claude_file_id == "file_abc123"
        assert file.telegram_file_id == "tg_file_xyz"
        assert file.telegram_file_unique_id == "unique_123"
        assert file.file_type == MediaType.IMAGE
        assert file.filename == "photo.jpg"
        assert file.mime_type == "image/jpeg"
        assert file.size_bytes == 1024
        assert file.metadata == {}

    def test_create_uploaded_file_with_metadata(self) -> None:
        """UploadedFile accepts metadata dict."""
        file = UploadedFile(
            claude_file_id="file_abc123",
            telegram_file_id="tg_file_xyz",
            telegram_file_unique_id="unique_123",
            file_type=MediaType.IMAGE,
            filename="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=2048,
            metadata={
                "width": 1920,
                "height": 1080
            },
        )

        assert file.metadata == {"width": 1920, "height": 1080}

    def test_uploaded_file_pdf_type(self) -> None:
        """UploadedFile works with PDF type."""
        file = UploadedFile(
            claude_file_id="file_pdf123",
            telegram_file_id="tg_pdf",
            telegram_file_unique_id="unique_pdf",
            file_type=MediaType.PDF,
            filename="document.pdf",
            mime_type="application/pdf",
            size_bytes=50000,
            metadata={"page_count": 10},
        )

        assert file.file_type == MediaType.PDF
        assert file.mime_type == "application/pdf"


class TestReplyContext:
    """Tests for ReplyContext dataclass."""

    def test_create_empty_reply_context(self) -> None:
        """ReplyContext can be created with all defaults."""
        ctx = ReplyContext()

        assert ctx.original_text is None
        assert ctx.original_sender is None
        assert ctx.original_message_id is None
        assert ctx.is_forward is False
        assert ctx.is_quote is False
        assert ctx.quote_text is None

    def test_create_reply_context_full(self) -> None:
        """ReplyContext accepts all fields."""
        ctx = ReplyContext(
            original_text="Original message",
            original_sender="John Doe",
            original_message_id=12345,
            is_forward=False,
            is_quote=True,
            quote_text="quoted part",
        )

        assert ctx.original_text == "Original message"
        assert ctx.original_sender == "John Doe"
        assert ctx.original_message_id == 12345
        assert ctx.is_forward is False
        assert ctx.is_quote is True
        assert ctx.quote_text == "quoted part"

    def test_create_forward_context(self) -> None:
        """ReplyContext can represent forwarded message."""
        ctx = ReplyContext(
            original_text="Forwarded content",
            original_sender="Alice",
            is_forward=True,
        )

        assert ctx.is_forward is True
        assert ctx.original_sender == "Alice"


class TestMessageMetadata:
    """Tests for MessageMetadata dataclass."""

    def test_create_metadata_minimal(self) -> None:
        """MessageMetadata can be created with required fields."""
        now = datetime.now(timezone.utc)
        metadata = MessageMetadata(
            chat_id=123456789,
            user_id=987654321,
            message_id=100,
            message_thread_id=None,
            chat_type="private",
            date=now,
        )

        assert metadata.chat_id == 123456789
        assert metadata.user_id == 987654321
        assert metadata.message_id == 100
        assert metadata.message_thread_id is None
        assert metadata.chat_type == "private"
        assert metadata.date == now
        assert metadata.is_topic_message is False
        assert metadata.username is None
        assert metadata.first_name is None
        assert metadata.last_name is None
        assert metadata.is_premium is False

    def test_create_metadata_full(self) -> None:
        """MessageMetadata accepts all optional fields."""
        now = datetime.now(timezone.utc)
        metadata = MessageMetadata(
            chat_id=123,
            user_id=456,
            message_id=789,
            message_thread_id=10,
            chat_type="supergroup",
            date=now,
            is_topic_message=True,
            username="johndoe",
            first_name="John",
            last_name="Doe",
            is_premium=True,
        )

        assert metadata.message_thread_id == 10
        assert metadata.is_topic_message is True
        assert metadata.username == "johndoe"
        assert metadata.first_name == "John"
        assert metadata.last_name == "Doe"
        assert metadata.is_premium is True


class TestProcessedMessage:
    """Tests for ProcessedMessage dataclass."""

    @pytest.fixture
    def mock_message(self) -> MagicMock:
        """Create a mock aiogram Message."""
        msg = MagicMock()
        msg.message_id = 100
        msg.chat.id = 123
        msg.from_user.id = 456
        return msg

    @pytest.fixture
    def sample_metadata(self) -> MessageMetadata:
        """Create sample MessageMetadata."""
        return MessageMetadata(
            chat_id=123,
            user_id=456,
            message_id=100,
            message_thread_id=None,
            chat_type="private",
            date=datetime.now(timezone.utc),
        )

    def test_create_text_only_message(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """ProcessedMessage can be created for text-only message."""
        pm = ProcessedMessage(
            text="Hello, Claude!",
            metadata=sample_metadata,
            original_message=mock_message,
        )

        assert pm.text == "Hello, Claude!"
        assert pm.files == []
        assert pm.transcript is None
        assert pm.reply_context is None
        assert pm.has_media is False
        assert pm.has_files is False
        assert pm.has_transcript is False

    def test_create_message_with_files(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """ProcessedMessage can be created with files."""
        file = UploadedFile(
            claude_file_id="file_123",
            telegram_file_id="tg_123",
            telegram_file_unique_id="unique_123",
            file_type=MediaType.IMAGE,
            filename="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=1024,
        )

        pm = ProcessedMessage(
            text="Check this image",
            metadata=sample_metadata,
            original_message=mock_message,
            files=[file],
        )

        assert len(pm.files) == 1
        assert pm.has_media is True
        assert pm.has_files is True
        assert pm.has_transcript is False

    def test_create_message_with_transcript(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """ProcessedMessage can be created with transcript."""
        transcript = TranscriptInfo(
            text="Hello from voice",
            duration_seconds=5.0,
            detected_language="en",
            cost_usd=0.001,
        )

        pm = ProcessedMessage(
            text=None,
            metadata=sample_metadata,
            original_message=mock_message,
            transcript=transcript,
        )

        assert pm.transcript is not None
        assert pm.has_media is True
        assert pm.has_files is False
        assert pm.has_transcript is True

    def test_get_text_for_db_text_message(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """get_text_for_db returns text for regular message."""
        pm = ProcessedMessage(
            text="Regular text message",
            metadata=sample_metadata,
            original_message=mock_message,
        )

        assert pm.get_text_for_db() == "Regular text message"

    def test_get_text_for_db_voice_message(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """get_text_for_db adds voice prefix for transcript."""
        transcript = TranscriptInfo(
            text="Voice transcript",
            duration_seconds=12.5,
            detected_language="en",
            cost_usd=0.001,
        )

        pm = ProcessedMessage(
            text=None,
            metadata=sample_metadata,
            original_message=mock_message,
            transcript=transcript,
        )

        assert pm.get_text_for_db() == "[VOICE MESSAGE - 12s]: Voice transcript"

    def test_get_text_for_db_empty_text(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """get_text_for_db returns empty string for None text."""
        pm = ProcessedMessage(
            text=None,
            metadata=sample_metadata,
            original_message=mock_message,
        )

        assert pm.get_text_for_db() == ""

    def test_get_text_for_claude_same_as_db(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """get_text_for_claude returns same as get_text_for_db."""
        pm = ProcessedMessage(
            text="Test message",
            metadata=sample_metadata,
            original_message=mock_message,
        )

        assert pm.get_text_for_claude() == pm.get_text_for_db()

    def test_get_file_mentions_no_files(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """get_file_mentions returns empty for no files."""
        pm = ProcessedMessage(
            text="No files",
            metadata=sample_metadata,
            original_message=mock_message,
        )

        assert pm.get_file_mentions() == ""

    def test_get_file_mentions_single_file(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """get_file_mentions formats single file."""
        file = UploadedFile(
            claude_file_id="file_xyz",
            telegram_file_id="tg_xyz",
            telegram_file_unique_id="unique_xyz",
            file_type=MediaType.IMAGE,
            filename="photo.jpg",
            mime_type="image/jpeg",
            size_bytes=1024,
        )

        pm = ProcessedMessage(
            text="With file",
            metadata=sample_metadata,
            original_message=mock_message,
            files=[file],
        )

        mentions = pm.get_file_mentions()
        assert "Available files:" in mentions
        assert "photo.jpg" in mentions
        assert "image/jpeg" in mentions
        assert "file_xyz" in mentions
        assert "1.0 KB" in mentions

    def test_get_file_mentions_multiple_files(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """get_file_mentions formats multiple files."""
        files = [
            UploadedFile(
                claude_file_id="file_1",
                telegram_file_id="tg_1",
                telegram_file_unique_id="unique_1",
                file_type=MediaType.IMAGE,
                filename="photo1.jpg",
                mime_type="image/jpeg",
                size_bytes=1024,
            ),
            UploadedFile(
                claude_file_id="file_2",
                telegram_file_id="tg_2",
                telegram_file_unique_id="unique_2",
                file_type=MediaType.PDF,
                filename="doc.pdf",
                mime_type="application/pdf",
                size_bytes=50000,
            ),
        ]

        pm = ProcessedMessage(
            text="With files",
            metadata=sample_metadata,
            original_message=mock_message,
            files=files,
        )

        mentions = pm.get_file_mentions()
        assert "photo1.jpg" in mentions
        assert "doc.pdf" in mentions
        assert "file_1" in mentions
        assert "file_2" in mentions

    def test_message_with_reply_context(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """ProcessedMessage can include reply context."""
        reply_ctx = ReplyContext(
            original_text="Original message",
            original_sender="John",
            original_message_id=99,
        )

        pm = ProcessedMessage(
            text="Reply to original",
            metadata=sample_metadata,
            original_message=mock_message,
            reply_context=reply_ctx,
        )

        assert pm.reply_context is not None
        assert pm.reply_context.original_text == "Original message"
        assert pm.reply_context.original_sender == "John"

    def test_transcription_charged_flag(
        self,
        mock_message: MagicMock,
        sample_metadata: MessageMetadata,
    ) -> None:
        """ProcessedMessage tracks transcription charge status."""
        transcript = TranscriptInfo(
            text="Voice",
            duration_seconds=5.0,
            detected_language="en",
            cost_usd=0.001,
        )

        pm = ProcessedMessage(
            text=None,
            metadata=sample_metadata,
            original_message=mock_message,
            transcript=transcript,
            transcription_charged=True,
        )

        assert pm.transcription_charged is True


class TestFormatSize:
    """Tests for _format_size helper function."""

    def test_format_bytes(self) -> None:
        """Format small sizes in bytes."""
        assert _format_size(0) == "0.0 B"
        assert _format_size(512) == "512.0 B"
        assert _format_size(1023) == "1023.0 B"

    def test_format_kilobytes(self) -> None:
        """Format sizes in kilobytes."""
        assert _format_size(1024) == "1.0 KB"
        assert _format_size(1536) == "1.5 KB"
        assert _format_size(10240) == "10.0 KB"

    def test_format_megabytes(self) -> None:
        """Format sizes in megabytes."""
        assert _format_size(1024 * 1024) == "1.0 MB"
        assert _format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_format_gigabytes(self) -> None:
        """Format sizes in gigabytes."""
        assert _format_size(1024 * 1024 * 1024) == "1.0 GB"
        assert _format_size(2 * 1024 * 1024 * 1024) == "2.0 GB"

    def test_format_terabytes(self) -> None:
        """Format sizes in terabytes."""
        assert _format_size(1024 * 1024 * 1024 * 1024) == "1.0 TB"
