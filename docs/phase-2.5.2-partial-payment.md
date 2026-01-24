# Phase 2.5.2: Partial Payment on Cancellation

**Status:** Complete
**Dependencies:** Phase 2.5.1 (Generation Stop)

---

## Problem

When user cancels generation via `/stop` or new message:
- Anthropic charges us for generated tokens
- Tool costs (generate_image, transcribe_audio) are incurred
- **Old behavior:** User paid nothing for cancelled requests
- **Result:** We absorbed losses on every cancellation

---

## Solution

**Simplified approach:** Estimate Claude API cost from accumulated text, charge user.

Tool costs remain unchanged - charged immediately during execution (provides abuse protection).

---

## Implementation

### Key Changes

1. **Return `thinking_chars` from streaming function**
   - `_stream_with_unified_events` now returns 6-tuple including `thinking_chars`
   - Accumulated across all iterations

2. **Estimate tokens when cancelled**
   ```python
   # ~4 characters per token (conservative, rounds down)
   estimated_output_tokens = output_chars // 4
   estimated_thinking_tokens = thinking_chars // 4
   estimated_input_tokens = context_chars // 4
   ```

3. **Calculate and charge partial cost**
   ```python
   partial_cost = (
       (estimated_input_tokens / 1_000_000) * model.pricing_input +
       ((estimated_output_tokens + estimated_thinking_tokens) / 1_000_000)
       * model.pricing_output
   )
   await balance_service.charge_user(user_id, partial_cost, ...)
   ```

### What's Charged When

| Scenario | Claude API | Tools |
|----------|------------|-------|
| Normal completion | Exact (from API) | Immediate |
| Cancelled | Estimated | Already charged |
| Cancel during tool | Estimated | Completed tools charged |

### Files Modified

| File | Changes |
|------|---------|
| `telegram/handlers/claude.py` | Added thinking_chars return, partial payment logic |

---

## Logging

```json
// When cancelled and charged
{
  "event": "claude_handler.cancelled_partial_charge",
  "estimated_input_tokens": 4500,
  "estimated_output_tokens": 50,
  "estimated_thinking_tokens": 200,
  "output_chars": 200,
  "thinking_chars": 800,
  "partial_cost_usd": 0.015
}

{
  "event": "claude_handler.cancelled_user_charged",
  "user_id": 123456,
  "partial_cost_usd": 0.015,
  "balance_after": 5.234
}
```

---

## Design Decisions

1. **Tool costs unchanged** - Still charged immediately for abuse protection
2. **Conservative estimation** - `chars // 4` rounds down, slightly undercharges
3. **Input tokens estimated** - From system prompt + context messages
4. **Single metric** - `claude_cancelled` service for tracking

---

## Testing

Manual testing:
1. Start long generation → `/stop` → Check logs for `cancelled_partial_charge`
2. Verify balance decreased
3. Verify tool costs (if any) charged separately
