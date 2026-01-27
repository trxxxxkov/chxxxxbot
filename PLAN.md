# Universal Chat Action Architecture Plan

## Executive Summary

Redesign the chat action system to provide a **centralized, context-aware, automatic** mechanism for showing appropriate Telegram status indicators across all bot operations.

---

## Current State Analysis

### Problems Identified

1. **Scattered Implementation** - Chat actions called from 5+ different files with inconsistent patterns
2. **Manual Action Selection** - Each callsite manually chooses action type
3. **No MIME-Type Awareness** - Must manually map file types to actions
4. **Direct API Calls** - Some places bypass helper functions (claude.py:1060)
5. **No Operation Phases** - Can't express "typing → uploading → typing" transitions
6. **No Concurrent Operation Support** - No way to track multiple parallel operations
7. **Repeated Context Passing** - bot, chat_id, thread_id passed everywhere

### Current Usage Map

| File | Function | Pattern |
|------|----------|---------|
| normalizer.py | Media processing | `send_action()` - single shot |
| claude.py | Streaming | `continuous_action()` - context |
| claude_tools.py | Tool execution | `continuous_action()` - context |
| claude_files.py | File delivery | `continuous_action()` - context |

---

## Proposed Architecture

### Core Principle: **Scoped Action Manager**

Each operation creates a "scope" that automatically manages chat actions based on:
- Current operation type (generating, uploading, processing)
- File MIME type (auto-detect photo vs document vs video)
- Phase transitions (automatically switch between actions)

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         ChatActionManager                            │
│  (Per-chat singleton managing all action state)                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │  ActionScope    │    │  ActionScope    │    │  ActionScope    │  │
│  │  (Streaming)    │    │  (Tool exec)    │    │  (File send)    │  │
│  │  action=typing  │    │  action=typing  │    │  action=upload_*│  │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘  │
│           │                      │                      │           │
│           └──────────────────────┼──────────────────────┘           │
│                                  ▼                                   │
│                    ┌─────────────────────────┐                      │
│                    │   ActionLoop (async)    │                      │
│                    │   Refreshes every 4s    │                      │
│                    │   Uses highest priority │                      │
│                    └─────────────────────────┘                      │
│                                  │                                   │
└──────────────────────────────────┼───────────────────────────────────┘
                                   ▼
                         Telegram Bot API
                       send_chat_action()
```

---

## Module Structure

### New File: `telegram/chat_action/manager.py`

```python
from typing import Optional, TYPE_CHECKING
from weakref import WeakValueDictionary
from telegram.pipeline.models import MediaType
from db.models.user_file import FileType
from .types import ActionPhase, ActionPriority, FileTypeHint
from .scope import ActionScope

if TYPE_CHECKING:
    from aiogram import Bot


class ChatActionManager:
    """Centralized manager for chat actions in a single chat.

    Features:
    - Single action loop per chat (no duplicate API calls)
    - Priority-based action resolution (upload > typing)
    - Automatic file type based action selection (via MediaType/FileType enums)
    - Nested scope support for complex operations
    - MIME fallback when only string available

    Usage:
        manager = ActionManager.get(bot, chat_id, thread_id)

        async with manager.generating():
            # Shows "typing" indicator
            async with manager.uploading(file_type=MediaType.IMAGE):
                # Shows "upload_photo" indicator
            # Back to "typing"
    """

    # Global registry of active managers (weak refs for auto-cleanup)
    _registry: WeakValueDictionary[tuple, "ChatActionManager"] = WeakValueDictionary()

    @classmethod
    def get(
        cls,
        bot: "Bot",
        chat_id: int,
        thread_id: Optional[int] = None,
    ) -> "ChatActionManager":
        """Get or create manager for chat/thread.

        Args:
            bot: Telegram Bot instance.
            chat_id: Chat ID.
            thread_id: Forum topic ID (optional).

        Returns:
            ChatActionManager instance (reused if exists).
        """
        key = (chat_id, thread_id)
        if key not in cls._registry:
            cls._registry[key] = cls(bot, chat_id, thread_id)
        return cls._registry[key]

    def __init__(
        self,
        bot: "Bot",
        chat_id: int,
        thread_id: Optional[int] = None,
    ):
        self.bot = bot
        self.chat_id = chat_id
        self.thread_id = thread_id
        self._scope_stack: list[ActionScope] = []
        self._loop_task: Optional[asyncio.Task] = None

    # === High-level convenience methods ===

    def generating(self) -> ActionScope:
        """Scope for text generation (typing indicator)."""
        return ActionScope(self, ActionPhase.GENERATING)

    def uploading(
        self,
        file_type: FileTypeHint = None,
        *,
        mime_type: Optional[str] = None,
    ) -> ActionScope:
        """Scope for file upload to user.

        Args:
            file_type: MediaType or FileType enum.
            mime_type: MIME string fallback if enum not available.
        """
        return ActionScope(
            self, ActionPhase.UPLOADING,
            file_type=file_type, mime_type=mime_type,
            priority=ActionPriority.HIGH,
        )

    def downloading(
        self,
        file_type: FileTypeHint = None,
        *,
        mime_type: Optional[str] = None,
    ) -> ActionScope:
        """Scope for file download from user.

        Args:
            file_type: MediaType enum (preferred).
            mime_type: MIME string fallback.
        """
        return ActionScope(
            self, ActionPhase.DOWNLOADING,
            file_type=file_type, mime_type=mime_type,
        )

    def processing(
        self,
        file_type: FileTypeHint = None,
        *,
        mime_type: Optional[str] = None,
    ) -> ActionScope:
        """Scope for media processing (transcription, OCR).

        Args:
            file_type: MediaType enum.
            mime_type: MIME string fallback.
        """
        return ActionScope(
            self, ActionPhase.PROCESSING,
            file_type=file_type, mime_type=mime_type,
        )

    def searching(self) -> ActionScope:
        """Scope for search operations."""
        return ActionScope(self, ActionPhase.SEARCHING)

    # === Low-level scope management ===

    async def push_scope(
        self,
        phase: ActionPhase,
        file_type: FileTypeHint = None,
        mime_type: Optional[str] = None,
        priority: ActionPriority = ActionPriority.NORMAL,
    ) -> str:
        """Push new scope onto stack and update action loop."""
        ...

    async def pop_scope(self, scope_id: str) -> None:
        """Pop scope from stack and update action loop."""
        ...
```

### New File: `telegram/chat_action/types.py`

```python
from enum import Enum, auto
from typing import Union

# Import existing file type enums from project
from telegram.pipeline.models import MediaType
from db.models.user_file import FileType


class ActionPhase(Enum):
    """Semantic operation phase (what bot is DOING).

    This represents the PHASE of operation, not the file type.
    File type is determined separately via MediaType/FileType.
    """
    IDLE = auto()           # No action needed
    GENERATING = auto()     # Thinking/writing text (typing)
    PROCESSING = auto()     # Processing input - transcription, OCR (record_*)
    UPLOADING = auto()      # Sending file to user (upload_*)
    DOWNLOADING = auto()    # Receiving file from user (record_* or upload_*)
    SEARCHING = auto()      # Web search / location lookup (find_location)


class ActionPriority(Enum):
    """Priority for concurrent operations."""
    LOW = 1       # Background processing
    NORMAL = 2    # Standard generation
    HIGH = 3      # File transfer (user waiting to see file)


# Unified file type alias - accepts both enum types
FileTypeHint = Union[MediaType, FileType, None]


# Resolution table using existing enum types
# Key: (ActionPhase, FileTypeHint) → ChatAction string
# None as file type = default for that phase

ACTION_RESOLUTION_TABLE: dict[tuple, str] = {
    # === GENERATING: Always typing (no file context) ===
    (ActionPhase.GENERATING, None): "typing",

    # === UPLOADING: Depends on file type (sending TO user) ===
    # MediaType variants
    (ActionPhase.UPLOADING, MediaType.IMAGE): "upload_photo",
    (ActionPhase.UPLOADING, MediaType.VIDEO): "upload_video",
    (ActionPhase.UPLOADING, MediaType.VIDEO_NOTE): "upload_video_note",
    (ActionPhase.UPLOADING, MediaType.AUDIO): "upload_voice",
    (ActionPhase.UPLOADING, MediaType.VOICE): "upload_voice",
    (ActionPhase.UPLOADING, MediaType.DOCUMENT): "upload_document",
    (ActionPhase.UPLOADING, MediaType.PDF): "upload_document",
    # FileType variants (database model)
    (ActionPhase.UPLOADING, FileType.IMAGE): "upload_photo",
    (ActionPhase.UPLOADING, FileType.VIDEO): "upload_video",
    (ActionPhase.UPLOADING, FileType.AUDIO): "upload_voice",
    (ActionPhase.UPLOADING, FileType.VOICE): "upload_voice",
    (ActionPhase.UPLOADING, FileType.DOCUMENT): "upload_document",
    (ActionPhase.UPLOADING, FileType.PDF): "upload_document",
    (ActionPhase.UPLOADING, FileType.GENERATED): "upload_document",
    # Default for unknown file type
    (ActionPhase.UPLOADING, None): "upload_document",

    # === DOWNLOADING: Receiving FROM user (shows "recording" for voice/video) ===
    (ActionPhase.DOWNLOADING, MediaType.VOICE): "record_voice",
    (ActionPhase.DOWNLOADING, MediaType.VIDEO_NOTE): "record_video",
    (ActionPhase.DOWNLOADING, MediaType.AUDIO): "upload_voice",  # Not recording
    (ActionPhase.DOWNLOADING, MediaType.VIDEO): "upload_video",  # Not recording
    (ActionPhase.DOWNLOADING, MediaType.IMAGE): "upload_photo",
    (ActionPhase.DOWNLOADING, MediaType.DOCUMENT): "upload_document",
    (ActionPhase.DOWNLOADING, MediaType.PDF): "upload_document",
    (ActionPhase.DOWNLOADING, None): "typing",

    # === PROCESSING: Transcription, OCR, analysis ===
    (ActionPhase.PROCESSING, MediaType.VOICE): "record_voice",
    (ActionPhase.PROCESSING, MediaType.VIDEO_NOTE): "record_video",
    (ActionPhase.PROCESSING, MediaType.AUDIO): "record_voice",
    (ActionPhase.PROCESSING, MediaType.VIDEO): "record_video",
    (ActionPhase.PROCESSING, None): "typing",

    # === SEARCHING: Location or web search ===
    (ActionPhase.SEARCHING, None): "typing",  # find_location is niche
}
```

### New File: `telegram/chat_action/scope.py`

```python
from typing import Optional
from .types import ActionPhase, ActionPriority, FileTypeHint


class ActionScope:
    """A scoped action that automatically manages its lifecycle.

    Scopes are stackable - inner scope temporarily overrides outer.
    When inner scope exits, outer scope's action resumes.

    Usage:
        async with ActionScope(manager, ActionPhase.GENERATING):
            await generate_text()  # Shows "typing"

            async with ActionScope(manager, ActionPhase.UPLOADING, MediaType.IMAGE):
                await send_photo()  # Shows "upload_photo"

            # Back to "typing" automatically
    """

    def __init__(
        self,
        manager: "ChatActionManager",
        phase: ActionPhase,
        file_type: FileTypeHint = None,
        *,
        mime_type: Optional[str] = None,
        priority: ActionPriority = ActionPriority.NORMAL,
    ):
        self.manager = manager
        self.phase = phase
        self.file_type = file_type
        self.mime_type = mime_type
        self.priority = priority
        self._scope_id: Optional[str] = None

    async def __aenter__(self) -> "ActionScope":
        self._scope_id = await self.manager.push_scope(
            phase=self.phase,
            file_type=self.file_type,
            mime_type=self.mime_type,
            priority=self.priority,
        )
        return self

    async def __aexit__(self, *args):
        await self.manager.pop_scope(self._scope_id)
```

### New File: `telegram/chat_action/resolver.py`

```python
from typing import Optional
from .types import ActionPhase, FileTypeHint, ACTION_RESOLUTION_TABLE, ChatAction

# Import CENTRALIZED conversion from core module (NO DUPLICATION!)
from core.mime_types import mime_to_media_type


def resolve_action(
    phase: ActionPhase,
    file_type: FileTypeHint = None,
    *,
    mime_type: Optional[str] = None,
) -> ChatAction:
    """Resolve action phase + file type to Telegram ChatAction.

    Accepts multiple input types for flexibility:
    - MediaType enum (from pipeline) - PREFERRED
    - FileType enum (from database)
    - MIME string (auto-converted via core.mime_types.mime_to_media_type)

    Args:
        phase: What the bot is doing (GENERATING, UPLOADING, etc).
        file_type: MediaType, FileType enum, or None.
        mime_type: Optional MIME string (converted to MediaType if file_type is None).

    Returns:
        Telegram ChatAction string.

    Examples:
        resolve_action(ActionPhase.GENERATING) → "typing"
        resolve_action(ActionPhase.UPLOADING, MediaType.IMAGE) → "upload_photo"
        resolve_action(ActionPhase.UPLOADING, FileType.VIDEO) → "upload_video"
        resolve_action(ActionPhase.UPLOADING, mime_type="image/png") → "upload_photo"
        resolve_action(ActionPhase.PROCESSING, MediaType.VOICE) → "record_voice"
    """
    # Convert MIME to MediaType using EXISTING centralized function
    effective_file_type = file_type
    if effective_file_type is None and mime_type:
        effective_file_type = mime_to_media_type(mime_type)

    # Try exact match first
    key = (phase, effective_file_type)
    if key in ACTION_RESOLUTION_TABLE:
        return ACTION_RESOLUTION_TABLE[key]

    # Fallback to phase-only default
    default_key = (phase, None)
    return ACTION_RESOLUTION_TABLE.get(default_key, "typing")
```

### Updated File: `telegram/chat_action/__init__.py`

```python
"""Universal Chat Action System.

Provides automatic, context-aware Telegram status indicators.
Uses existing MediaType/FileType enums for type-safe action resolution.

Quick Start:
    from telegram.chat_action import ActionManager
    from telegram.pipeline.models import MediaType

    # Get or create manager for this chat
    manager = ActionManager.get(bot, chat_id, thread_id)

    # Use semantic scopes with enum types
    async with manager.generating():
        await stream_response()

        async with manager.uploading(file_type=MediaType.IMAGE):
            await send_photo()  # Auto-resolves to "upload_photo"

    # Or with FileType from database layer
    from db.models.user_file import FileType
    async with manager.uploading(file_type=FileType.VIDEO):
        await send_video()  # Auto-resolves to "upload_video"

    # MIME fallback when enum not available
    async with manager.uploading(mime_type="audio/mpeg"):
        await send_audio()  # Auto-converts to MediaType.AUDIO → "upload_voice"

Low-level API (still available for backwards compatibility):
    from telegram.chat_action import send_action, continuous_action
"""

from telegram.chat_action.types import ActionPhase, ActionPriority
from telegram.chat_action.manager import ChatActionManager as ActionManager
from telegram.chat_action.scope import ActionScope
from telegram.chat_action.resolver import resolve_action

# Legacy API (backwards compatible)
from telegram.chat_action.legacy import send_action, continuous_action, ChatActionContext

# Re-export file type enums for convenience
from telegram.pipeline.models import MediaType
from db.models.user_file import FileType

__all__ = [
    # New API
    "ActionManager",
    "ActionPhase",
    "ActionPriority",
    "ActionScope",
    "resolve_action",
    # File types (convenience re-export)
    "MediaType",
    "FileType",
    # Legacy API
    "send_action",
    "continuous_action",
    "ChatActionContext",
]
```

---

## Usage Examples

### Example 1: Streaming with Tool Execution

```python
from telegram.pipeline.models import MediaType

# Before (scattered, manual)
async with continuous_action(bot, chat_id, "typing", thread_id):
    async for event in stream_events():
        ...
        if tool_use:
            async with continuous_action(bot, chat_id, "typing", thread_id):
                result = await execute_tool()
                if result.get("_file_contents"):
                    async with continuous_action(bot, chat_id, "upload_photo", thread_id):
                        await send_file()

# After (automatic, semantic)
manager = ActionManager.get(bot, chat_id, thread_id)

async with manager.generating():  # → "typing"
    async for event in stream_events():
        ...
        if tool_use:
            # Tool execution inherits "generating" scope (typing)
            result = await execute_tool()
            if result.get("_file_contents"):
                for file in files:
                    # Use MediaType enum - auto-resolved to correct action
                    async with manager.uploading(file_type=file.media_type):
                        # MediaType.IMAGE → "upload_photo"
                        # MediaType.VIDEO → "upload_video"
                        # MediaType.AUDIO → "upload_voice"
                        await send_file(file)
                # Back to typing automatically
```

### Example 2: Media Input Processing (normalizer.py)

```python
from telegram.pipeline.models import MediaType

# Before (manual mapping in 6 places)
if message.voice:
    await send_action(bot, chat_id, "record_voice", thread_id)
elif message.video_note:
    await send_action(bot, chat_id, "record_video", thread_id)
elif message.audio:
    await send_action(bot, chat_id, "upload_voice", thread_id)
elif message.video:
    await send_action(bot, chat_id, "upload_video", thread_id)
elif message.photo:
    await send_action(bot, chat_id, "upload_photo", thread_id)
elif message.document:
    await send_action(bot, chat_id, "upload_document", thread_id)

# After (automatic from MediaType)
manager = ActionManager.get(bot, chat_id, thread_id)

# MediaType already determined from message
media_type = MediaType.VOICE  # or VIDEO_NOTE, AUDIO, etc.

async with manager.downloading(file_type=media_type):
    # MediaType.VOICE → "record_voice"
    # MediaType.VIDEO_NOTE → "record_video"
    # MediaType.AUDIO → "upload_voice"
    # etc.
    file_bytes = await download_from_telegram()
    await upload_to_files_api(file_bytes)
```

### Example 3: File Delivery (claude_files.py)

```python
from db.models.user_file import FileType

# Before (manual MIME checking)
if mime_type.startswith("image/"):
    async with continuous_action(bot, chat_id, "upload_photo", thread_id):
        await send_photo()
else:
    async with continuous_action(bot, chat_id, "upload_document", thread_id):
        await send_document()

# After (automatic from FileType)
manager = ActionManager.get(bot, chat_id, thread_id)

# FileType already determined for DB storage
file_type = FileType.IMAGE  # or VIDEO, AUDIO, etc.

async with manager.uploading(file_type=file_type):
    # FileType.IMAGE → "upload_photo"
    # FileType.VIDEO → "upload_video"
    # FileType.AUDIO → "upload_voice"
    # FileType.DOCUMENT → "upload_document"
    await send_to_telegram()
```

### Example 4: Parallel Operations in Forum Topics

```python
# Forum with multiple topics - each topic has independent action state
topic_1_manager = ActionManager.get(bot, chat_id, topic_1_id)
topic_2_manager = ActionManager.get(bot, chat_id, topic_2_id)

# Concurrent operations in different topics - completely independent
async def handle_topic_1():
    async with topic_1_manager.generating():
        await long_generation()

async def handle_topic_2():
    async with topic_2_manager.uploading(file_type=MediaType.VIDEO):
        await send_large_video()

await asyncio.gather(handle_topic_1(), handle_topic_2())
```

### Example 5: Fallback to MIME (when enum not available)

```python
# When only MIME string is available (rare case)
manager = ActionManager.get(bot, chat_id, thread_id)

async with manager.uploading(mime_type="image/png"):
    # MIME auto-converted to MediaType.IMAGE → "upload_photo"
    await send_file()
```

---

## Implementation Plan

### Phase 0: Prerequisite Refactoring - Centralize MIME→Enum Conversion

**Problem Found:** MIME → enum conversion is duplicated in 3 places:
- `normalizer.py:672-681` - MIME → MediaType
- `claude_files.py:68-77` - MIME → FileType
- `processor.py:31-49` - MediaType → FileType (this is fine, enum→enum)

**Solution:** Add centralized functions to `core/mime_types.py`:

```python
# NEW in core/mime_types.py

def mime_to_media_type(mime_type: str) -> "MediaType":
    """Convert MIME type to MediaType enum.

    Centralizes logic previously duplicated in normalizer.py.
    Uses existing is_*_mime() helper functions.
    """
    from telegram.pipeline.models import MediaType

    normalized = normalize_mime_type(mime_type)

    if is_pdf_mime(normalized):
        return MediaType.PDF
    elif is_image_mime(normalized):
        return MediaType.IMAGE
    elif is_audio_mime(normalized):
        return MediaType.AUDIO
    elif is_video_mime(normalized):
        return MediaType.VIDEO
    else:
        return MediaType.DOCUMENT
```

**Then update existing code:**
1. `normalizer.py:672-681` → use `mime_to_media_type()`
2. `claude_files.py:68-77` → use `mime_to_media_type()` + `_media_type_to_file_type()`

**Note:** `_media_type_to_file_type()` in processor.py stays as-is (it's enum→enum, not MIME→enum)

---

### Phase 1: Core Infrastructure (New Files)
1. Create `telegram/chat_action/` package
2. Implement `types.py` with ActionPhase enum and resolution table
3. Implement `resolver.py` - uses `mime_to_media_type()` from core/mime_types.py (NO duplication!)
4. Implement `manager.py` with scope stack and action loop
5. Implement `scope.py` with context manager
6. Add `__init__.py` with public API

### Phase 2: Legacy Compatibility Layer
1. Move existing functions to `legacy.py`
2. Re-export from `__init__.py` for backwards compatibility
3. Ensure all existing imports continue to work

### Phase 3: Migration - Streaming (claude.py)
1. Replace `continuous_action()` wrapper with `manager.generating()`
2. Remove manual action passing through call stack
3. Test streaming still works

### Phase 4: Migration - Tool Execution (claude_tools.py)
1. Replace tool action mapping with `ActionManager` scope
2. Remove `TOOL_CHAT_ACTIONS` dict
3. Tool execution inherits parent scope (typing)

### Phase 5: Migration - File Delivery (claude_files.py)
1. Replace manual MIME checking with `manager.uploading(file_type=...)`
2. FileType already determined at line 68-77, just pass it
3. Test all file types

### Phase 6: Migration - Input Processing (normalizer.py)
1. Replace 6 separate `send_action()` calls
2. MediaType already determined, just pass it to `manager.downloading(file_type=...)`
3. Test all media input types

### Phase 7: Fix Direct API Call (claude.py:1060)
1. Replace `bot.send_chat_action()` with manager
2. Ensure proper error handling

### Phase 8: Testing & Documentation
1. Unit tests for ActionManager
2. Integration tests for scope nesting
3. Update CLAUDE.md with new patterns

---

## File Structure After Implementation

```
bot/telegram/chat_action/
├── __init__.py          # Public API exports
├── types.py             # ActionType, ActionPriority, resolution table
├── resolver.py          # MIME-to-action resolution logic
├── manager.py           # ChatActionManager (per-chat singleton)
├── scope.py             # ActionScope context manager
├── loop.py              # ActionLoop (async refresh task)
├── registry.py          # Global registry of active managers
└── legacy.py            # Backwards-compatible API (send_action, etc.)
```

---

## API Reference

### High-Level API (Recommended)

```python
from telegram.chat_action import ActionManager, MediaType, FileType

# Get manager for chat (singleton per chat/thread)
manager = ActionManager.get(bot, chat_id, thread_id)

# === Semantic scopes with enum types ===

# Text generation
async with manager.generating():  # → "typing"
    ...

# File upload to user (auto-select action from enum)
async with manager.uploading(file_type=MediaType.IMAGE):    # → "upload_photo"
async with manager.uploading(file_type=MediaType.VIDEO):    # → "upload_video"
async with manager.uploading(file_type=MediaType.AUDIO):    # → "upload_voice"
async with manager.uploading(file_type=FileType.DOCUMENT):  # → "upload_document"

# File download from user
async with manager.downloading(file_type=MediaType.VOICE):      # → "record_voice"
async with manager.downloading(file_type=MediaType.VIDEO_NOTE): # → "record_video"
async with manager.downloading(file_type=MediaType.IMAGE):      # → "upload_photo"

# Media processing (transcription, OCR)
async with manager.processing(file_type=MediaType.VOICE):  # → "record_voice"
async with manager.processing(file_type=MediaType.AUDIO):  # → "record_voice"

# Search operations
async with manager.searching():  # → "typing"

# === MIME fallback (when enum not available) ===
async with manager.uploading(mime_type="image/png"):  # → "upload_photo"
async with manager.uploading(mime_type="video/mp4"):  # → "upload_video"

# === Manual override (raw action string) ===
async with manager.scope(ActionPhase.UPLOADING, file_type=MediaType.IMAGE):
    ...
```

### Low-Level API (Legacy Compatible)

```python
# These still work exactly as before
from telegram.chat_action import send_action, continuous_action

await send_action(bot, chat_id, "typing", thread_id)

async with continuous_action(bot, chat_id, "upload_photo", thread_id):
    await upload_file()
```

---

## Migration Checklist

### Phase 0: Prerequisite Refactoring (eliminates code duplication)
- [ ] Add `mime_to_media_type()` to `core/mime_types.py`
- [ ] Refactor `normalizer.py:672-681` to use new function
- [ ] Refactor `claude_files.py:68-77` to use new function + `_media_type_to_file_type()`
- [ ] Add tests for `mime_to_media_type()`

### Phase 1-2: Chat Action Infrastructure
- [ ] Create `telegram/chat_action/` package structure
- [ ] Implement `ActionPhase` enum and resolution table
- [ ] Implement `ActionManager` with scope stack
- [ ] Implement `ActionScope` context manager
- [ ] Implement `ActionLoop` for periodic refresh
- [ ] Move legacy functions to `legacy.py`

### Phase 3-7: Migration
- [ ] Migrate `claude.py` streaming
- [ ] Migrate `claude_tools.py` tool execution
- [ ] Migrate `claude_files.py` file delivery
- [ ] Migrate `normalizer.py` input processing
- [ ] Fix direct API call in `claude.py:1060`

### Phase 8: Testing & Documentation
- [ ] Add unit tests for ActionManager
- [ ] Add integration tests for scope nesting
- [ ] Update documentation

---

## Benefits

1. **Single Responsibility** - ActionManager owns all action logic for a chat
2. **Type-Safe** - Uses existing `MediaType`/`FileType` enums (no string magic)
3. **Consistent** - Follows project patterns (`core/mime_types.py` helpers)
4. **Scope Nesting** - Complex operations work naturally
5. **Concurrent Safety** - Multiple topics/chats handled independently
6. **Backwards Compatible** - Existing code continues to work
7. **Testable** - Clear interfaces for unit testing
8. **Maintainable** - All action logic in one place
9. **Extensible** - Easy to add new action types

---

## Architectural Consistency

### Code Reuse - NO Duplication!

**Before (current state - duplicated logic):**
```
normalizer.py:672-681    →  MIME → MediaType (inline)
claude_files.py:68-77    →  MIME → FileType (inline, duplicated!)
processor.py:31-49       →  MediaType → FileType (function)
```

**After (Phase 0 refactoring):**
```
core/mime_types.py       →  mime_to_media_type() [NEW, CENTRALIZED]
normalizer.py            →  uses mime_to_media_type()
claude_files.py          →  uses mime_to_media_type() + _media_type_to_file_type()
chat_action/resolver.py  →  uses mime_to_media_type() [NO NEW CODE]
```

### Pattern Compliance

| Pattern | Existing Usage | Chat Action Usage |
|---------|---------------|-------------------|
| **Enums for types** | `MediaType`, `FileType` | Reuse same enums |
| **MIME detection** | `core/mime_types.py` | Add `mime_to_media_type()` |
| **Enum conversion** | `processor._media_type_to_file_type()` | Reuse existing |
| **Helper functions** | `is_image_mime()`, etc. | Used by new centralized function |
| **Two-layer model** | Pipeline → Database | Phase + FileType → Action |
| **Singleton per context** | `ClaudeProvider` | `ActionManager.get()` |

### File Type Resolution Flow

```
Input                     Resolution                         Output
────────────────────────────────────────────────────────────────────────
MediaType.IMAGE      ──→  ACTION_RESOLUTION_TABLE       ──→  "upload_photo"
FileType.VIDEO       ──→  ACTION_RESOLUTION_TABLE       ──→  "upload_video"
"audio/mpeg"         ──→  core.mime_types.mime_to_media_type()
                          ↓
                          MediaType.AUDIO
                          ↓
                          ACTION_RESOLUTION_TABLE       ──→  "upload_voice"
```

### Integration with Existing Code

```python
# normalizer.py - MediaType already determined
# (after Phase 0: uses centralized mime_to_media_type())
file_type = MediaType.VOICE
async with manager.downloading(file_type=file_type):
    ...

# claude_files.py - FileType already determined
# (after Phase 0: uses mime_to_media_type() + _media_type_to_file_type())
file_type = FileType.IMAGE
async with manager.uploading(file_type=file_type):
    ...

# Rare edge case: only MIME string available
async with manager.uploading(mime_type=mime_str):
    # Uses SAME centralized mime_to_media_type() - NO DUPLICATION
    ...
```

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing code | Full backwards compatibility layer |
| Performance overhead | Singleton per chat, minimal overhead |
| Complexity increase | High-level API hides complexity |
| Race conditions | Single action loop per chat |
| Memory leaks | Weak references in registry, cleanup on chat end |

---

## Approval Request

This plan creates a universal, modular chat action system that:
- Works with any file type (auto MIME detection)
- Works in any chat type (private, group, forum)
- Works for any operation (generating, uploading, processing)
- Maintains full backwards compatibility
- Improves code maintainability

**Estimated files to create:** 7
**Estimated files to modify:** 4
**Backwards compatible:** Yes

Ready to implement upon approval.
