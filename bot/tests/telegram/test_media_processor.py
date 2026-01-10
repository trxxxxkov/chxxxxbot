"""Tests for MediaProcessor (Phase 1.6).

Tests universal media processing architecture including:
- Voice message transcription
- Audio file transcription
- Video file transcription (audio track extraction)
- Image upload to Files API
- PDF upload to Files API
- Media download from Telegram
- Thread resolution helpers
"""

import io
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from telegram.media_processor import download_media
from telegram.media_processor import get_or_create_thread
from telegram.media_processor import MediaContent
from telegram.media_processor import MediaProcessor
from telegram.media_processor import MediaType

# ============================================================================
# MediaProcessor Tests
# ============================================================================


@pytest.fixture
def media_processor():
    """Create MediaProcessor instance.

    Returns:
        MediaProcessor instance for testing.
    """
    return MediaProcessor()


@pytest.mark.asyncio
async def test_process_voice_success(media_processor):
    """Test successful voice message transcription.

    Tests:
    - OpenAI client initialization
    - Whisper API call
    - Cost calculation ($0.006 per minute)
    - MediaContent creation
    """
    # Mock OpenAI client
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.strip.return_value = "Привет, как дела?"
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch.object(media_processor,
                      '_get_openai_client',
                      return_value=mock_client):
        # Test data
        audio_bytes = b"fake_audio_data"
        filename = "voice.ogg"
        duration = 10  # 10 seconds

        # Execute
        result = await media_processor.process_voice(audio_bytes, filename,
                                                     duration)

        # Verify
        assert isinstance(result, MediaContent)
        assert result.type == MediaType.VOICE
        assert result.text_content == "Привет, как дела?"
        assert result.file_id is None
        assert result.metadata["duration"] == 10
        assert result.metadata["cost_usd"] == 0.001  # 10s = 0.001 USD
        assert result.metadata["language"] == "auto"

        # Verify Whisper API call
        mock_client.audio.transcriptions.create.assert_called_once()
        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["model"] == "whisper-1"
        assert call_kwargs["language"] is None  # auto-detect
        assert call_kwargs["response_format"] == "text"


@pytest.mark.asyncio
async def test_process_audio_success(media_processor):
    """Test successful audio file transcription.

    Tests:
    - Audio file processing (MP3, FLAC, etc.)
    - verbose_json response format
    - Duration detection from API response
    """
    # Mock OpenAI client
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.text = "This is the transcript"
    mock_response.duration = 180.5  # 3 minutes
    mock_response.language = "en"
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch.object(media_processor,
                      '_get_openai_client',
                      return_value=mock_client):
        # Test data
        audio_bytes = b"fake_mp3_data"
        filename = "song.mp3"

        # Execute
        result = await media_processor.process_audio(audio_bytes, filename)

        # Verify
        assert result.type == MediaType.AUDIO
        assert result.text_content == "This is the transcript"
        assert result.metadata["duration"] == 180.5
        # Cost: 180.5s / 60 * 0.006 = 0.01805
        assert result.metadata["cost_usd"] == pytest.approx(0.01805, rel=1e-4)
        assert result.metadata["language"] == "en"

        # Verify verbose_json format
        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["response_format"] == "verbose_json"


@pytest.mark.asyncio
async def test_process_video_success(media_processor):
    """Test successful video transcription (audio track).

    Tests:
    - Video file processing (MP4, MOV, etc.)
    - Whisper automatically extracts audio from video
    """
    # Mock OpenAI client
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.text = "Video dialogue transcript"
    mock_response.duration = 120.0
    mock_response.language = "ru"
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch.object(media_processor,
                      '_get_openai_client',
                      return_value=mock_client):
        # Test data
        video_bytes = b"fake_mp4_data"
        filename = "video.mp4"

        # Execute
        result = await media_processor.process_video(video_bytes, filename)

        # Verify
        assert result.type == MediaType.VIDEO
        assert result.text_content == "Video dialogue transcript"
        assert result.metadata["duration"] == 120.0
        assert result.metadata["language"] == "ru"


@pytest.mark.asyncio
async def test_process_image_success(media_processor):
    """Test successful image upload to Files API.

    Tests:
    - Anthropic client initialization
    - Files API upload
    - file_id in MediaContent
    """
    # Mock Anthropic client
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.id = "file_abc123"
    mock_client.files.create.return_value = mock_response

    with patch.object(media_processor,
                      '_get_anthropic_client',
                      return_value=mock_client):
        # Test data
        image_bytes = b"fake_image_data"
        filename = "photo.jpg"

        # Execute
        result = await media_processor.process_image(image_bytes, filename)

        # Verify
        assert result.type == MediaType.IMAGE
        assert result.text_content is None
        assert result.file_id == "file_abc123"
        assert result.metadata["filename"] == "photo.jpg"
        assert result.metadata["size_bytes"] == len(image_bytes)

        # Verify Files API call
        mock_client.files.create.assert_called_once()
        call_kwargs = mock_client.files.create.call_args[1]
        assert call_kwargs["purpose"] == "vision"


@pytest.mark.asyncio
async def test_process_pdf_success(media_processor):
    """Test successful PDF upload to Files API.

    Tests:
    - PDF file processing
    - application/pdf mime type
    """
    # Mock Anthropic client
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.id = "file_def456"
    mock_client.files.create.return_value = mock_response

    with patch.object(media_processor,
                      '_get_anthropic_client',
                      return_value=mock_client):
        # Test data
        pdf_bytes = b"fake_pdf_data"
        filename = "document.pdf"

        # Execute
        result = await media_processor.process_pdf(pdf_bytes, filename)

        # Verify
        assert result.type == MediaType.DOCUMENT
        assert result.file_id == "file_def456"
        assert result.metadata["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_process_voice_with_language(media_processor):
    """Test voice transcription with specified language.

    Tests:
    - Language parameter passed to Whisper
    """
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.strip.return_value = "Bonjour"
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch.object(media_processor,
                      '_get_openai_client',
                      return_value=mock_client):
        # Execute with French language
        result = await media_processor.process_voice(b"data",
                                                     "voice.ogg",
                                                     10,
                                                     language="fr")

        # Verify language parameter
        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["language"] == "fr"
        assert result.metadata["language"] == "fr"


# ============================================================================
# Helper Functions Tests
# ============================================================================


@pytest.mark.asyncio
async def test_download_media_voice():
    """Test downloading voice message from Telegram.

    Tests:
    - Voice message type detection
    - File ID extraction
    - Telegram API download
    """
    # Mock message
    message = MagicMock()
    message.voice = MagicMock()
    message.voice.file_id = "voice_file_id_123"

    # Mock bot
    mock_file_info = Mock()
    mock_file_info.file_path = "/path/to/voice.ogg"

    mock_bytes_io = io.BytesIO(b"voice_data_bytes")
    message.bot.get_file = AsyncMock(return_value=mock_file_info)
    message.bot.download_file = AsyncMock(return_value=mock_bytes_io)

    # Execute
    result = await download_media(message, MediaType.VOICE)

    # Verify
    assert result == b"voice_data_bytes"
    message.bot.get_file.assert_called_once_with("voice_file_id_123")
    message.bot.download_file.assert_called_once_with("/path/to/voice.ogg")


@pytest.mark.asyncio
async def test_download_media_audio():
    """Test downloading audio file from Telegram."""
    message = MagicMock()
    message.audio = MagicMock()
    message.audio.file_id = "audio_file_id_456"

    mock_file_info = Mock()
    mock_file_info.file_path = "/path/to/song.mp3"

    mock_bytes_io = io.BytesIO(b"audio_data_bytes")
    message.bot.get_file = AsyncMock(return_value=mock_file_info)
    message.bot.download_file = AsyncMock(return_value=mock_bytes_io)

    result = await download_media(message, MediaType.AUDIO)

    assert result == b"audio_data_bytes"


@pytest.mark.asyncio
async def test_download_media_video():
    """Test downloading video file from Telegram."""
    message = MagicMock()
    message.video = MagicMock()
    message.video.file_id = "video_file_id_789"

    mock_file_info = Mock()
    mock_file_info.file_path = "/path/to/video.mp4"

    mock_bytes_io = io.BytesIO(b"video_data_bytes")
    message.bot.get_file = AsyncMock(return_value=mock_file_info)
    message.bot.download_file = AsyncMock(return_value=mock_bytes_io)

    result = await download_media(message, MediaType.VIDEO)

    assert result == b"video_data_bytes"


@pytest.mark.asyncio
async def test_download_media_image():
    """Test downloading image (photo) from Telegram.

    Tests:
    - Photo array (multiple sizes)
    - Selecting largest photo
    """
    message = MagicMock()

    # Multiple photo sizes (Telegram sends array)
    photo1 = Mock()
    photo1.file_id = "photo_small"
    photo2 = Mock()
    photo2.file_id = "photo_large"

    message.photo = [photo1, photo2]

    mock_file_info = Mock()
    mock_file_info.file_path = "/path/to/photo.jpg"

    mock_bytes_io = io.BytesIO(b"image_data_bytes")
    message.bot.get_file = AsyncMock(return_value=mock_file_info)
    message.bot.download_file = AsyncMock(return_value=mock_bytes_io)

    result = await download_media(message, MediaType.IMAGE)

    # Should download largest (last) photo
    assert result == b"image_data_bytes"
    message.bot.get_file.assert_called_once_with("photo_large")


@pytest.mark.asyncio
async def test_download_media_invalid_type():
    """Test error handling for invalid media type."""
    message = MagicMock()
    message.voice = None

    with pytest.raises(ValueError, match="Invalid media type"):
        await download_media(message, MediaType.VOICE)


@pytest.mark.asyncio
async def test_get_or_create_thread_creates_new():
    """Test thread creation for new user/chat.

    Tests:
    - User creation
    - Chat creation
    - Thread creation
    - All repositories work together
    """
    # Mock message
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.from_user.username = "testuser"
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.chat = MagicMock()
    message.chat.id = 789012
    message.chat.type = "private"
    message.chat.title = None
    message.message_thread_id = None

    # Mock session
    session = AsyncMock()

    # Mock repositories
    with patch('telegram.media_processor.UserRepository') as MockUserRepo, \
         patch('telegram.media_processor.ChatRepository') as MockChatRepo, \
         patch('telegram.media_processor.ThreadRepository') as MockThreadRepo:

        # Setup mocks
        mock_user = Mock()
        mock_user.id = 1
        MockUserRepo.return_value.get_or_create = AsyncMock(
            return_value=(mock_user, True))

        mock_chat = Mock()
        mock_chat.id = 2
        MockChatRepo.return_value.get_or_create = AsyncMock(
            return_value=(mock_chat, True))

        mock_thread = Mock()
        mock_thread.id = 3
        MockThreadRepo.return_value.get_or_create_thread = AsyncMock(
            return_value=(mock_thread, True))

        # Execute
        result = await get_or_create_thread(message, session)

        # Verify
        assert result.id == 3

        # Verify repository calls
        MockUserRepo.return_value.get_or_create.assert_called_once_with(
            telegram_id=123456,
            username="testuser",
            first_name="Test",
            last_name="User")

        MockChatRepo.return_value.get_or_create.assert_called_once_with(
            telegram_id=789012, chat_type="private", title=None)

        MockThreadRepo.return_value.get_or_create_thread.assert_called_once_with(
            chat_id=789012, user_id=123456, thread_id=None)


@pytest.mark.asyncio
async def test_get_or_create_thread_with_forum_topic():
    """Test thread creation with Telegram forum topic ID.

    Tests:
    - message_thread_id parameter
    """
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 111
    message.from_user.username = None
    message.from_user.first_name = "John"
    message.from_user.last_name = None
    message.chat = MagicMock()
    message.chat.id = 222
    message.chat.type = "supergroup"
    message.chat.title = "Test Group"
    message.message_thread_id = 54321  # Forum topic ID

    session = AsyncMock()

    with patch('telegram.media_processor.UserRepository') as MockUserRepo, \
         patch('telegram.media_processor.ChatRepository') as MockChatRepo, \
         patch('telegram.media_processor.ThreadRepository') as MockThreadRepo:

        mock_user = Mock()
        mock_user.id = 1
        MockUserRepo.return_value.get_or_create = AsyncMock(
            return_value=(mock_user, False))

        mock_chat = Mock()
        mock_chat.id = 2
        MockChatRepo.return_value.get_or_create = AsyncMock(
            return_value=(mock_chat, False))

        mock_thread = Mock()
        mock_thread.id = 3
        MockThreadRepo.return_value.get_or_create_thread = AsyncMock(
            return_value=(mock_thread, True))

        result = await get_or_create_thread(message, session)

        # Verify thread_id parameter
        MockThreadRepo.return_value.get_or_create_thread.assert_called_once_with(
            chat_id=222, user_id=111, thread_id=54321)


@pytest.mark.asyncio
async def test_get_or_create_thread_no_from_user():
    """Test error handling when message has no from_user."""
    message = MagicMock()
    message.from_user = None

    session = AsyncMock()

    with pytest.raises(ValueError, match="Message has no from_user"):
        await get_or_create_thread(message, session)


# ============================================================================
# MediaContent Tests
# ============================================================================


def test_media_content_creation_voice():
    """Test MediaContent creation for voice messages."""
    content = MediaContent(type=MediaType.VOICE,
                           text_content="Hello world",
                           file_id=None,
                           metadata={
                               "duration": 5,
                               "cost_usd": 0.0005
                           })

    assert content.type == MediaType.VOICE
    assert content.text_content == "Hello world"
    assert content.file_id is None
    assert content.metadata["duration"] == 5


def test_media_content_creation_image():
    """Test MediaContent creation for images."""
    content = MediaContent(type=MediaType.IMAGE,
                           text_content=None,
                           file_id="file_xyz",
                           metadata={"size_bytes": 1024})

    assert content.type == MediaType.IMAGE
    assert content.text_content is None
    assert content.file_id == "file_xyz"


def test_media_content_metadata_default():
    """Test MediaContent metadata initialization."""
    content = MediaContent(type=MediaType.AUDIO, text_content="test")

    # Should initialize empty dict
    assert content.metadata == {}
    assert isinstance(content.metadata, dict)


def test_media_content_metadata_provided():
    """Test MediaContent with provided metadata."""
    metadata = {"duration": 100, "language": "en"}
    content = MediaContent(type=MediaType.AUDIO,
                           text_content="test",
                           metadata=metadata)

    assert content.metadata is metadata
    assert content.metadata["duration"] == 100
