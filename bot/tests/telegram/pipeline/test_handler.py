"""Unit tests for unified message handler.

Tests the handler's ability to process all message types through
the unified pipeline.
"""

from datetime import datetime
from datetime import timezone
from io import BytesIO
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_message() -> MagicMock:
    """Create a mock Telegram message."""
    message = MagicMock()
    message.message_id = 100
    message.chat.id = 123
    message.chat.type = "private"
    message.chat.title = None
    message.chat.username = None
    message.chat.first_name = "Test"
    message.chat.last_name = None
    message.chat.is_forum = False

    message.from_user.id = 456
    message.from_user.username = "testuser"
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.from_user.is_premium = False
    message.from_user.is_bot = False
    message.from_user.language_code = "en"
    message.from_user.added_to_attachment_menu = False

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

    # Mock async methods
    message.answer = AsyncMock()

    return message


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    return session


class TestGetContentType:
    """Tests for _get_content_type helper."""

    def test_voice_type(self, mock_message: MagicMock) -> None:
        """Detects voice message type."""
        from telegram.pipeline.handler import _get_content_type

        mock_message.voice = MagicMock()
        assert _get_content_type(mock_message) == "voice"

    def test_video_note_type(self, mock_message: MagicMock) -> None:
        """Detects video note type."""
        from telegram.pipeline.handler import _get_content_type

        mock_message.video_note = MagicMock()
        assert _get_content_type(mock_message) == "video_note"

    def test_audio_type(self, mock_message: MagicMock) -> None:
        """Detects audio type."""
        from telegram.pipeline.handler import _get_content_type

        mock_message.audio = MagicMock()
        assert _get_content_type(mock_message) == "audio"

    def test_video_type(self, mock_message: MagicMock) -> None:
        """Detects video type."""
        from telegram.pipeline.handler import _get_content_type

        mock_message.video = MagicMock()
        assert _get_content_type(mock_message) == "video"

    def test_photo_type(self, mock_message: MagicMock) -> None:
        """Detects photo type."""
        from telegram.pipeline.handler import _get_content_type

        mock_message.photo = [MagicMock()]
        assert _get_content_type(mock_message) == "photo"

    def test_document_type(self, mock_message: MagicMock) -> None:
        """Detects document type."""
        from telegram.pipeline.handler import _get_content_type

        mock_message.document = MagicMock()
        assert _get_content_type(mock_message) == "document"

    def test_text_type(self, mock_message: MagicMock) -> None:
        """Defaults to text type."""
        from telegram.pipeline.handler import _get_content_type

        mock_message.text = "Hello"
        assert _get_content_type(mock_message) == "text"


class TestGetErrorMessage:
    """Tests for _get_error_message helper."""

    def test_error_messages_exist(self) -> None:
        """All content types have error messages."""
        from telegram.pipeline.handler import _get_error_message

        types = [
            "voice", "video_note", "audio", "video", "photo", "document", "text"
        ]
        for content_type in types:
            msg = _get_error_message(content_type)
            assert msg  # Not empty
            assert "try again" in msg.lower()

    def test_unknown_type_fallback(self) -> None:
        """Unknown type gets fallback message."""
        from telegram.pipeline.handler import _get_error_message

        msg = _get_error_message("unknown")
        assert "error occurred" in msg.lower()


class TestGetQueue:
    """Tests for queue singleton."""

    def test_get_queue_returns_same_instance(self) -> None:
        """get_queue returns singleton."""
        from telegram.pipeline.handler import get_queue

        q1 = get_queue()
        q2 = get_queue()
        assert q1 is q2

    def test_get_queue_returns_queue_type(self) -> None:
        """get_queue returns ProcessedMessageQueue."""
        from telegram.pipeline.handler import get_queue
        from telegram.pipeline.queue import ProcessedMessageQueue

        q = get_queue()
        assert isinstance(q, ProcessedMessageQueue)


class TestUnifiedHandler:
    """Tests for the unified message handler."""

    @pytest.mark.asyncio
    @patch("telegram.pipeline.handler.get_normalizer")
    @patch("telegram.pipeline.handler.get_or_create_thread")
    @patch("telegram.pipeline.handler.get_queue")
    async def test_handler_processes_text_message(
        self,
        mock_get_queue: MagicMock,
        mock_get_thread: AsyncMock,
        mock_get_normalizer: MagicMock,
        mock_message: MagicMock,
        mock_session: AsyncMock,
    ) -> None:
        """Handler processes text message through pipeline."""
        from telegram.pipeline.handler import handle_message
        from telegram.pipeline.models import MessageMetadata
        from telegram.pipeline.models import ProcessedMessage

        # Set up message
        mock_message.text = "Hello, Claude!"

        # Set up normalizer
        metadata = MessageMetadata(
            chat_id=123,
            user_id=456,
            message_id=100,
            message_thread_id=None,
            chat_type="private",
            date=mock_message.date,
        )
        processed = ProcessedMessage(
            text="Hello, Claude!",
            metadata=metadata,
            original_message=mock_message,
        )
        normalizer = MagicMock()
        normalizer.normalize = AsyncMock(return_value=processed)
        mock_get_normalizer.return_value = normalizer

        # Set up thread
        thread = MagicMock()
        thread.id = 1
        mock_get_thread.return_value = thread

        # Set up queue
        queue = MagicMock()
        queue.add = AsyncMock()
        mock_get_queue.return_value = queue

        # Call handler
        await handle_message(mock_message, mock_session)

        # Verify
        normalizer.normalize.assert_called_once_with(mock_message)
        mock_get_thread.assert_called_once()
        queue.add.assert_called_once_with(thread_id=1, message=processed)

    @pytest.mark.asyncio
    async def test_handler_rejects_no_user(
        self,
        mock_message: MagicMock,
        mock_session: AsyncMock,
    ) -> None:
        """Handler rejects message without user."""
        from telegram.pipeline.handler import handle_message

        mock_message.from_user = None

        await handle_message(mock_message, mock_session)

        # Should not raise, just log warning

    @pytest.mark.asyncio
    @patch("telegram.pipeline.handler.get_normalizer")
    async def test_handler_sends_error_on_failure(
        self,
        mock_get_normalizer: MagicMock,
        mock_message: MagicMock,
        mock_session: AsyncMock,
    ) -> None:
        """Handler sends error message on failure."""
        from telegram.pipeline.handler import handle_message

        mock_message.text = "Test"

        # Normalizer raises exception
        normalizer = MagicMock()
        normalizer.normalize = AsyncMock(side_effect=ValueError("Test error"))
        mock_get_normalizer.return_value = normalizer

        await handle_message(mock_message, mock_session)

        # Should have called message.answer with error
        mock_message.answer.assert_called_once()
        args = mock_message.answer.call_args[0]
        assert "try again" in args[0].lower()
