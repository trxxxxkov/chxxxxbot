"""Tests for media handlers (Phase 1.6).

Tests all media handlers:
- handle_voice() - voice messages
- handle_audio() - audio files
- handle_video() - video files
- handle_video_note() - round video messages

Tests integration with MediaProcessor and message queue.
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from telegram.handlers.media_handlers import get_media_processor
from telegram.handlers.media_handlers import handle_audio
from telegram.handlers.media_handlers import handle_video
from telegram.handlers.media_handlers import handle_video_note
from telegram.handlers.media_handlers import handle_voice
from telegram.media_processor import MediaContent
from telegram.media_processor import MediaType

# ============================================================================
# handle_voice() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_handle_voice_success():
    """Test successful voice message handling.

    Flow:
    1. Download voice from Telegram
    2. Transcribe with Whisper
    3. Charge user for transcription (if cost_usd in metadata)
    4. Get/create thread
    5. Add to message queue with MediaContent
    """
    # Mock message
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.voice = MagicMock()
    message.voice.file_id = "voice_id_123"
    message.voice.duration = 15
    message.voice.file_size = 50000
    message.message_id = 1001

    # Mock session
    session = AsyncMock()

    # Mock media processor - no cost to avoid charging path complexity
    mock_processor = AsyncMock()
    mock_media_content = MediaContent(type=MediaType.VOICE,
                                      text_content="Transcribed text",
                                      metadata={"duration": 15})
    mock_processor.process_voice.return_value = mock_media_content

    # Mock download_media
    mock_audio_bytes = b"voice_data"

    # Mock thread
    mock_thread = Mock()
    mock_thread.id = 42

    # Mock message queue
    mock_queue_manager = AsyncMock()

    with patch('telegram.handlers.media_handlers.download_media',
               return_value=mock_audio_bytes) as mock_download, \
         patch('telegram.handlers.media_handlers.get_or_create_thread',
               return_value=mock_thread) as mock_get_thread, \
         patch('telegram.handlers.media_handlers.get_media_processor',
               return_value=mock_processor), \
         patch('telegram.handlers.claude.message_queue_manager',
               mock_queue_manager):

        # Execute
        await handle_voice(message, session)

        # Verify download
        mock_download.assert_called_once()
        assert mock_download.call_args[0][1] == MediaType.VOICE

        # Verify processing
        mock_processor.process_voice.assert_called_once_with(
            audio_bytes=mock_audio_bytes,
            filename="voice_voice_id.ogg",
            duration=15)

        # Verify thread resolution
        mock_get_thread.assert_called_once_with(message, session)

        # Verify queue addition
        mock_queue_manager.add_message.assert_called_once_with(
            42,  # thread_id
            message,
            media_content=mock_media_content,
            immediate=True)


@pytest.mark.asyncio
async def test_handle_voice_no_from_user():
    """Test voice handler with missing from_user."""
    message = MagicMock()
    message.from_user = None
    message.voice = None

    session = AsyncMock()

    # Should return early (warning logged)
    await handle_voice(message, session)

    # No processing should happen
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_handle_voice_whisper_api_error():
    """Test voice handler when Whisper API fails.

    Should send error message to user.
    """
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 123
    message.voice = MagicMock()
    message.voice.file_id = "voice_id"
    message.voice.duration = 10
    message.voice.file_size = 10000
    message.answer = AsyncMock()

    session = AsyncMock()

    # Mock download success but processing failure
    mock_audio_bytes = b"data"

    mock_processor = AsyncMock()
    # Create proper APIError with mock request
    from unittest.mock import Mock

    import openai
    mock_request = Mock()
    api_error = openai.APIError(message="Whisper API failed",
                                request=mock_request,
                                body=None)
    mock_processor.process_voice.side_effect = api_error

    with patch('telegram.handlers.media_handlers.download_media',
               return_value=mock_audio_bytes), \
         patch('telegram.handlers.media_handlers.get_media_processor',
               return_value=mock_processor):

        # Execute
        await handle_voice(message, session)

        # Verify error message sent
        message.answer.assert_called_once()
        assert "Failed to transcribe" in message.answer.call_args[0][0]


# ============================================================================
# handle_audio() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_handle_audio_success():
    """Test successful audio file handling."""
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 456
    message.audio = MagicMock()
    message.audio.file_id = "audio_id_789"
    message.audio.file_name = "song.mp3"
    message.audio.duration = 180
    message.audio.file_size = 5000000
    message.audio.mime_type = "audio/mpeg"
    message.message_id = 2001

    session = AsyncMock()

    mock_processor = AsyncMock()
    mock_media_content = MediaContent(type=MediaType.AUDIO,
                                      text_content="Song lyrics",
                                      metadata={
                                          "duration": 180,
                                          "language": "en"
                                      })
    mock_processor.process_audio.return_value = mock_media_content

    mock_audio_bytes = b"audio_file_data"
    mock_thread = Mock()
    mock_thread.id = 99
    mock_queue_manager = AsyncMock()

    with patch('telegram.handlers.media_handlers.download_media',
               return_value=mock_audio_bytes), \
         patch('telegram.handlers.media_handlers.get_or_create_thread',
               return_value=mock_thread), \
         patch('telegram.handlers.media_handlers.get_media_processor',
               return_value=mock_processor), \
         patch('telegram.handlers.claude.message_queue_manager',
               mock_queue_manager):

        await handle_audio(message, session)

        # Verify processing
        mock_processor.process_audio.assert_called_once()
        assert mock_processor.process_audio.call_args[1][
            "filename"] == "song.mp3"

        # Verify immediate queue processing
        mock_queue_manager.add_message.assert_called_once()
        assert mock_queue_manager.add_message.call_args[1]["immediate"] is True


# ============================================================================
# handle_video() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_handle_video_success():
    """Test successful video file handling."""
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 789
    message.video = MagicMock()
    message.video.file_id = "video_id_456"
    message.video.file_name = "clip.mp4"
    message.video.duration = 60
    message.video.file_size = 10000000
    message.video.mime_type = "video/mp4"

    session = AsyncMock()

    mock_processor = AsyncMock()
    mock_media_content = MediaContent(type=MediaType.VIDEO,
                                      text_content="Video dialogue",
                                      metadata={"duration": 60})
    mock_processor.process_video.return_value = mock_media_content

    mock_video_bytes = b"video_data"
    mock_thread = Mock()
    mock_thread.id = 77
    mock_queue_manager = AsyncMock()

    with patch('telegram.handlers.media_handlers.download_media',
               return_value=mock_video_bytes), \
         patch('telegram.handlers.media_handlers.get_or_create_thread',
               return_value=mock_thread), \
         patch('telegram.handlers.media_handlers.get_media_processor',
               return_value=mock_processor), \
         patch('telegram.handlers.claude.message_queue_manager',
               mock_queue_manager):

        await handle_video(message, session)

        # Verify download with correct type
        # (download_media is patched, can't check args easily)

        # Verify processing
        mock_processor.process_video.assert_called_once()


# ============================================================================
# handle_video_note() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_handle_video_note_success():
    """Test successful video note (round video) handling."""
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 111
    message.video_note = MagicMock()
    message.video_note.file_id = "video_note_id_999"
    message.video_note.duration = 30
    message.video_note.file_size = 2000000

    session = AsyncMock()

    mock_processor = AsyncMock()
    mock_media_content = MediaContent(type=MediaType.VIDEO,
                                      text_content="Round video speech",
                                      metadata={"duration": 30})
    mock_processor.process_video.return_value = mock_media_content

    mock_video_bytes = b"video_note_data"
    mock_thread = Mock()
    mock_thread.id = 55
    mock_queue_manager = AsyncMock()

    with patch('telegram.handlers.media_handlers.download_media',
               return_value=mock_video_bytes), \
         patch('telegram.handlers.media_handlers.get_or_create_thread',
               return_value=mock_thread), \
         patch('telegram.handlers.media_handlers.get_media_processor',
               return_value=mock_processor), \
         patch('telegram.handlers.claude.message_queue_manager',
               mock_queue_manager):

        await handle_video_note(message, session)

        # Verify processing (video notes use process_video)
        mock_processor.process_video.assert_called_once()

        # Verify queue
        mock_queue_manager.add_message.assert_called_once()


# ============================================================================
# get_media_processor() Tests
# ============================================================================


def test_get_media_processor_singleton():
    """Test that get_media_processor returns same instance.

    MediaProcessor should be a singleton (global instance).
    """
    # Reset global
    import telegram.handlers.media_handlers as mh
    mh._media_processor = None

    # Get processor twice
    processor1 = get_media_processor()
    processor2 = get_media_processor()

    # Should be same instance
    assert processor1 is processor2


def test_get_media_processor_initializes_once():
    """Test that MediaProcessor is initialized only once."""
    import telegram.handlers.media_handlers as mh
    mh._media_processor = None

    with patch('telegram.handlers.media_handlers.MediaProcessor') as MockMP:
        mock_instance = Mock()
        MockMP.return_value = mock_instance

        # Call twice
        get_media_processor()
        get_media_processor()

        # Should construct only once
        MockMP.assert_called_once()


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_handle_voice_queue_not_initialized():
    """Test voice handler when message queue not initialized."""
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 123
    message.voice = MagicMock()
    message.voice.file_id = "voice_id"
    message.voice.duration = 10
    message.voice.file_size = 10000
    message.answer = AsyncMock()

    session = AsyncMock()

    mock_processor = AsyncMock()
    mock_media_content = MediaContent(type=MediaType.VOICE, text_content="text")
    mock_processor.process_voice.return_value = mock_media_content

    mock_audio_bytes = b"data"
    mock_thread = Mock()
    mock_thread.id = 1

    with patch('telegram.handlers.media_handlers.download_media',
               return_value=mock_audio_bytes), \
         patch('telegram.handlers.media_handlers.get_or_create_thread',
               return_value=mock_thread), \
         patch('telegram.handlers.media_handlers.get_media_processor',
               return_value=mock_processor), \
         patch('telegram.handlers.claude.message_queue_manager',
               None):  # Queue not initialized

        await handle_voice(message, session)

        # Should send error message
        message.answer.assert_called_once()
        assert "not properly configured" in message.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_audio_generic_error():
    """Test audio handler with unexpected error."""
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 456
    message.audio = MagicMock()
    message.audio.file_id = "audio_id"
    message.audio.file_name = "test.mp3"
    message.audio.duration = 60
    message.audio.file_size = 1000
    message.audio.mime_type = "audio/mpeg"
    message.answer = AsyncMock()

    session = AsyncMock()

    # Mock unexpected exception
    with patch('telegram.handlers.media_handlers.download_media',
               side_effect=Exception("Unexpected error")):

        await handle_audio(message, session)

        # Should send error message
        message.answer.assert_called_once()
        assert "Failed to process" in message.answer.call_args[0][0]
