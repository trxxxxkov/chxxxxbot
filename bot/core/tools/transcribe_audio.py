"""Transcribe audio tool using OpenAI Whisper API.

This module implements the transcribe_audio tool for speech-to-text
transcription of audio and video files using OpenAI's Whisper model.

Phase 3.2: Uses unified FileManager for downloads with Redis caching.

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


async def transcribe_audio(
        file_id: str,
        bot: 'Bot',
        session: 'AsyncSession',
        thread_id: int | None = None,  # pylint: disable=unused-argument
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
        thread_id: Thread ID (unused, for interface consistency).
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
        from core.file_manager import \
            FileManager  # pylint: disable=import-outside-toplevel
        from db.repositories.user_file_repository import \
            UserFileRepository  # pylint: disable=import-outside-toplevel

        # Get file metadata
        repo = UserFileRepository(session)
        file_record = await repo.get_by_claude_file_id(file_id)

        if not file_record:
            raise ValueError(f"File not found: {file_id}")

        # Download file using unified FileManager (with caching)
        file_manager = FileManager(bot, session)
        audio_bytes = await file_manager.download_by_claude_id(
            file_id,
            filename=file_record.filename,
            use_cache=True,
        )

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
        # OpenAI Whisper API failures are external service issues
        logger.info("tools.transcribe_audio.whisper_api_failed",
                    file_id=file_id,
                    error=str(e))
        raise

    except Exception as e:
        # External service failures, not internal bugs
        logger.info("tools.transcribe_audio.failed",
                    file_id=file_id,
                    error=str(e))
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
        Formatted system message string (without newlines - handled by caller).
    """
    if "error" in result:
        error = result.get("error", "unknown error")
        preview = error[:80] + "..." if len(error) > 80 else error
        return f"[❌ Ошибка транскрипции: {preview}]"

    duration = result.get("duration", 0)
    language = result.get("language", "")
    lang_info = f", {language}" if language else ""
    return f"[🎤 Транскрибировано: {duration:.0f}s{lang_info}]"


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
