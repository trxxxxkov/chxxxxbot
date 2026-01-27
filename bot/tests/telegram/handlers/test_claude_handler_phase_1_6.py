"""Integration tests for Claude handler with ProcessedMessage.

Tests message saving logic with ProcessedMessage:
- Transcript prefix formatting for voice/video_note
- File mention formatting for images/PDFs
- Database message saving
- Mixed batch processing (text + media)

Uses ProcessedMessage from the unified pipeline.
"""

from contextlib import asynccontextmanager
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import MessageMetadata
from telegram.pipeline.models import ProcessedMessage
from telegram.pipeline.models import TranscriptInfo
from telegram.pipeline.models import UploadedFile


@asynccontextmanager
async def mock_session_context(session):
    """Helper to create async context manager for mock session."""
    yield session


@pytest.fixture
def mock_session():
    """Create mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def sample_metadata() -> MessageMetadata:
    """Create sample MessageMetadata."""
    return MessageMetadata(
        chat_id=789012,
        user_id=123456,
        message_id=12345,
        message_thread_id=None,
        chat_type="private",
        date=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_message():
    """Create mock Telegram message."""
    message = MagicMock()
    message.message_id = 12345
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.from_user.username = "testuser"
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.chat = MagicMock()
    message.chat.id = 789012
    message.chat.type = "private"
    message.text = None
    message.caption = None
    message.answer = AsyncMock()
    message.date = MagicMock()
    message.date.timestamp.return_value = 1234567890.0
    message.message_thread_id = None
    message.reply_to_message = None
    return message


@pytest.fixture
def mock_thread():
    """Create mock Thread instance."""
    thread = Mock()
    thread.id = 42
    thread.chat_id = 789012
    thread.user_id = 123456
    thread.thread_id = None
    thread.model_id = "claude:sonnet"
    return thread


@pytest.fixture
def mock_thread_repo(mock_thread):
    """Create mock ThreadRepository."""
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=mock_thread)
    return repo


@pytest.fixture
def mock_message_repo():
    """Create mock MessageRepository."""
    repo = AsyncMock()
    repo.create_message = AsyncMock()
    repo.get_thread_messages = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_claude_provider():
    """Create mock Claude provider."""
    provider = AsyncMock()
    provider.stream_message = AsyncMock()
    return provider


@pytest.fixture
def mock_user():
    """Create mock User instance."""
    user = Mock()
    user.id = 123456
    user.model_id = "claude:sonnet"
    user.custom_prompt = None
    return user


@pytest.fixture
def mock_user_repo(mock_user):
    """Create mock UserRepository."""
    repo = AsyncMock()
    repo.get_by_id = AsyncMock(return_value=mock_user)
    return repo


@pytest.fixture
def mock_user_file_repo():
    """Create mock UserFileRepository."""
    repo = AsyncMock()
    repo.get_active_files_for_thread = AsyncMock(return_value=[])
    return repo


# ============================================================================
# ProcessedMessage Transcript Prefix Tests
# ============================================================================


@pytest.mark.asyncio
async def test_voice_message_transcript_prefix(
        mock_session, mock_message, sample_metadata, mock_thread_repo,
        mock_message_repo, mock_claude_provider, mock_user_repo,
        mock_user_file_repo):
    """Test voice message gets transcript prefix.

    Format: [VOICE MESSAGE - 12s]: transcript text
    """
    transcript = TranscriptInfo(
        text="Hello, how are you?",
        duration_seconds=12.5,
        detected_language="en",
        cost_usd=0.00125,
    )

    processed = ProcessedMessage(
        text=None,
        metadata=sample_metadata,
        original_message=mock_message,
        transcript=transcript,
    )

    # Create mock ServiceFactory
    mock_services = MagicMock()
    mock_services.threads = mock_thread_repo
    mock_services.messages = mock_message_repo
    mock_services.users = mock_user_repo
    mock_services.files = mock_user_file_repo

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ServiceFactory',
               return_value=mock_services), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [processed])

        mock_message_repo.create_message.assert_called()
        call_kwargs = mock_message_repo.create_message.call_args[1]

        # ProcessedMessage.get_text_for_db() uses int(duration)
        expected_prefix = "[VOICE MESSAGE - 12s]: Hello, how are you?"
        assert call_kwargs['text_content'] == expected_prefix


# ============================================================================
# File Mention Tests (Image/PDF/Document)
# ============================================================================


@pytest.mark.asyncio
async def test_image_with_caption(mock_session, mock_message, sample_metadata,
                                  mock_thread_repo, mock_message_repo,
                                  mock_claude_provider, mock_user_repo,
                                  mock_user_file_repo):
    """Test image with caption uses caption as text_content."""
    file = UploadedFile(
        claude_file_id="file_abc123",
        telegram_file_id="tg_123",
        telegram_file_unique_id="unique_123",
        file_type=MediaType.IMAGE,
        filename="photo.jpg",
        mime_type="image/jpeg",
        size_bytes=102400,
    )

    processed = ProcessedMessage(
        text="Look at this photo!",
        metadata=sample_metadata,
        original_message=mock_message,
        files=[file],
    )

    # Create mock ServiceFactory
    mock_services = MagicMock()
    mock_services.threads = mock_thread_repo
    mock_services.messages = mock_message_repo
    mock_services.users = mock_user_repo
    mock_services.files = mock_user_file_repo

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ServiceFactory',
               return_value=mock_services), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [processed])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        assert call_kwargs['text_content'] == "Look at this photo!"


@pytest.mark.asyncio
async def test_image_without_caption(mock_session, mock_message,
                                     sample_metadata, mock_thread_repo,
                                     mock_message_repo, mock_claude_provider,
                                     mock_user_repo, mock_user_file_repo):
    """Test image without caption gets file mention.

    Format: 📎 User uploaded image: filename.jpg (size bytes) [file_id: ...]
    """
    file = UploadedFile(
        claude_file_id="file_img_123",
        telegram_file_id="tg_123",
        telegram_file_unique_id="unique_123",
        file_type=MediaType.IMAGE,
        filename="photo.jpg",
        mime_type="image/jpeg",
        size_bytes=102400,
    )

    processed = ProcessedMessage(
        text=None,
        metadata=sample_metadata,
        original_message=mock_message,
        files=[file],
    )

    # Create mock ServiceFactory
    mock_services = MagicMock()
    mock_services.threads = mock_thread_repo
    mock_services.messages = mock_message_repo
    mock_services.users = mock_user_repo
    mock_services.files = mock_user_file_repo

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ServiceFactory',
               return_value=mock_services), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [processed])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        text = call_kwargs['text_content']

        assert "📎 User uploaded image: photo.jpg" in text
        assert "(102400 bytes)" in text
        assert "[file_id: file_img_123]" in text


# ============================================================================
# Regular Text Message Tests
# ============================================================================


@pytest.mark.asyncio
async def test_regular_text_message(mock_session, mock_message, sample_metadata,
                                    mock_thread_repo, mock_message_repo,
                                    mock_claude_provider, mock_user_repo,
                                    mock_user_file_repo):
    """Test regular text message without media."""
    processed = ProcessedMessage(
        text="Just a regular text message",
        metadata=sample_metadata,
        original_message=mock_message,
    )

    # Create mock ServiceFactory
    mock_services = MagicMock()
    mock_services.threads = mock_thread_repo
    mock_services.messages = mock_message_repo
    mock_services.users = mock_user_repo
    mock_services.files = mock_user_file_repo

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ServiceFactory',
               return_value=mock_services), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [processed])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        assert call_kwargs['text_content'] == "Just a regular text message"
