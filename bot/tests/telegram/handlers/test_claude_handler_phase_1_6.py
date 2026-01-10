"""Integration tests for Claude handler with MediaContent (Phase 1.6).

Tests universal media architecture integration:
- MediaContent extraction from message queue batches
- Transcript prefix formatting for voice/audio/video
- File mention formatting for images/PDFs
- Database message saving with MediaContent
- Mixed batch processing (text + media)

Note: This focuses on Phase 1.6 integration. Existing claude handler tests
in test_claude_handler_integration.py cover Phase 1.3 core functionality.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from telegram.media_processor import MediaContent
from telegram.media_processor import MediaType


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
    message.answer = AsyncMock()  # Make answer async
    message.date = MagicMock()
    message.date.timestamp.return_value = 1234567890.0
    message.message_thread_id = None
    return message


@pytest.fixture
def mock_thread():
    """Create mock Thread instance."""
    thread = Mock()
    thread.id = 42
    thread.chat_id = 789012
    thread.user_id = 123456
    thread.model_id = "claude:sonnet"  # Valid model from registry
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
# MediaContent Transcript Prefix Tests
# ============================================================================


@pytest.mark.asyncio
async def test_voice_message_transcript_prefix(
        mock_session, mock_message, mock_thread_repo, mock_message_repo,
        mock_claude_provider, mock_user_repo, mock_user_file_repo):
    """Test voice message gets transcript prefix.

    Format: [VOICE MESSAGE - 12.5s]: transcript text
    """
    # Setup voice media content
    media_content = MediaContent(type=MediaType.VOICE,
                                 text_content="Hello, how are you?",
                                 metadata={
                                     "duration": 12.5,
                                     "cost_usd": 0.00125
                                 })

    # Mock dependencies
    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        # Import after patches
        from telegram.handlers.claude import _process_message_batch

        # Execute
        await _process_message_batch(42, [(mock_message, media_content)])

        # Verify message saved with prefix
        mock_message_repo.create_message.assert_called()
        call_kwargs = mock_message_repo.create_message.call_args[1]

        # Check text_content format (duration is float from metadata)
        expected_prefix = "[VOICE MESSAGE - 12.5s]: Hello, how are you?"
        assert call_kwargs['text_content'] == expected_prefix


@pytest.mark.asyncio
async def test_audio_message_transcript_prefix(
        mock_session, mock_message, mock_thread_repo, mock_message_repo,
        mock_claude_provider, mock_user_repo, mock_user_file_repo):
    """Test audio file gets transcript prefix.

    Format: [AUDIO MESSAGE - 180s]: transcript text
    """
    media_content = MediaContent(type=MediaType.AUDIO,
                                 text_content="Song lyrics here",
                                 metadata={
                                     "duration": 180.0,
                                     "language": "en"
                                 })

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(mock_message, media_content)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        expected_prefix = "[AUDIO MESSAGE - 180.0s]: Song lyrics here"
        assert call_kwargs['text_content'] == expected_prefix


@pytest.mark.asyncio
async def test_video_message_transcript_prefix(
        mock_session, mock_message, mock_thread_repo, mock_message_repo,
        mock_claude_provider, mock_user_repo, mock_user_file_repo):
    """Test video file gets transcript prefix.

    Format: [VIDEO MESSAGE - 60s]: transcript text
    """
    media_content = MediaContent(type=MediaType.VIDEO,
                                 text_content="Video dialogue transcript",
                                 metadata={"duration": 60.0})

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(mock_message, media_content)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        expected_prefix = "[VIDEO MESSAGE - 60.0s]: Video dialogue transcript"
        assert call_kwargs['text_content'] == expected_prefix


@pytest.mark.asyncio
async def test_video_note_transcript_prefix(mock_session, mock_message,
                                            mock_thread_repo, mock_message_repo,
                                            mock_claude_provider,
                                            mock_user_repo,
                                            mock_user_file_repo):
    """Test video note (round video) gets transcript prefix.

    Format: [VIDEO_NOTE MESSAGE - 30s]: transcript text
    """
    media_content = MediaContent(type=MediaType.VIDEO_NOTE,
                                 text_content="Round video speech",
                                 metadata={"duration": 30.0})

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(mock_message, media_content)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        expected_prefix = "[VIDEO_NOTE MESSAGE - 30.0s]: Round video speech"
        assert call_kwargs['text_content'] == expected_prefix


# ============================================================================
# File Mention Tests (Image/PDF/Document)
# ============================================================================


@pytest.mark.asyncio
async def test_image_with_caption(mock_session, mock_thread_repo,
                                  mock_message_repo, mock_claude_provider,
                                  mock_user_repo, mock_user_file_repo):
    """Test image with caption uses caption as text_content."""
    message = MagicMock()
    message.message_id = 12345
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.chat = MagicMock()
    message.chat.id = 789012
    message.text = None
    message.caption = "Look at this photo!"
    message.date = MagicMock()
    message.date.timestamp.return_value = 1234567890.0
    message.message_thread_id = None
    message.answer = AsyncMock()

    media_content = MediaContent(type=MediaType.IMAGE,
                                 file_id="file_abc123",
                                 metadata={
                                     "filename": "photo.jpg",
                                     "size_bytes": 102400
                                 })

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(message, media_content)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        assert call_kwargs['text_content'] == "Look at this photo!"


@pytest.mark.asyncio
async def test_image_without_caption(mock_session, mock_message,
                                     mock_thread_repo, mock_message_repo,
                                     mock_claude_provider, mock_user_repo,
                                     mock_user_file_repo):
    """Test image without caption gets file mention.

    Format: 📎 User uploaded image: filename.jpg (size bytes) [file_id: ...]
    """
    media_content = MediaContent(type=MediaType.IMAGE,
                                 file_id="file_img_123",
                                 metadata={
                                     "filename": "photo.jpg",
                                     "size_bytes": 102400
                                 })

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(mock_message, media_content)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        text = call_kwargs['text_content']

        assert "📎 User uploaded image: photo.jpg" in text
        assert "(102400 bytes)" in text
        assert "[file_id: file_img_123]" in text


@pytest.mark.asyncio
async def test_pdf_without_caption(mock_session, mock_message, mock_thread_repo,
                                   mock_message_repo, mock_claude_provider,
                                   mock_user_repo, mock_user_file_repo):
    """Test PDF without caption gets file mention."""
    media_content = MediaContent(type=MediaType.DOCUMENT,
                                 file_id="file_pdf_456",
                                 metadata={
                                     "filename": "report.pdf",
                                     "size_bytes": 512000
                                 })

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(mock_message, media_content)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        text = call_kwargs['text_content']

        assert "📎 User uploaded document: report.pdf" in text
        assert "(512000 bytes)" in text
        assert "[file_id: file_pdf_456]" in text


# ============================================================================
# Mixed Batch Tests
# ============================================================================


@pytest.mark.asyncio
async def test_mixed_batch_text_and_voice(mock_session, mock_thread_repo,
                                          mock_message_repo,
                                          mock_claude_provider, mock_user_repo,
                                          mock_user_file_repo):
    """Test batch with both text and voice messages."""
    # Text message
    msg1 = MagicMock()
    msg1.message_id = 12345
    msg1.from_user = MagicMock()
    msg1.from_user.id = 123456
    msg1.chat = MagicMock()
    msg1.chat.id = 789012
    msg1.text = "Hello Claude"
    msg1.caption = None
    msg1.date = MagicMock()
    msg1.date.timestamp.return_value = 1234567890.0
    msg1.message_thread_id = None
    msg1.answer = AsyncMock()

    # Voice message
    msg2 = MagicMock()
    msg2.message_id = 12346
    msg2.from_user = MagicMock()
    msg2.from_user.id = 123456
    msg2.chat = MagicMock()
    msg2.chat.id = 789012
    msg2.text = None
    msg2.caption = None
    msg2.date = MagicMock()
    msg2.date.timestamp.return_value = 1234567890.0
    msg2.message_thread_id = None
    msg2.answer = AsyncMock()

    media_content = MediaContent(type=MediaType.VOICE,
                                 text_content="How are you?",
                                 metadata={"duration": 8.0})

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        # Process batch with both messages
        await _process_message_batch(42, [(msg1, None), (msg2, media_content)])

        # Should save both messages
        assert mock_message_repo.create_message.call_count == 2

        # First message: regular text
        first_call = mock_message_repo.create_message.call_args_list[0][1]
        assert first_call['text_content'] == "Hello Claude"

        # Second message: voice with prefix
        second_call = mock_message_repo.create_message.call_args_list[1][1]
        assert second_call[
            'text_content'] == "[VOICE MESSAGE - 8.0s]: How are you?"


@pytest.mark.asyncio
async def test_mixed_batch_image_and_audio(mock_session, mock_thread_repo,
                                           mock_message_repo,
                                           mock_claude_provider, mock_user_repo,
                                           mock_user_file_repo):
    """Test batch with image and audio messages."""
    # Image message
    msg1 = MagicMock()
    msg1.message_id = 12345
    msg1.from_user = MagicMock()
    msg1.from_user.id = 123456
    msg1.chat = MagicMock()
    msg1.chat.id = 789012
    msg1.text = None
    msg1.caption = "Beautiful sunset"
    msg1.date = MagicMock()
    msg1.date.timestamp.return_value = 1234567890.0
    msg1.message_thread_id = None
    msg1.answer = AsyncMock()

    media1 = MediaContent(type=MediaType.IMAGE,
                          file_id="file_img_789",
                          metadata={
                              "filename": "sunset.jpg",
                              "size_bytes": 204800
                          })

    # Audio message
    msg2 = MagicMock()
    msg2.message_id = 12346
    msg2.from_user = MagicMock()
    msg2.from_user.id = 123456
    msg2.chat = MagicMock()
    msg2.chat.id = 789012
    msg2.text = None
    msg2.caption = None
    msg2.date = MagicMock()
    msg2.date.timestamp.return_value = 1234567890.0
    msg2.message_thread_id = None
    msg2.answer = AsyncMock()

    media2 = MediaContent(type=MediaType.AUDIO,
                          text_content="Music lyrics",
                          metadata={"duration": 240.0})

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(msg1, media1), (msg2, media2)])

        # Should save both messages
        assert mock_message_repo.create_message.call_count == 2

        # First message: image with caption
        first_call = mock_message_repo.create_message.call_args_list[0][1]
        assert first_call['text_content'] == "Beautiful sunset"

        # Second message: audio with transcript prefix
        second_call = mock_message_repo.create_message.call_args_list[1][1]
        assert second_call[
            'text_content'] == "[AUDIO MESSAGE - 240.0s]: Music lyrics"


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_regular_text_message_no_media(
        mock_session, mock_message, mock_thread_repo, mock_message_repo,
        mock_claude_provider, mock_user_repo, mock_user_file_repo):
    """Test regular text message without MediaContent."""
    mock_message.text = "Just a regular text message"

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(mock_message, None)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        assert call_kwargs['text_content'] == "Just a regular text message"


@pytest.mark.asyncio
async def test_voice_with_zero_duration(mock_session, mock_message,
                                        mock_thread_repo, mock_message_repo,
                                        mock_claude_provider, mock_user_repo,
                                        mock_user_file_repo):
    """Test voice message with missing or zero duration in metadata."""
    media_content = MediaContent(type=MediaType.VOICE,
                                 text_content="Short voice",
                                 metadata={})  # No duration

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(mock_message, media_content)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        # Should default to 0 if duration missing
        assert call_kwargs[
            'text_content'] == "[VOICE MESSAGE - 0s]: Short voice"


@pytest.mark.asyncio
async def test_file_without_filename_metadata(
        mock_session, mock_message, mock_thread_repo, mock_message_repo,
        mock_claude_provider, mock_user_repo, mock_user_file_repo):
    """Test file message with missing filename in metadata."""
    media_content = MediaContent(type=MediaType.IMAGE,
                                 file_id="file_xyz",
                                 metadata={"size_bytes": 1024})  # No filename

    with patch('telegram.handlers.claude.get_session') as mock_get_session, \
         patch('telegram.handlers.claude.ThreadRepository',
               return_value=mock_thread_repo), \
         patch('telegram.handlers.claude.MessageRepository',
               return_value=mock_message_repo), \
         patch('telegram.handlers.claude.UserRepository',
               return_value=mock_user_repo), \
         patch('telegram.handlers.claude.UserFileRepository',
               return_value=mock_user_file_repo), \
         patch('telegram.handlers.claude.ClaudeProvider',
               return_value=mock_claude_provider), \
         patch('telegram.handlers.claude.claude_provider',
               mock_claude_provider):

        # Configure mock_get_session to return async context manager
        mock_get_session.return_value = mock_session_context(mock_session)

        from telegram.handlers.claude import _process_message_batch

        await _process_message_batch(42, [(mock_message, media_content)])

        call_kwargs = mock_message_repo.create_message.call_args[1]
        text = call_kwargs['text_content']

        # Should default to "file" if filename missing
        assert "User uploaded image: file" in text
