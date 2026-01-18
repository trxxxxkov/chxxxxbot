"""Transcribe audio tool using OpenAI Whisper API.

This module implements the transcribe_audio tool for speech-to-text
transcription of audio and video files using OpenAI's Whisper model.

NO __init__.py - use direct import:
    from core.tools.transcribe_audio import (
        transcribe_audio,
        TRANSCRIBE_AUDIO_TOOL
    )
"""

import io
from typing import Any, Dict, TYPE_CHECKING

from core.clients import get_openai_async_client
from core.pricing import calculate_whisper_cost
from core.pricing import cost_to_float
import openai
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


async def download_file_from_telegram(file_id: str, bot: 'Bot',
                                      session: 'AsyncSession') -> bytes:
    """Download file from Telegram storage.

    Args:
        file_id: Claude file_id (used to lookup in database).
        bot: Telegram Bot instance for downloading files.
        session: Database session for querying file metadata.

    Returns:
        File content as bytes.

    Raises:
        ValueError: If file not found or no longer available.
        TelegramAPIError: If Telegram download fails.

    Note:
        Telegram stores files for ~6 months of inactivity.
    """
    # Import here to avoid circular dependencies
    from aiogram.exceptions import \
        TelegramAPIError  # pylint: disable=import-outside-toplevel
    from db.repositories.user_file_repository import \
        UserFileRepository  # pylint: disable=import-outside-toplevel

    logger.info("tools.transcribe_audio.downloading_file", file_id=file_id)

    # Get file metadata from database
    repo = UserFileRepository(session)
    file_record = await repo.get_by_claude_file_id(file_id)

    if not file_record:
        raise ValueError(f"File not found in database: {file_id}")

    if not file_record.telegram_file_id:
        raise ValueError(f"No telegram_file_id for file {file_id}. "
                         "Cannot download from Telegram.")

    try:
        logger.info("tools.transcribe_audio.telegram_download",
                    telegram_file_id=file_record.telegram_file_id,
                    filename=file_record.filename)

        # Get file info from Telegram
        file_info = await bot.get_file(file_record.telegram_file_id)

        # Download file content
        file_bytes_io = await bot.download_file(file_info.file_path)

        # Read BytesIO to bytes
        file_bytes = file_bytes_io.read()

        logger.info("tools.transcribe_audio.telegram_download_success",
                    file_id=file_id,
                    filename=file_record.filename,
                    size_bytes=len(file_bytes))

        return file_bytes

    except TelegramAPIError as e:
        logger.error("tools.transcribe_audio.telegram_download_failed",
                     file_id=file_id,
                     telegram_file_id=file_record.telegram_file_id,
                     filename=file_record.filename,
                     error=str(e),
                     exc_info=True)

        # User-friendly error message
        raise ValueError(
            f"File '{file_record.filename}' is no longer available in "
            "Telegram. Files are stored for approximately 6 months. "
            "Please re-upload the file to continue.") from e


async def transcribe_audio(file_id: str,
                           bot: 'Bot',
                           session: 'AsyncSession',
                           language: str = "auto") -> Dict[str, Any]:
    """Transcribe audio using OpenAI Whisper API.

    Uses OpenAI's Whisper model to convert speech to text from audio/video
    files. Supports 90+ languages with automatic detection. Returns full
    transcript with metadata including detected language, duration, and
    optional detailed segments with timestamps.

    Args:
        file_id: Claude file_id (from Available files list in conversation).
        bot: Telegram Bot instance for downloading files.
        session: Database session for querying file metadata.
        language: Language code for better accuracy (e.g., "ru", "en", "es")
            or "auto" for automatic detection. Default: "auto".

    Returns:
        Dictionary containing:
        - transcript: Full text of transcription.
        - language: Detected or specified language code.
        - duration: Audio duration in seconds.
        - cost_usd: API cost for this transcription.

    Raises:
        ValueError: If file not found or not available.
        openai.APIError: If Whisper API call fails.

    Examples:
        >>> result = await transcribe_audio(
        ...     file_id="file_abc123...",
        ...     bot=bot,
        ...     session=session,
        ...     language="auto"
        ... )
        >>> print(result['transcript'])
        'привет как дела'
        >>> print(f"Language: {result['language']}, Cost: ${result['cost_usd']}")
        Language: ru, Cost: $0.0015

    Cost:
        Whisper model pricing: $0.006 per minute of audio.
        - 15 sec voice message: ~$0.0015
        - 3 min song: ~$0.018
        - 1 hour podcast: ~$0.36
    """
    try:
        logger.info("tools.transcribe_audio.called",
                    file_id=file_id,
                    language=language)

        # Import here to avoid circular dependencies
        from db.repositories.user_file_repository import \
            UserFileRepository  # pylint: disable=import-outside-toplevel

        # Get file metadata
        repo = UserFileRepository(session)
        file_record = await repo.get_by_claude_file_id(file_id)

        if not file_record:
            raise ValueError(f"File not found: {file_id}")

        # Download file from Telegram
        audio_bytes = await download_file_from_telegram(file_id, bot, session)

        # Use centralized client factory
        client = get_openai_async_client()

        # Prepare file for Whisper API
        # Whisper expects file-like object with filename
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = file_record.filename

        # Call Whisper API
        logger.info("tools.transcribe_audio.calling_whisper",
                    file_id=file_id,
                    filename=file_record.filename,
                    size_bytes=len(audio_bytes))

        response = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=None if language == "auto" else language,
            response_format="verbose_json"  # Includes duration and segments
        )

        # Use centralized pricing calculation
        duration = response.duration
        cost_usd = calculate_whisper_cost(duration)

        logger.info("tools.transcribe_audio.success",
                    file_id=file_id,
                    filename=file_record.filename,
                    transcript_length=len(response.text),
                    detected_language=response.language,
                    duration=duration,
                    cost_usd=cost_to_float(cost_usd))

        return {
            "transcript": response.text,
            "language": response.language,
            "duration": duration,
            "cost_usd": f"{cost_to_float(cost_usd):.6f}"
        }

    except openai.APIError as e:
        logger.error("tools.transcribe_audio.whisper_api_failed",
                     file_id=file_id,
                     error=str(e),
                     exc_info=True)
        raise

    except Exception as e:
        logger.error("tools.transcribe_audio.failed",
                     file_id=file_id,
                     error=str(e),
                     exc_info=True)
        raise


# Tool definition for Claude API (anthropic tools format)
TRANSCRIBE_AUDIO_TOOL = {
    "name":
        "transcribe_audio",
    "description":
        """Transcribe audio from audio/video files using OpenAI Whisper.

<purpose>
Convert speech to text from any audio or video file. Supports 90+ languages
with automatic detection. Essential for understanding spoken content in
user-uploaded files.
</purpose>

<when_to_use>
Use this tool when:
- User asks about spoken content in audio/video files
- Extracting lyrics from songs
- Getting dialogue/narration from videos
- Transcribing voice messages (for detailed analysis beyond auto-transcript)
- Converting any speech to text for further processing

Note: Voice messages are AUTO-TRANSCRIBED on receipt. Use this tool only
if you need the detailed audio analysis or if the auto-transcript wasn't saved.
</when_to_use>

<supported_formats>
Audio formats: MP3, FLAC, OGG, WAV, M4A, AAC, OPUS, WebM
Video formats: MP4, MOV, AVI, MKV, WebM (audio track extracted automatically)
Voice messages: OGG/OPUS (Telegram format)

The tool automatically extracts audio from video files - you can transcribe
videos directly without manual extraction.
</supported_formats>

<output>
Returns:
- transcript: Full text of transcription
- language: Detected language code (ru, en, es, etc.)
- duration: Audio duration in seconds
- cost_usd: API cost for this transcription

The transcript is optimized for readability (punctuation, capitalization).
</output>

<examples>
Example 1 - Song lyrics:
  User uploads: song.mp3
  You call: transcribe_audio("file_abc123")
  Returns: Full lyrics as text

Example 2 - Video dialogue:
  User uploads: interview.mp4
  You call: transcribe_audio("file_def456")
  Returns: Full spoken dialogue from video

Example 3 - Multi-language detection:
  User uploads: mixed_language.mp3
  You call: transcribe_audio("file_ghi789", language="auto")
  Returns: Transcript with auto-detected language
</examples>

<cost>
Pricing: $0.006 per minute of audio
- 15 sec voice message: ~$0.0015
- 3 min song: ~$0.018
- 10 min video: ~$0.06
- 1 hour podcast: ~$0.36

Cost is automatically tracked and logged.
</cost>

<limitations>
- Max file size: 25 MB (OpenAI limit)
- If file too large, use execute_python to split audio first
- Background noise may affect accuracy
- Multiple overlapping speakers may reduce quality
- Non-speech audio (music only) returns empty or minimal text
</limitations>

<best_practices>
1. Use language parameter if you know the language (better accuracy)
2. For long audio (>10 min), inform user about processing time
3. For videos, consider if transcription is needed or visual analysis sufficient
4. Combine with execute_python for advanced audio processing (pitch, tempo, etc.)
</best_practices>

API: OpenAI Whisper (whisper-1 model)
Language support: 90+ languages including English, Russian, Spanish, French,
German, Chinese, Japanese, and many more.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_id": {
                "type":
                    "string",
                "description":
                    ("Claude file_id from 'Available files' section in "
                     "conversation context. This is the unique identifier "
                     "for the file you want to transcribe.")
            },
            "language": {
                "type":
                    "string",
                "description":
                    ("Language code for better transcription accuracy. "
                     "Use 'auto' for automatic detection (default), or specify "
                     "ISO 639-1 code: 'ru' (Russian), 'en' (English), "
                     "'es' (Spanish), 'fr' (French), 'de' (German), "
                     "'zh' (Chinese), 'ja' (Japanese), etc. "
                     "Specifying language improves accuracy and speed.")
            }
        },
        "required": ["file_id"]
    }
}


def format_transcribe_audio_result(
    tool_input: dict,
    result: dict,
) -> str:
    """Format transcribe_audio result for user display.

    Args:
        tool_input: The input parameters (file_id, language).
        result: The result dictionary with transcript, duration, language.

    Returns:
        Formatted system message string.
    """
    if "error" in result:
        error = result.get("error", "unknown error")
        preview = error[:80] + "..." if len(error) > 80 else error
        return f"\n[❌ Ошибка транскрипции: {preview}]\n"

    duration = result.get("duration", 0)
    language = result.get("language", "")
    lang_info = f", {language}" if language else ""
    return f"\n[🎤 Транскрибировано: {duration:.0f}s{lang_info}]\n"


# Unified tool configuration
from core.tools.base import ToolConfig  # pylint: disable=wrong-import-position

TOOL_CONFIG = ToolConfig(
    name="transcribe_audio",
    definition=TRANSCRIBE_AUDIO_TOOL,
    executor=transcribe_audio,
    emoji="🎤",
    needs_bot_session=True,
    format_result=format_transcribe_audio_result,
)
