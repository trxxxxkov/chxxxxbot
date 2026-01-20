"""Unit tests for MessageNormalizer.

Tests the normalizer's ability to convert Telegram messages into
ProcessedMessage objects with all I/O mocked.
"""

from datetime import datetime
from datetime import timezone
from io import BytesIO
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import ProcessedMessage
from telegram.pipeline.normalizer import MessageNormalizer


@pytest.fixture
def normalizer() -> MessageNormalizer:
    """Create a fresh normalizer instance."""
    return MessageNormalizer()


@pytest.fixture
def mock_message() -> MagicMock:
    """Create a basic mock Telegram message."""
    message = MagicMock()
    message.message_id = 100
    message.chat.id = 123
    message.chat.type = "private"
    message.chat.title = None
    message.chat.username = None
    message.chat.first_name = "TestChat"
    message.chat.last_name = None
    message.chat.is_forum = False

    message.from_user.id = 456
    message.from_user.username = "testuser"
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.from_user.is_premium = False

    message.date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    message.message_thread_id = None
    message.is_topic_message = False

    # No media by default
    message.text = None
    message.caption = None
    message.photo = None
    message.document = None
    message.voice = None
    message.audio = None
    message.video = None
    message.video_note = None

    # No reply/forward
    message.reply_to_message = None
    message.forward_origin = None
    message.quote = None

    return message


@pytest.fixture
def mock_bot() -> AsyncMock:
    """Create a mock Bot with download capabilities."""
    bot = AsyncMock()

    # Mock file download
    file_info = MagicMock()
    file_info.file_path = "path/to/file"
    bot.get_file.return_value = file_info
    bot.download_file.return_value = BytesIO(b"test file content")

    return bot


class TestMessageNormalizerTextOnly:
    """Tests for text-only message normalization."""

    @pytest.mark.asyncio
    async def test_normalize_text_message(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """Normalizes simple text message."""
        mock_message.text = "Hello, Claude!"

        result = await normalizer.normalize(mock_message)

        assert isinstance(result, ProcessedMessage)
        assert result.text == "Hello, Claude!"
        assert result.has_media is False
        assert result.has_files is False
        assert result.has_transcript is False
        assert result.metadata.chat_id == 123
        assert result.metadata.user_id == 456

    @pytest.mark.asyncio
    async def test_normalize_caption_as_text(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """Caption is used as text when no plain text."""
        mock_message.caption = "Caption text"

        result = await normalizer.normalize(mock_message)

        assert result.text == "Caption text"

    @pytest.mark.asyncio
    async def test_normalize_empty_message(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """Empty message is normalized."""
        result = await normalizer.normalize(mock_message)

        assert result.text is None
        assert result.has_media is False

    @pytest.mark.asyncio
    async def test_normalize_message_no_user_raises(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """Message without from_user raises ValueError."""
        mock_message.from_user = None

        with pytest.raises(ValueError, match="no from_user"):
            await normalizer.normalize(mock_message)


class TestMessageNormalizerMetadata:
    """Tests for metadata extraction."""

    @pytest.mark.asyncio
    async def test_extract_metadata_basic(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """Extracts basic metadata from message."""
        mock_message.text = "Test"
        mock_message.message_thread_id = 10
        mock_message.is_topic_message = True

        result = await normalizer.normalize(mock_message)

        assert result.metadata.chat_id == 123
        assert result.metadata.user_id == 456
        assert result.metadata.message_id == 100
        assert result.metadata.message_thread_id == 10
        assert result.metadata.chat_type == "private"
        assert result.metadata.is_topic_message is True
        assert result.metadata.username == "testuser"
        assert result.metadata.first_name == "Test"
        assert result.metadata.last_name == "User"
        assert result.metadata.is_premium is False

    @pytest.mark.asyncio
    async def test_extract_metadata_premium_user(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """Extracts premium status from user."""
        mock_message.text = "Test"
        mock_message.from_user.is_premium = True

        result = await normalizer.normalize(mock_message)

        assert result.metadata.is_premium is True


class TestMessageNormalizerReplyContext:
    """Tests for reply context extraction."""

    @pytest.mark.asyncio
    async def test_extract_reply_context(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """Extracts reply context from reply_to_message."""
        mock_message.text = "Reply text"

        # Set up reply
        reply = MagicMock()
        reply.message_id = 99
        reply.text = "Original message"
        reply.caption = None
        reply.from_user = MagicMock()
        reply.from_user.username = "original_user"
        reply.from_user.first_name = "Original"
        reply.from_user.last_name = None
        mock_message.reply_to_message = reply

        result = await normalizer.normalize(mock_message)

        assert result.reply_context is not None
        assert result.reply_context.original_text == "Original message"
        assert result.reply_context.original_sender == "@original_user"
        assert result.reply_context.original_message_id == 99
        assert result.reply_context.is_forward is False
        assert result.reply_context.is_quote is False

    @pytest.mark.asyncio
    async def test_extract_forward_context(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """Extracts forward context from forward_origin."""
        from aiogram import types as aiogram_types

        mock_message.text = "Forwarded text"

        # Create proper MessageOriginUser
        forward_origin = MagicMock(spec=aiogram_types.MessageOriginUser)
        forward_origin.type = "user"
        forward_origin.date = datetime(2025, 1, 15, tzinfo=timezone.utc)
        forward_origin.sender_user = MagicMock()
        forward_origin.sender_user.username = "forwarder"
        forward_origin.sender_user.first_name = "Forward"
        forward_origin.sender_user.last_name = None
        mock_message.forward_origin = forward_origin

        result = await normalizer.normalize(mock_message)

        assert result.reply_context is not None
        assert result.reply_context.is_forward is True
        assert result.reply_context.original_sender == "@forwarder"

    @pytest.mark.asyncio
    async def test_no_reply_context(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
    ) -> None:
        """No reply context when message is standalone."""
        mock_message.text = "Standalone message"

        result = await normalizer.normalize(mock_message)

        assert result.reply_context is None


class TestMessageNormalizerPhoto:
    """Tests for photo processing."""

    @pytest.mark.asyncio
    @patch("telegram.pipeline.normalizer.upload_to_files_api")
    async def test_process_photo(
        self,
        mock_upload: AsyncMock,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Processes photo by uploading to Files API."""
        mock_upload.return_value = "file_photo_123"

        # Set up photo
        photo_size = MagicMock()
        photo_size.file_id = "photo_file_id_123"
        photo_size.file_unique_id = "photo_unique_123"
        photo_size.width = 1920
        photo_size.height = 1080
        photo_size.file_size = 50000
        mock_message.photo = [photo_size]  # List of PhotoSize
        mock_message.caption = "Photo caption"
        mock_message.bot = mock_bot

        result = await normalizer.normalize(mock_message)

        assert result.has_files is True
        assert len(result.files) == 1
        assert result.files[0].claude_file_id == "file_photo_123"
        assert result.files[0].file_type == MediaType.IMAGE
        assert result.files[0].telegram_file_id == "photo_file_id_123"
        assert result.text == "Photo caption"
        mock_upload.assert_called_once()

    @pytest.mark.asyncio
    @patch("telegram.pipeline.normalizer.upload_to_files_api")
    async def test_process_photo_uses_largest_size(
        self,
        mock_upload: AsyncMock,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Uses largest photo size (last in list)."""
        mock_upload.return_value = "file_photo_large"

        # Multiple sizes (Telegram sends multiple)
        small = MagicMock()
        small.file_id = "small_id"
        small.file_unique_id = "small_unique"
        small.width = 320
        small.height = 240
        small.file_size = 5000

        large = MagicMock()
        large.file_id = "large_id"
        large.file_unique_id = "large_unique"
        large.width = 1920
        large.height = 1080
        large.file_size = 50000

        mock_message.photo = [small, large]  # Last is largest
        mock_message.bot = mock_bot

        result = await normalizer.normalize(mock_message)

        assert result.files[0].telegram_file_id == "large_id"


class TestMessageNormalizerDocument:
    """Tests for document processing."""

    @pytest.mark.asyncio
    @patch("telegram.pipeline.normalizer.upload_to_files_api")
    @patch("telegram.pipeline.normalizer.is_pdf_mime", return_value=True)
    @patch("telegram.pipeline.normalizer.is_image_mime", return_value=False)
    @patch(
        "telegram.pipeline.normalizer.detect_mime_type",
        return_value="application/pdf",
    )
    async def test_process_pdf_document(
        self,
        mock_detect: MagicMock,
        mock_is_image: MagicMock,
        mock_is_pdf: MagicMock,
        mock_upload: AsyncMock,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Processes PDF document."""
        mock_upload.return_value = "file_pdf_123"

        document = MagicMock()
        document.file_id = "doc_file_id"
        document.file_unique_id = "doc_unique"
        document.file_name = "document.pdf"
        document.mime_type = "application/pdf"
        document.file_size = 100000
        mock_message.document = document
        mock_message.bot = mock_bot

        result = await normalizer.normalize(mock_message)

        assert result.has_files is True
        assert result.files[0].file_type == MediaType.PDF
        assert result.files[0].filename == "document.pdf"

    @pytest.mark.asyncio
    @patch("telegram.pipeline.normalizer.upload_to_files_api")
    @patch("telegram.pipeline.normalizer.is_pdf_mime", return_value=False)
    @patch("telegram.pipeline.normalizer.is_image_mime", return_value=False)
    @patch(
        "telegram.pipeline.normalizer.detect_mime_type",
        return_value="text/plain",
    )
    async def test_process_text_document(
        self,
        mock_detect: MagicMock,
        mock_is_image: MagicMock,
        mock_is_pdf: MagicMock,
        mock_upload: AsyncMock,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Processes text document."""
        mock_upload.return_value = "file_txt_123"

        document = MagicMock()
        document.file_id = "txt_file_id"
        document.file_unique_id = "txt_unique"
        document.file_name = "notes.txt"
        document.mime_type = "text/plain"
        document.file_size = 1000
        mock_message.document = document
        mock_message.bot = mock_bot

        result = await normalizer.normalize(mock_message)

        assert result.files[0].file_type == MediaType.DOCUMENT


class TestMessageNormalizerVoice:
    """Tests for voice message processing."""

    @pytest.mark.asyncio
    async def test_process_voice_transcribes(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Processes voice message with transcription."""
        # Mock Whisper response
        whisper_response = MagicMock()
        whisper_response.text = "  Hello from voice message  "
        whisper_response.duration = 5.5
        whisper_response.language = "en"

        mock_openai = AsyncMock()
        mock_openai.audio.transcriptions.create.return_value = whisper_response

        # Set up voice
        voice = MagicMock()
        voice.file_id = "voice_file_id"
        voice.duration = 5
        voice.file_size = 10000
        mock_message.voice = voice
        mock_message.bot = mock_bot

        with patch.object(
                normalizer,
                "_get_openai_client",
                return_value=mock_openai,
        ):
            result = await normalizer.normalize(mock_message)

        assert result.has_transcript is True
        assert result.transcript.text == "Hello from voice message"
        assert result.transcript.duration_seconds == 5.5
        assert result.transcript.detected_language == "en"
        assert result.transcript.cost_usd > 0
        assert result.has_files is False

    @pytest.mark.asyncio
    async def test_voice_text_for_db_has_prefix(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Voice message text for DB includes prefix."""
        whisper_response = MagicMock()
        whisper_response.text = "Voice transcript"
        whisper_response.duration = 10.0
        whisper_response.language = "en"

        mock_openai = AsyncMock()
        mock_openai.audio.transcriptions.create.return_value = whisper_response

        voice = MagicMock()
        voice.file_id = "voice_id"
        voice.duration = 10
        voice.file_size = 20000
        mock_message.voice = voice
        mock_message.bot = mock_bot

        with patch.object(
                normalizer,
                "_get_openai_client",
                return_value=mock_openai,
        ):
            result = await normalizer.normalize(mock_message)

        assert result.get_text_for_db(
        ) == "[VOICE MESSAGE - 10s]: Voice transcript"


class TestMessageNormalizerVideoNote:
    """Tests for video note (round video) processing."""

    @pytest.mark.asyncio
    async def test_process_video_note_transcribes(
        self,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Processes video note with transcription."""
        whisper_response = MagicMock()
        whisper_response.text = "Video note message"
        whisper_response.duration = 15.0
        whisper_response.language = "ru"

        mock_openai = AsyncMock()
        mock_openai.audio.transcriptions.create.return_value = whisper_response

        video_note = MagicMock()
        video_note.file_id = "video_note_id"
        video_note.duration = 15
        video_note.file_size = 500000
        mock_message.video_note = video_note
        mock_message.bot = mock_bot

        with patch.object(
                normalizer,
                "_get_openai_client",
                return_value=mock_openai,
        ):
            result = await normalizer.normalize(mock_message)

        assert result.has_transcript is True
        assert result.transcript.text == "Video note message"
        assert result.transcript.detected_language == "ru"


class TestMessageNormalizerAudio:
    """Tests for audio file processing."""

    @pytest.mark.asyncio
    @patch("telegram.pipeline.normalizer.upload_to_files_api")
    @patch(
        "telegram.pipeline.normalizer.detect_mime_type",
        return_value="audio/mpeg",
    )
    async def test_process_audio_uploads_no_transcribe(
        self,
        mock_detect: MagicMock,
        mock_upload: AsyncMock,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Audio files are uploaded, not auto-transcribed."""
        mock_upload.return_value = "file_audio_123"

        audio = MagicMock()
        audio.file_id = "audio_id"
        audio.file_unique_id = "audio_unique"
        audio.file_name = "podcast.mp3"
        audio.mime_type = "audio/mpeg"
        audio.file_size = 5000000
        audio.duration = 300
        audio.performer = "Author"
        audio.title = "Episode 1"
        mock_message.audio = audio
        mock_message.bot = mock_bot

        result = await normalizer.normalize(mock_message)

        assert result.has_files is True
        assert result.has_transcript is False  # Not auto-transcribed
        assert result.files[0].file_type == MediaType.AUDIO
        assert result.files[0].metadata["duration"] == 300
        assert result.files[0].metadata["performer"] == "Author"


class TestMessageNormalizerVideo:
    """Tests for video file processing."""

    @pytest.mark.asyncio
    @patch("telegram.pipeline.normalizer.upload_to_files_api")
    @patch(
        "telegram.pipeline.normalizer.detect_mime_type",
        return_value="video/mp4",
    )
    async def test_process_video_uploads_no_transcribe(
        self,
        mock_detect: MagicMock,
        mock_upload: AsyncMock,
        normalizer: MessageNormalizer,
        mock_message: MagicMock,
        mock_bot: AsyncMock,
    ) -> None:
        """Video files are uploaded, not auto-transcribed."""
        mock_upload.return_value = "file_video_123"

        video = MagicMock()
        video.file_id = "video_id"
        video.file_unique_id = "video_unique"
        video.file_name = "recording.mp4"
        video.mime_type = "video/mp4"
        video.file_size = 10000000
        video.duration = 60
        video.width = 1920
        video.height = 1080
        mock_message.video = video
        mock_message.bot = mock_bot

        result = await normalizer.normalize(mock_message)

        assert result.has_files is True
        assert result.has_transcript is False  # Not auto-transcribed
        assert result.files[0].file_type == MediaType.VIDEO
        assert result.files[0].metadata["width"] == 1920
        assert result.files[0].metadata["height"] == 1080


class TestGetNormalizer:
    """Tests for singleton accessor."""

    def test_get_normalizer_returns_singleton(self) -> None:
        """get_normalizer returns same instance."""
        from telegram.pipeline.normalizer import get_normalizer

        n1 = get_normalizer()
        n2 = get_normalizer()

        assert n1 is n2

    def test_get_normalizer_returns_normalizer_type(self) -> None:
        """get_normalizer returns MessageNormalizer."""
        from telegram.pipeline.normalizer import get_normalizer

        n = get_normalizer()

        assert isinstance(n, MessageNormalizer)
