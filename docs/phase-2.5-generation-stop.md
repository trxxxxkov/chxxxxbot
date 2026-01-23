# Phase 2.5: Generation Stop

**Status:** Complete (Phase 2.5.1 - Simplified)
**Dependencies:** Phase 1.4 (Extended Thinking), Phase 3.4 (Streaming Architecture)

---

## Overview

Stop Claude generation mid-stream via two mechanisms:

1. **`/stop` command** - user sends /stop to stop active generation
2. **New message interruption** - sending any message stops current generation

**Implemented behavior:**
- User sends `/stop` command → generation stops entirely
- User sends new message → current generation stops, new message queued
- Partial content preserved with "[interrupted]" indicator

---

## Implementation Summary (Phase 2.5.1 - Simplified)

### Files

| File | Purpose |
|------|---------|
| `telegram/generation_tracker.py` | Singleton tracker + `generation_context` context manager |
| `telegram/handlers/stop_generation.py` | Handler for `/stop` command |

### Modified Files

| File | Changes |
|------|---------|
| `telegram/handlers/claude.py` | Added `generation_context`, cancellation check in stream loop, "[interrupted]" suffix |
| `telegram/pipeline/handler.py` | Auto-cancel generation on new message |
| `telegram/loader.py` | Registered `stop_generation` router |

### How It Works

**Method 1: /stop Command**
1. **User sends `/stop`** during generation
2. **Handler calls `generation_tracker.cancel()`**: Sets cancel event
3. **Stream detects cancellation**: Breaks loop between events
4. **Message finalized**: Partial content + "[interrupted]" suffix
5. **Handler replies**: "Generation stopped." or "No active generation to stop."

**Method 2: New Message**
1. **User sends new message** while generation active
2. **Pipeline handler** checks `generation_tracker.is_active()`
3. **If active**: Calls `cancel()`, logs the interruption
4. **Current generation stops**, new message processed after
5. **Partial content preserved** with "[interrupted]" suffix

### Tests

- `tests/telegram/test_generation_tracker.py` - 14 tests
- `tests/telegram/handlers/test_stop_generation.py` - 6 tests

**Total: 20 tests for generation stop, 1221 total tests passing**

---

## Technical Architecture

### Current Flow (simplified)

```
User Message → Pipeline → Claude API Stream → Events Loop → Draft Updates → Finalize
                                    ↑
                              [CAN INTERRUPT HERE]
```

The streaming loop in `_stream_with_unified_events()` (claude.py:217-244):
```python
async for event in claude_provider.stream_events(iter_request):
    if event.type == "thinking_delta":
        await stream.handle_thinking_delta(event.content)
    elif event.type == "text_delta":
        await stream.handle_text_delta(event.content)
    # ... etc
```

**Key insight:** We can check a cancellation flag between events (every ~50-200ms).

### Proposed Solution

#### 1. Cancellation Token (asyncio.Event)

```python
# In StreamingSession or separate tracker
class GenerationTracker:
    """Track active generations for cancellation."""

    def __init__(self):
        self._active: dict[tuple[int, int], asyncio.Event] = {}
        # Key: (chat_id, user_id) → only one active generation per user per chat

    def start(self, chat_id: int, user_id: int) -> asyncio.Event:
        """Start tracking, return cancellation event."""
        key = (chat_id, user_id)
        self._active[key] = asyncio.Event()
        return self._active[key]

    def cancel(self, chat_id: int, user_id: int) -> bool:
        """Request cancellation, return True if found."""
        key = (chat_id, user_id)
        if key in self._active:
            self._active[key].set()
            return True
        return False

    def cleanup(self, chat_id: int, user_id: int) -> None:
        """Remove from tracking after completion."""
        self._active.pop((chat_id, user_id), None)
```

#### 2. Inline Keyboard with Stop Button

```python
# telegram/keyboards/stop_generation.py
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def get_stop_keyboard(chat_id: int, user_id: int) -> InlineKeyboardBuilder:
    """Create stop button keyboard.

    Args:
        chat_id: Chat ID for callback routing.
        user_id: User ID for callback routing.

    Returns:
        InlineKeyboardBuilder with stop button.
    """
    builder = InlineKeyboardBuilder()
    # Format: stop:<chat_id>:<user_id>
    callback_data = f"stop:{chat_id}:{user_id}"
    builder.row(
        InlineKeyboardButton(
            text="⏹ Stop",
            callback_data=callback_data
        )
    )
    return builder
```

#### 3. Callback Handler

```python
# telegram/handlers/stop_generation.py
from aiogram import F, Router, types
from telegram.generation_tracker import generation_tracker

router = Router(name="stop_generation")

@router.callback_query(F.data.startswith("stop:"))
async def stop_generation_callback(callback: types.CallbackQuery) -> None:
    """Handle stop button press.

    Args:
        callback: Callback query from inline keyboard.
    """
    if not callback.data or not callback.from_user:
        await callback.answer("⚠️ Invalid request")
        return

    # Parse callback data: "stop:<chat_id>:<user_id>"
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("⚠️ Invalid callback")
        return

    try:
        target_chat_id = int(parts[1])
        target_user_id = int(parts[2])
    except ValueError:
        await callback.answer("⚠️ Invalid IDs")
        return

    # Security: only the user who started generation can stop it
    if callback.from_user.id != target_user_id:
        await callback.answer("⚠️ You can only stop your own generations")
        return

    # Request cancellation
    if generation_tracker.cancel(target_chat_id, target_user_id):
        await callback.answer("⏹ Stopping generation...")
    else:
        await callback.answer("No active generation found")
```

#### 4. Integration Points

**A. Send keyboard with draft (draft_streaming.py)**

When starting a draft, attach the stop button:
```python
# In DraftStreamer.update() or similar
async def update(self, text: str, reply_markup: InlineKeyboardMarkup = None):
    """Update draft with optional keyboard."""
    # sendMessageDraft supports reply_markup
    await self._bot.send_message_draft(
        chat_id=self._chat_id,
        text=text,
        reply_markup=reply_markup,  # Stop button here
        ...
    )
```

**B. Check cancellation in streaming loop (claude.py)**

```python
async for event in claude_provider.stream_events(iter_request):
    # Check cancellation between events
    if cancel_event.is_set():
        if stream.is_in_thinking():
            # Stop thinking, force text generation
            logger.info("generation.cancelled_thinking", thread_id=thread_id)
            # Signal Claude to stop thinking and output text
            # This requires API support or workaround
            break
        else:
            # Stop text generation entirely
            logger.info("generation.cancelled_text", thread_id=thread_id)
            break

    # Normal event processing...
```

**C. Remove keyboard after completion**

When finalizing the message, remove the stop button:
```python
final_message = await dm.current.finalize(
    final_text=final_display,
    reply_markup=None  # Remove stop button
)
```

---

## API Considerations

### Claude API Limitations

**Problem:** Claude API doesn't support mid-stream cancellation or "skip thinking" commands.

**Workarounds:**

1. **Client-side stop:** Simply stop reading the stream and close connection
   - Claude SDK: Exit the `async for` loop, context manager handles cleanup
   - Cost: Still charged for tokens generated up to that point

2. **Skip thinking → text:** Not directly supported
   - **Option A:** Stop stream, make new request without extended thinking
   - **Option B:** Just display thinking as-is and stop (simpler)
   - **Option C:** Wait for thinking to complete naturally, only allow stopping text

**Recommendation:** Start with Option B (simplest), upgrade later if needed.

### Telegram Bot API

`sendMessageDraft` (Bot API 9.3) supports `reply_markup`:
```
reply_markup: InlineKeyboardMarkup (optional)
```

This allows attaching the stop button to the draft message.

---

## Implementation Phases

### Phase 2.5.1: Basic Stop (Text Only)

**Scope:** Stop text generation only (no thinking interruption)

**Files:**
- `telegram/generation_tracker.py` - Cancellation tracking
- `telegram/keyboards/stop_generation.py` - Stop button keyboard
- `telegram/handlers/stop_generation.py` - Callback handler
- `telegram/handlers/claude.py` - Integration (check cancel flag)
- `telegram/loader.py` - Register router

**Behavior:**
- Stop button appears during generation
- Press → stops current text generation
- Message ends with `[Generation stopped]` indicator
- Keyboard removed after stop/completion

### Phase 2.5.2: Thinking-Aware Stop

**Scope:** Different behavior during thinking vs text

**Additional changes:**
- `telegram/streaming/session.py` - Track current phase (thinking/text)
- Update callback handler to check phase

**Behavior during thinking:**
- Stop button shows "⏹ Skip Thinking"
- Press → stops thinking block, starts new API call for text
- If no text generated yet, just stops entirely

**Behavior during text:**
- Stop button shows "⏹ Stop"
- Press → stops generation

### Phase 2.5.3: Enhanced UX

**Scope:** Better user experience

**Improvements:**
- Button text changes dynamically: "⏭ Skip Thinking" → "⏹ Stop"
- Confirmation toast: "Thinking skipped" / "Stopped"
- Partial thinking preserved in display (collapsed)
- Logging and metrics for stop events

---

## File Structure

```
bot/
├── telegram/
│   ├── generation_tracker.py      # NEW: Cancellation tracking
│   ├── keyboards/
│   │   └── stop_generation.py     # NEW: Stop button keyboard
│   ├── handlers/
│   │   ├── stop_generation.py     # NEW: Callback handler
│   │   └── claude.py              # MODIFY: Integration
│   ├── streaming/
│   │   └── session.py             # MODIFY: Phase tracking
│   ├── draft_streaming.py         # MODIFY: Keyboard support
│   └── loader.py                  # MODIFY: Register router
├── tests/
│   └── telegram/
│       ├── test_generation_tracker.py  # NEW
│       └── handlers/
│           └── test_stop_generation.py # NEW
```

---

## Edge Cases

### 1. Race Conditions

**Problem:** User presses stop after generation completed but before keyboard removed.

**Solution:**
- `generation_tracker.cancel()` returns False if not found
- Callback answers "No active generation found"

### 2. Multiple Messages

**Problem:** User sends multiple messages, which generation to stop?

**Solution:**
- Track by (chat_id, user_id) - only latest generation
- Previous generations auto-cleanup when new one starts

### 3. Tool Execution

**Problem:** What if stop pressed during tool execution (not streaming)?

**Solution:**
- Check cancel flag before tool execution
- If already executing, let tool complete (can't interrupt external APIs)
- Stop after tool result, before next iteration

### 4. Group Chats

**Problem:** Multiple users in group, who can stop?

**Solution:**
- Only the user who initiated the message can stop their generation
- Callback data includes user_id for verification

---

## Metrics

New Prometheus metrics:
```python
# utils/metrics.py
generation_stops_total = Counter(
    "bot_generation_stops_total",
    "Total generation stops by user",
    ["phase", "chat_type"]  # phase: thinking/text, chat_type: private/group
)
```

---

## Security Considerations

1. **Authorization:** Only message sender can stop their generation
2. **Callback validation:** Parse and validate IDs from callback data
3. **Rate limiting:** Standard Telegram callback rate limits apply
4. **No sensitive data:** Callback data contains only IDs, no content

---

## Testing Strategy

### Unit Tests

```python
# test_generation_tracker.py
def test_start_creates_event():
    tracker = GenerationTracker()
    event = tracker.start(123, 456)
    assert isinstance(event, asyncio.Event)
    assert not event.is_set()

def test_cancel_sets_event():
    tracker = GenerationTracker()
    tracker.start(123, 456)
    result = tracker.cancel(123, 456)
    assert result is True

def test_cancel_nonexistent_returns_false():
    tracker = GenerationTracker()
    result = tracker.cancel(123, 456)
    assert result is False
```

### Integration Tests

```python
# test_stop_generation.py
async def test_stop_callback_stops_generation():
    """Test that stop callback sets cancel event."""
    ...

async def test_stop_callback_wrong_user_rejected():
    """Test that other users can't stop generation."""
    ...

async def test_keyboard_removed_after_completion():
    """Test that stop button is removed when done."""
    ...
```

---

## Open Questions

1. **Keyboard persistence:** Should stop button persist after message is finalized (for potential "regenerate" feature)?

2. **Partial charges:** Should we log/display how much was saved by stopping early?

3. **Skip thinking cost:** Making a new API call to skip thinking costs more. Is this acceptable?

4. **Visual feedback:** Should we show a spinner or "Stopping..." text while cancellation propagates?

---

## Dependencies

- aiogram 3.24+ (InlineKeyboardButton, callback_query)
- Bot API 9.3 (sendMessageDraft with reply_markup)
- asyncio.Event (stdlib)

---

## Estimated Complexity

| Phase | Files | Tests | Risk |
|-------|-------|-------|------|
| 2.5.1 | 5 new, 2 modified | ~15 | Low |
| 2.5.2 | 2 modified | ~10 | Medium |
| 2.5.3 | 3 modified | ~10 | Low |

**Total:** ~7 files, ~35 tests
