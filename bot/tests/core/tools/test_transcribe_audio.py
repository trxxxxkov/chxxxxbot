"""Tests for transcribe_audio tool (Phase 1.6).

Tests Whisper API integration for speech-to-text transcription:
- Success flow (auto language detection)
- Language parameter handling
- File download from Telegram
- Error handling (file not found, download failures, API errors)
- Cost calculation
"""

import io
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

from core.tools.transcribe_audio import download_file_from_telegram
from core.tools.transcribe_audio import transcribe_audio
from core.tools.transcribe_audio import TRANSCRIBE_AUDIO_TOOL
import openai
import pytest


@pytest.fixture(autouse=True)
def reset_client():
    """Reset global client before and after each test."""
    # Reset before test
    import core.clients
    core.clients._openai_async_client = None
    yield
    # Reset after test
    core.clients._openai_async_client = None


# ============================================================================
# download_file_from_telegram() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_download_file_from_telegram_success():
    """Test successful file download from Telegram.

    Flow:
    1. Query database for file metadata
    2. Get telegram_file_id
    3. Call bot.get_file() and bot.download_file()
    4. Return bytes
    """
    file_id = 'file_abc123'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock file record from database
    mock_file_record = Mock()
    mock_file_record.telegram_file_id = 'telegram_file_456'
    mock_file_record.filename = 'audio.mp3'

    # Mock repository
    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = mock_file_record

    # Mock Telegram API
    mock_file_info = Mock()
    mock_file_info.file_path = '/path/to/audio.mp3'
    bot.get_file.return_value = mock_file_info

    mock_bytes_io = io.BytesIO(b'audio_file_data')
    bot.download_file.return_value = mock_bytes_io

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo):
        # Execute
        result = await download_file_from_telegram(file_id, bot, session)

        # Verify
        assert result == b'audio_file_data'
        mock_repo.get_by_claude_file_id.assert_called_once_with(file_id)
        bot.get_file.assert_called_once_with('telegram_file_456')
        bot.download_file.assert_called_once_with('/path/to/audio.mp3')


@pytest.mark.asyncio
async def test_download_file_from_telegram_file_not_found():
    """Test error when file not found in database."""
    file_id = 'file_nonexistent'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock repository returning None
    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = None

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo):
        # Execute and verify exception
        with pytest.raises(ValueError, match='File not found in database'):
            await download_file_from_telegram(file_id, bot, session)


@pytest.mark.asyncio
async def test_download_file_from_telegram_no_telegram_file_id():
    """Test error when file has no telegram_file_id."""
    file_id = 'file_abc123'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock file record WITHOUT telegram_file_id (assistant-generated file)
    mock_file_record = Mock()
    mock_file_record.telegram_file_id = None
    mock_file_record.filename = 'generated.png'

    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = mock_file_record

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo):
        # Execute and verify exception
        with pytest.raises(ValueError, match='No telegram_file_id'):
            await download_file_from_telegram(file_id, bot, session)


@pytest.mark.asyncio
async def test_download_file_from_telegram_api_error():
    """Test error handling when Telegram download fails.

    Should convert TelegramAPIError to user-friendly ValueError.
    """
    file_id = 'file_abc123'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock file record
    mock_file_record = Mock()
    mock_file_record.telegram_file_id = 'telegram_file_456'
    mock_file_record.filename = 'old_audio.mp3'

    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = mock_file_record

    # Mock Telegram API error
    from aiogram.exceptions import TelegramAPIError
    mock_method = Mock()
    bot.get_file.side_effect = TelegramAPIError(method=mock_method,
                                                message='File expired')

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo):
        # Execute and verify exception
        with pytest.raises(ValueError,
                           match='no longer available in Telegram') as exc_info:
            await download_file_from_telegram(file_id, bot, session)

        # Verify user-friendly message
        assert 'old_audio.mp3' in str(exc_info.value)
        assert '6 months' in str(exc_info.value)


# ============================================================================
# transcribe_audio() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_transcribe_audio_success_auto_language():
    """Test successful transcription with auto language detection.

    Flow:
    1. Get file metadata from database
    2. Download file from Telegram
    3. Call Whisper API with verbose_json
    4. Calculate cost ($0.006 per minute)
    5. Return transcript + metadata
    """
    file_id = 'file_abc123'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock file record
    mock_file_record = Mock()
    mock_file_record.telegram_file_id = 'telegram_file_456'
    mock_file_record.filename = 'voice.ogg'

    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = mock_file_record

    # Mock file download
    mock_audio_bytes = b'fake_audio_data'

    # Mock OpenAI client and response
    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.text = 'Hello, how are you?'
    mock_response.duration = 10.5  # 10.5 seconds
    mock_response.language = 'en'
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo), \
         patch('core.tools.transcribe_audio.download_file_from_telegram',
               return_value=mock_audio_bytes) as mock_download, \
         patch('core.tools.transcribe_audio.get_openai_async_client',
               return_value=mock_client):

        # Execute
        result = await transcribe_audio(file_id, bot, session, language='auto')

        # Verify result
        assert result['transcript'] == 'Hello, how are you?'
        assert result['language'] == 'en'
        assert result['duration'] == 10.5

        # Verify cost calculation: 10.5 sec = 0.175 min = $0.00105
        expected_cost = (10.5 / 60.0) * 0.006
        assert float(result['cost_usd']) == pytest.approx(expected_cost,
                                                          rel=1e-6)

        # Verify API call
        mock_download.assert_called_once_with(file_id, bot, session)
        mock_client.audio.transcriptions.create.assert_called_once()
        call_kwargs = \
            mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs['model'] == 'whisper-1'
        assert call_kwargs['language'] is None  # auto-detect
        assert call_kwargs['response_format'] == 'verbose_json'


@pytest.mark.asyncio
async def test_transcribe_audio_with_specific_language():
    """Test transcription with specified language parameter.

    Language parameter should be passed to Whisper API for better accuracy.
    """
    file_id = 'file_abc123'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock dependencies
    mock_file_record = Mock()
    mock_file_record.filename = 'speech_ru.ogg'
    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = mock_file_record

    mock_audio_bytes = b'audio_data'

    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.text = 'Привет, как дела?'
    mock_response.duration = 5.0
    mock_response.language = 'ru'
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo), \
         patch('core.tools.transcribe_audio.download_file_from_telegram',
               return_value=mock_audio_bytes), \
         patch('core.tools.transcribe_audio.get_openai_async_client',
               return_value=mock_client):

        # Execute with Russian language
        result = await transcribe_audio(file_id, bot, session, language='ru')

        # Verify language parameter passed
        call_kwargs = \
            mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs['language'] == 'ru'
        assert result['language'] == 'ru'


@pytest.mark.asyncio
async def test_transcribe_audio_file_not_found():
    """Test error when file not found in database."""
    file_id = 'file_nonexistent'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock repository returning None
    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = None

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo):
        # Execute and verify exception
        with pytest.raises(ValueError, match='File not found'):
            await transcribe_audio(file_id, bot, session)


@pytest.mark.asyncio
async def test_transcribe_audio_whisper_api_error():
    """Test error handling when Whisper API fails.

    Should propagate openai.APIError with proper logging.
    """
    file_id = 'file_abc123'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock dependencies
    mock_file_record = Mock()
    mock_file_record.filename = 'audio.mp3'
    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = mock_file_record

    mock_audio_bytes = b'audio_data'

    # Mock Whisper API error
    mock_client = AsyncMock()
    mock_request = Mock()
    api_error = openai.APIError(message='Whisper API failed',
                                request=mock_request,
                                body=None)
    mock_client.audio.transcriptions.create.side_effect = api_error

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo), \
         patch('core.tools.transcribe_audio.download_file_from_telegram',
               return_value=mock_audio_bytes), \
         patch('core.tools.transcribe_audio.get_openai_async_client',
               return_value=mock_client):

        # Execute and verify exception propagated
        with pytest.raises(openai.APIError, match='Whisper API failed'):
            await transcribe_audio(file_id, bot, session)


@pytest.mark.asyncio
async def test_transcribe_audio_generic_exception():
    """Test error handling for unexpected exceptions.

    Should catch and log any unexpected errors.
    """
    file_id = 'file_abc123'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock unexpected exception during file download
    with patch('db.repositories.user_file_repository.UserFileRepository') as \
            MockRepo:
        MockRepo.side_effect = RuntimeError('Unexpected database error')

        # Execute and verify exception propagated
        with pytest.raises(RuntimeError, match='Unexpected database error'):
            await transcribe_audio(file_id, bot, session)


@pytest.mark.asyncio
async def test_transcribe_audio_long_file_cost():
    """Test cost calculation for longer audio file.

    Verify cost calculation accuracy for various durations.
    """
    file_id = 'file_abc123'
    bot = AsyncMock()
    session = AsyncMock()

    # Mock dependencies
    mock_file_record = Mock()
    mock_file_record.filename = 'podcast.mp3'
    mock_repo = AsyncMock()
    mock_repo.get_by_claude_file_id.return_value = mock_file_record

    mock_audio_bytes = b'audio_data'

    mock_client = AsyncMock()
    mock_response = Mock()
    mock_response.text = 'Long podcast transcript...'
    mock_response.duration = 1800.0  # 30 minutes
    mock_response.language = 'en'
    mock_client.audio.transcriptions.create.return_value = mock_response

    with patch('db.repositories.user_file_repository.UserFileRepository',
               return_value=mock_repo), \
         patch('core.tools.transcribe_audio.download_file_from_telegram',
               return_value=mock_audio_bytes), \
         patch('core.tools.transcribe_audio.get_openai_async_client',
               return_value=mock_client):

        # Execute
        result = await transcribe_audio(file_id, bot, session)

        # Verify cost: 30 minutes = $0.18
        expected_cost = 30.0 * 0.006
        assert float(result['cost_usd']) == pytest.approx(expected_cost,
                                                          rel=1e-6)
        assert result['duration'] == 1800.0


# ============================================================================
# TRANSCRIBE_AUDIO_TOOL Definition Tests
# ============================================================================


def test_transcribe_audio_tool_structure():
    """Test that TRANSCRIBE_AUDIO_TOOL has correct structure."""
    assert TRANSCRIBE_AUDIO_TOOL['name'] == 'transcribe_audio'
    assert 'description' in TRANSCRIBE_AUDIO_TOOL
    assert 'input_schema' in TRANSCRIBE_AUDIO_TOOL


def test_transcribe_audio_tool_input_schema():
    """Test input schema structure."""
    schema = TRANSCRIBE_AUDIO_TOOL['input_schema']
    assert schema['type'] == 'object'
    assert 'properties' in schema
    assert 'file_id' in schema['properties']
    assert 'language' in schema['properties']
    assert schema['required'] == ['file_id']


def test_transcribe_audio_tool_description_complete():
    """Test that tool description includes all key sections."""
    desc = TRANSCRIBE_AUDIO_TOOL['description']

    # Verify key sections present
    assert '<purpose>' in desc
    assert '<when_to_use>' in desc
    assert '<supported_formats>' in desc
    assert '<output>' in desc
    assert '<examples>' in desc
    assert '<cost>' in desc
    assert '<limitations>' in desc
    assert '<best_practices>' in desc

    # Verify key information
    assert 'Whisper' in desc
    assert '$0.006 per minute' in desc
    assert '90+ languages' in desc
