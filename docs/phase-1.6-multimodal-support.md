# Phase 1.6: Multimodal Support (All File Types)

**Status:** ✅ **COMPLETE**

**Purpose:** Add support for ALL file types (audio, voice, video, arbitrary formats) with hybrid file storage architecture.

**Date:** January 10, 2026

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [New Modalities](#new-modalities)
- [Tools](#tools)
- [Implementation Stages](#implementation-stages)
- [Testing](#testing)
- [Related Documents](#related-documents)

---

## Overview

Phase 1.6 completes multimodal support by adding:
- 🎵 **Audio files** (MP3, FLAC, OGG, WAV)
- 🎤 **Voice messages** (with auto-transcription)
- 🎬 **Video files** (MP4, MOV, AVI)
- 📹 **Video notes** (round videos)
- 📄 **Arbitrary formats** (any file type)

### Prerequisites

- ✅ Phase 1.5: Tools framework (execute_python, analyze_image, analyze_pdf)
- ✅ Hybrid file storage (Files API + Telegram)
- ✅ OpenAI API key in secrets (for Whisper)

### Key Features

1. **Universal tool: transcribe_audio** - works with ANY audio/video
2. **Voice → Text** - automatic transcription for voice messages
3. **Telegram limits** - Premium detection (20MB/2GB)
4. **No auto-processing** - model decides when to process files
5. **Hybrid storage** - optimal for each use case

---

## Architecture

### Hybrid File Storage

Phase 1.6 maintains the hybrid approach from Phase 1.5:

```
┌─────────────────────────────────────────────────┐
│ USER uploads ANY file (photo/audio/video/etc)  │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
        ┌─────────────────────┐
        │  Bot downloads from │
        │      Telegram       │
        └─────────┬───────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
   Files API          Telegram Storage
  (claude_file_id)    (telegram_file_id)
        │                   │
        │                   │
┌───────┴────────┐  ┌───────┴────────┐
│ analyze_image  │  │ execute_python │
│ analyze_pdf    │  │ transcribe_    │
│ (direct ref)   │  │ audio (NEW!)   │
└────────────────┘  └────────────────┘
```

### When to Use What

| Tool | Source | File Types | Purpose |
|------|--------|-----------|---------|
| `analyze_image` | Files API | Images only | Fast vision analysis |
| `analyze_pdf` | Files API | PDF only | Fast document analysis |
| `execute_python` | Telegram | **ALL files** | Universal processing |
| `transcribe_audio` 🆕 | Telegram | Audio/Video | Speech-to-text |

### Why Hybrid?

**Files API** (images/PDF):
- ✅ Fast (direct reference, no download)
- ✅ Fewer tokens (vs base64 ~33% overhead)
- ✅ Optimized for vision/PDF
- ❌ TTL: 24 hours
- ❌ Cannot download user files
- ❌ Limited formats

**Telegram** (all files):
- ✅ TTL: ~6 months
- ✅ Supports ANY format
- ✅ Can download for execute_python
- ❌ Must download each time
- ❌ Size limits (20MB/2GB)

---

## New Modalities

### 1. Audio (Music Files)

**Telegram type:** `message.audio`
**Formats:** MP3, FLAC, OGG, M4A, WAV, AAC, etc.
**Handler:** `handle_audio()`

#### Workflow

```
User uploads song.flac (5.2 MB, 3:24) →
  ├─ Bot downloads from Telegram
  ├─ Bot uploads to Files API → claude_file_id
  ├─ Bot saves telegram_file_id + claude_file_id to database
  └─ Bot adds to context: "song.flac (audio, 3:24, 5.2 MB)"

User: "что это за песня?" →
  Model sees: "Available files: song.flac (audio, 3:24, 5.2 MB)"

  Model can:
    Option 1: transcribe_audio("file_abc") → get lyrics
    Option 2: execute_python(file_inputs=[song.flac]) → analyze metadata
```

**NO auto-transcription** - model decides if transcription needed.

#### Use Cases

- Identify song (metadata: artist, title, album)
- Extract lyrics (transcribe_audio)
- Analyze audio features (execute_python: tempo, key, loudness)
- Convert formats (execute_python: MP3 → FLAC)

---

### 2. Voice Messages ⭐ Special Handling

**Telegram type:** `message.voice`
**Format:** OGG/OPUS (Telegram proprietary)
**Handler:** `handle_voice()` with **auto-transcription**

#### Workflow (Automatic)

```
User sends voice message (15 seconds) →
  ├─ Bot downloads OGG file
  ├─ Bot transcribes with OpenAI Whisper API
  ├─ Bot saves as TEXT message (not file!)
  │   text_content = "привет как дела"
  ├─ Bot optionally saves audio to user_files
  └─ Model sees as REGULAR text message

Model responds to transcript as normal text!
```

#### Key Design Decision

**Voice → Text Conversion:**
- Voice messages are NOT treated as file attachments
- Transcript saved directly as `message.text_content`
- Model sees voice as regular text message
- Natural conversation flow (no tool calls needed)

#### Logging Example

```json
{"event": "voice_received", "duration": 15, "size_bytes": 234000}
{"event": "whisper_transcription", "transcript": "привет как дела", "duration_ms": 850}
{"event": "message_saved", "text_content": "привет как дела", "role": "user"}
{"event": "claude_response", "text": "Привет! Всё хорошо, спасибо!"}
```

#### Why Auto-Transcribe?

1. **Better UX** - model responds immediately to voice content
2. **Natural flow** - no extra tool calls needed
3. **Context** - transcript available in conversation history
4. **Searchable** - can search voice messages by content

#### Advanced Usage

If user needs detailed audio analysis:
```
User: "проанализируй мой голос с точки зрения эмоций"
Model: execute_python(file_inputs=[voice_17468.ogg])
  → analyze with librosa/parselmouth
  → detect pitch, tone, emotion
```

---

### 3. Video Files

**Telegram type:** `message.video`
**Formats:** MP4, MOV, AVI, MKV, WebM, etc.
**Handler:** `handle_video()`

#### Workflow

```
User uploads video.mp4 (45 MB, 1:30, 1920x1080) →
  ├─ Bot downloads from Telegram
  ├─ Bot uploads to Files API
  ├─ Bot saves telegram_file_id + claude_file_id
  └─ Bot adds to context: "video.mp4 (video, 1:30, 1920x1080, 45 MB)"

User: "что на видео?" →
  Model can use multiple approaches:

  Approach 1 - Visual analysis:
    execute_python(file_inputs=[video.mp4])
      → extract frames with ffmpeg/opencv
      → analyze key frames

  Approach 2 - Speech analysis:
    transcribe_audio("file_abc")
      → extract audio track
      → transcribe speech

  Approach 3 - Combined:
    1. transcribe_audio → understand dialogue
    2. execute_python → extract/analyze frames
    3. Combine insights
```

**NO auto-processing** - model decides what to analyze.

#### Use Cases

- Summarize video content (frames + speech)
- Extract speech/dialogue (transcribe_audio)
- Find specific scenes (execute_python: frame analysis)
- Generate thumbnails (execute_python: extract key frames)
- Convert formats (execute_python: ffmpeg)

---

### 4. Video Notes (Circles)

**Telegram type:** `message.video_note`
**Format:** MP4 (round video, Telegram specific)
**Handler:** `handle_video_note()`

Same as regular video, but typically shorter (up to 1 minute).

---

## Tools

### transcribe_audio (NEW!)

Universal audio transcription tool using OpenAI Whisper API.

#### Tool Definition

```python
{
    "name": "transcribe_audio",
    "description": """Transcribe audio from audio/video files using Whisper.

Use this to convert speech to text from:
- Audio files (MP3, FLAC, OGG, WAV, M4A, AAC, etc.)
- Video files (automatically extracts audio track)
- Voice messages (if detailed analysis needed beyond auto-transcript)

Supports 90+ languages with automatic detection. Returns:
- Full transcript text
- Detected language
- Duration
- Optional: detailed segments with timestamps

Examples:
- Get lyrics from song: transcribe_audio("song_123")
- Extract dialogue from video: transcribe_audio("video_456")
- Analyze voice message: transcribe_audio("voice_789")

Cost: ~$0.006 per minute of audio.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "Claude file_id from 'Available files' section"
            },
            "language": {
                "type": "string",
                "description": "Language code for better accuracy (auto/ru/en/es/etc). Default: auto-detect",
                "default": "auto"
            }
        },
        "required": ["file_id"]
    }
}
```

#### Implementation

```python
# bot/core/tools/transcribe_audio.py

async def transcribe_audio(file_id: str,
                          language: str = "auto",
                          bot: 'Bot',
                          session: 'AsyncSession') -> Dict[str, Any]:
    """Transcribe audio using OpenAI Whisper API.

    Args:
        file_id: Claude file_id (from Available files).
        language: Language code or "auto" for detection.
        bot: Telegram Bot for downloading.
        session: Database session.

    Returns:
        {
            "transcript": "полный текст расшифровки",
            "language": "ru",
            "duration": 15.3,
            "segments": [...] (optional: detailed timestamps)
        }

    Raises:
        ValueError: If file not found.
        openai.APIError: If Whisper API fails.
    """
    # 1. Get file from database
    repo = UserFileRepository(session)
    file_record = await repo.get_by_claude_file_id(file_id)

    # 2. Download from Telegram (similar to execute_python)
    file_bytes = await download_from_telegram(
        bot, file_record.telegram_file_id)

    # 3. Call OpenAI Whisper API
    client = openai.AsyncOpenAI(api_key=read_secret("openai_api_key"))

    response = await client.audio.transcriptions.create(
        model="whisper-1",
        file=(file_record.filename, file_bytes),
        language=None if language == "auto" else language,
        response_format="verbose_json"  # includes timestamps
    )

    # 4. Return transcript + metadata
    return {
        "transcript": response.text,
        "language": response.language,
        "duration": response.duration,
        "segments": response.segments  # detailed timestamps
    }
```

#### Cost Tracking

- Model: `whisper-1`
- Pricing: **$0.006 per minute** of audio
- Example: 15 sec voice = **$0.0015**
- Example: 3 min song = **$0.018**

Store in logs:
```json
{"event": "transcribe_audio.success",
 "duration": 15.3,
 "cost_usd": 0.0015}
```

---

## Implementation Stages

### Stage 1: transcribe_audio Tool ✅

**Files to create:**
- `bot/core/tools/transcribe_audio.py` - implementation
- Update `bot/core/tools/registry.py` - add to TOOL_DEFINITIONS

**Tasks:**
1. Implement `transcribe_audio()` function
2. Add download logic (reuse from execute_python)
3. OpenAI Whisper API integration
4. Error handling (API failures, timeouts)
5. Cost tracking
6. Tool definition for Claude
7. Add to registry

**OpenAI API:**
```python
import openai
from bot.main import read_secret

client = openai.AsyncOpenAI(api_key=read_secret("openai_api_key"))

response = await client.audio.transcriptions.create(
    model="whisper-1",
    file=(filename, audio_bytes),
    language=None,  # auto-detect
    response_format="verbose_json"
)
```

**Secrets:**
- Uses existing `secrets/openai_api_key.txt`
- No new secrets needed ✅

---

### Stage 2: Voice Handler (Auto-Transcription) ✅

**File to update:**
- `bot/telegram/handlers/files.py` - add `handle_voice()`

**Tasks:**
1. Create `handle_voice()` handler
2. Download voice from Telegram
3. Transcribe with Whisper
4. Save as TEXT message (not file)
5. Optionally save audio to user_files
6. Add logging

**Implementation:**

```python
@router.message(F.voice & ~F.caption)
async def handle_voice(message: types.Message, session: AsyncSession) -> None:
    """Handle voice messages with automatic transcription.

    Voice messages are converted to text automatically for better UX.
    Model sees transcript as regular text message.

    Args:
        message: Telegram message with voice.
        session: Database session.
    """
    if not message.from_user or not message.voice:
        return

    user_id = message.from_user.id
    voice = message.voice

    logger.info("voice_handler.received",
                user_id=user_id,
                duration=voice.duration,
                file_size=voice.file_size)

    # Download voice file
    file_info = await message.bot.get_file(voice.file_id)
    file_bytes_io = await message.bot.download_file(file_info.file_path)
    audio_bytes = file_bytes_io.read()

    # Transcribe with Whisper
    try:
        transcript = await transcribe_with_whisper(audio_bytes, language="auto")

        logger.info("voice_handler.transcribed",
                    user_id=user_id,
                    transcript=transcript[:100],
                    duration=voice.duration)

        # Save as TEXT message (goes through claude handler)
        # Create synthetic text message
        from aiogram.types import Message

        # Update message text for processing
        message.text = transcript

        # Process as regular text message
        # (claude handler will pick it up automatically)

        logger.info("voice_handler.complete",
                    user_id=user_id,
                    transcript_length=len(transcript))

    except Exception as e:
        logger.error("voice_handler.transcription_failed",
                     user_id=user_id,
                     error=str(e),
                     exc_info=True)
        await message.answer("⚠️ Failed to transcribe voice message")
```

**Note:** Voice messages flow through claude handler like regular text.

---

### Stage 3: Audio/Video Handlers ✅

**File to update:**
- `bot/telegram/handlers/files.py`

**Tasks:**
1. Add `handle_audio()` - music files
2. Add `handle_video()` - video files
3. Add `handle_video_note()` - round videos
4. Reuse upload logic from existing handlers

**Implementation:**

```python
@router.message(F.audio & ~F.caption)
async def handle_audio(message: types.Message, session: AsyncSession) -> None:
    """Handle audio files (music).

    NO auto-transcription - model decides if transcription needed.
    """
    # Similar to document handler
    # Upload to Files API + save to database

@router.message(F.video & ~F.caption)
async def handle_video(message: types.Message, session: AsyncSession) -> None:
    """Handle video files.

    NO auto-processing - model can:
    - execute_python: extract frames, analyze visuals
    - transcribe_audio: get speech/dialogue
    """
    # Similar to document handler

@router.message(F.video_note & ~F.caption)
async def handle_video_note(message: types.Message,
                            session: AsyncSession) -> None:
    """Handle video notes (round videos).

    Same as regular video.
    """
    # Similar to video handler
```

---

### Stage 4: File Size Limits (Telegram Premium) ✅

**File to update:**
- `bot/telegram/handlers/files.py`

**Tasks:**
1. Add Premium detection helper
2. Update all handlers to check limits
3. Return clear error messages

**Implementation:**

```python
def get_file_size_limit(user: types.User) -> int:
    """Get file size limit based on user Premium status.

    Telegram limits:
    - Free: 20 MB
    - Premium: 2 GB

    Args:
        user: Telegram user object.

    Returns:
        Max file size in bytes.
    """
    if user.is_premium:
        return 2 * 1024 * 1024 * 1024  # 2 GB
    return 20 * 1024 * 1024  # 20 MB

# Usage in handlers:
if file_size > get_file_size_limit(message.from_user):
    limit = "2 GB" if message.from_user.is_premium else "20 MB"
    await message.answer(f"⚠️ File too large (max {limit})")
    return
```

---

### Stage 5: Update FileType Enum ✅

**File to update:**
- `bot/db/models/user_file.py`

**Tasks:**
1. Add new file types
2. Create Alembic migration

**Implementation:**

```python
class FileType(enum.Enum):
    """File type categories."""
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"
    AUDIO = "audio"       # 🆕 Music files (MP3, FLAC, etc)
    VOICE = "voice"       # 🆕 Voice messages (OGG)
    VIDEO = "video"       # 🆕 Video files (MP4, MOV, etc)
    GENERATED = "generated"
```

**Migration:**
```python
# postgres/alembic/versions/XXX_phase_1_6_add_audio_video_types.py

def upgrade():
    # Add new enum values
    op.execute("ALTER TYPE filetype ADD VALUE 'audio'")
    op.execute("ALTER TYPE filetype ADD VALUE 'voice'")
    op.execute("ALTER TYPE filetype ADD VALUE 'video'")

def downgrade():
    # Cannot remove enum values in PostgreSQL
    # Would need to recreate enum type
    pass
```

---

### Stage 6: Update System Prompt ✅

**File to update:**
- `bot/config.py` - GLOBAL_SYSTEM_PROMPT

**Tasks:**
1. Add transcribe_audio tool description
2. Update file handling instructions
3. Add examples

**Addition to system prompt:**

```python
GLOBAL_SYSTEM_PROMPT = (
    # ... existing content ...

    "# Available Tools (Phase 1.6)\n"
    "- analyze_image: Fast image analysis (direct Files API)\n"
    "- analyze_pdf: Fast PDF analysis (direct Files API)\n"
    "- transcribe_audio: Speech-to-text for audio/video files 🆕\n"
    "- execute_python: Universal file processing (any format)\n"
    "- web_search, web_fetch: Web access\n\n"

    "# Working with Files\n"
    "Available files show metadata:\n"
    "- Images: 'photo.jpg (image, 1920x1080, 2.4 MB)'\n"
    "- PDFs: 'document.pdf (pdf, 10 pages, 5.1 MB)'\n"
    "- Audio: 'song.mp3 (audio, 3:24, 5.2 MB)' 🆕\n"
    "- Video: 'video.mp4 (video, 1:30, 1920x1080, 45 MB)' 🆕\n\n"

    "Processing guidelines:\n"
    "- Images → analyze_image (fastest)\n"
    "- PDFs → analyze_pdf (fastest)\n"
    "- Audio transcription → transcribe_audio 🆕\n"
    "- Video frames → execute_python\n"
    "- Video speech → transcribe_audio 🆕\n"
    "- Any other format → execute_python\n\n"

    "Example workflows:\n"
    "1. Video analysis:\n"
    "   - transcribe_audio(video.mp4) → get dialogue\n"
    "   - execute_python(extract frames) → analyze visuals\n"
    "   - Combine insights for full understanding\n\n"

    "2. Song identification:\n"
    "   - execute_python(extract metadata) → artist, title\n"
    "   - transcribe_audio(song.mp3) → get lyrics\n"
)
```

---

### Stage 7: Available Files Context Format ✅

**File to update:**
- `bot/telegram/handlers/claude.py` - `format_files_section()`

**Tasks:**
1. Update format for new file types
2. Add duration for audio/video
3. Add transcript preview for voice (optional)

**Implementation:**

```python
def format_files_section(files: List[UserFile]) -> str:
    """Format available files for system prompt.

    Examples:
    - photo.jpg (image, 1920x1080, 2.4 MB)
    - song.mp3 (audio, 3:24, 5.2 MB)
    - voice_123.ogg (voice, 15s, transcript: 'привет как дела')
    - video.mp4 (video, 1:30, 1920x1080, 45 MB)
    """
    if not files:
        return ""

    lines = ["# Available Files\n"]

    for file in files:
        # Basic info
        parts = [
            f"{file.filename}",
            f"({file.file_type.value}",
        ]

        # Add type-specific metadata
        metadata = file.file_metadata or {}

        if file.file_type == FileType.IMAGE:
            if "width" in metadata and "height" in metadata:
                parts.append(f"{metadata['width']}x{metadata['height']}")

        elif file.file_type == FileType.PDF:
            if "page_count" in metadata:
                parts.append(f"{metadata['page_count']} pages")

        elif file.file_type in [FileType.AUDIO, FileType.VOICE]:
            if "duration" in metadata:
                duration = format_duration(metadata["duration"])
                parts.append(duration)

            # Add transcript preview for voice
            if file.file_type == FileType.VOICE and "transcript" in metadata:
                transcript = metadata["transcript"][:50]
                parts.append(f"transcript: '{transcript}...'")

        elif file.file_type == FileType.VIDEO:
            if "duration" in metadata:
                duration = format_duration(metadata["duration"])
                parts.append(duration)
            if "width" in metadata and "height" in metadata:
                parts.append(f"{metadata['width']}x{metadata['height']}")

        # Add file size
        parts.append(format_size(file.file_size))

        # Build line
        info = ", ".join(parts) + ")"
        lines.append(f"- {info} [file_id: {file.claude_file_id}]")

    return "\n".join(lines)

def format_duration(seconds: float) -> str:
    """Format duration in MM:SS format.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like "3:24" or "1:30:45".
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
```

---

## Testing

### Test Cases

#### 1. Audio Files
```
✅ Upload MP3 → verify Files API upload
✅ Upload FLAC → verify Telegram storage
✅ Ask model to identify song → execute_python
✅ Ask for lyrics → transcribe_audio tool
✅ Verify metadata (artist, album, duration)
```

#### 2. Voice Messages
```
✅ Send voice (Russian) → verify auto-transcription
✅ Check message saved as text
✅ Model responds to transcript
✅ Send voice (English) → verify auto-detect
✅ Send voice (mixed languages) → verify handling
```

#### 3. Video Files
```
✅ Upload video → verify upload
✅ Ask "what's in video" → execute_python + transcribe_audio
✅ Ask for dialogue → transcribe_audio only
✅ Ask for specific frame → execute_python
✅ Large video (>20MB) → Premium check
```

#### 4. Premium Limits
```
✅ Free user uploads 25MB → reject
✅ Premium user uploads 25MB → accept
✅ Premium user uploads 3GB → reject (>2GB)
```

#### 5. Tool Combinations
```
✅ Video: transcribe_audio + execute_python (frames)
✅ Audio: transcribe_audio + execute_python (metadata)
✅ Multiple files: mix of all types
```

#### 6. Error Handling
```
✅ Whisper API timeout → graceful error
✅ Invalid audio format → clear message
✅ Corrupted file → appropriate error
✅ File expired (Telegram) → TTL message
```

### Integration Tests

```python
# tests/integration/test_multimodal.py

async def test_voice_auto_transcription():
    """Voice message should be auto-transcribed to text."""
    # Send voice message
    # Verify Whisper API called
    # Verify text message saved
    # Verify model responds to transcript

async def test_transcribe_audio_tool():
    """transcribe_audio tool should work with audio/video."""
    # Upload audio file
    # Model calls transcribe_audio
    # Verify transcript returned
    # Verify cost tracked

async def test_video_multimodal():
    """Video should support both visual and audio analysis."""
    # Upload video
    # Model calls transcribe_audio → dialogue
    # Model calls execute_python → frames
    # Verify combined analysis

async def test_premium_limits():
    """File size limits should respect Premium status."""
    # Free user: 20MB limit
    # Premium user: 2GB limit
    # Verify rejections/acceptances
```

---

## Related Documents

- [Phase 1.5: Multimodal + Tools](phase-1.5-multimodal-tools.md) - Foundation (execute_python, analyze_image, analyze_pdf)
- [Phase 1.4: Claude Advanced API](phase-1.4-claude-advanced-api.md) - API best practices
- [Bot Structure](bot-structure.md) - Overall architecture
- [Database](database.md) - user_files table schema

---

## Summary

Phase 1.6 completes multimodal support:

✅ **All file types** supported (audio, voice, video, arbitrary)
✅ **Hybrid storage** (Files API + Telegram) for optimal performance
✅ **transcribe_audio tool** for universal speech-to-text
✅ **Voice → Text** automatic conversion for natural UX
✅ **Premium detection** for proper file size limits
✅ **Universal approach** - model decides how to process files

**Result:** Bot can handle ANY file type with appropriate tools and processing methods.
