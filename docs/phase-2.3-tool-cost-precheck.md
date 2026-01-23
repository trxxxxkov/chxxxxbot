# Phase 2.3: Tool Cost Pre-check

## Problem

Users can request expensive tool operations (e.g., "draw 1000 images") and go into large negative balance. Current soft balance check only prevents starting new requests when balance ≤ 0, but doesn't limit tool calls within a single request.

**Risk scenarios:**
- `generate_image` × 100 = ~$13.40
- `transcribe_audio` on long videos = ~$0.36/hour
- `execute_python` with 1-hour timeout = ~$0.13

## Solution

Pre-check estimated tool cost before execution. **If user balance < 0, reject all paid tool calls.** This is simple and prevents abuse while allowing the initial API call to complete (which may have pushed balance slightly negative).

## Cost Estimation by Tool

| Tool | Paid? | Cost Formula | Notes |
|------|-------|--------------|-------|
| `generate_image` | ✅ Yes | $0.134 (1K/2K), $0.240 (4K) | Google Gemini API |
| `transcribe_audio` | ✅ Yes | $0.006/minute | OpenAI Whisper API |
| `web_search` | ✅ Yes | $0.01/request | Anthropic server-side tool |
| `execute_python` | ✅ Yes | $0.000036/sec × timeout | E2B sandbox (default 3600s → max $0.13) |
| `analyze_image` | ✅ Yes | Variable (tokens) | Claude API (separate call) |
| `analyze_pdf` | ✅ Yes | Variable (tokens) | Claude API (separate call) |
| `preview_file` | ✅ Yes | Variable (tokens) | Claude Vision API for images/PDF (free for text) |
| `render_latex` | ❌ Free | $0 | Local pdflatex rendering |
| `web_fetch` | ❌ Free | Server-side | No external API |
| `deliver_file` | ❌ Free | No cost | File delivery only |

**Key insight:** 7 tools have API costs. If balance < 0, reject these 7.

## Architecture

### 1. Paid Tools Registry

**File:** `core/tools/cost_estimator.py`

```python
from decimal import Decimal
from typing import Any, Dict, Optional

# Tools that have API costs (external or Claude)
PAID_TOOLS = {
    "generate_image",     # Google Gemini: $0.134-0.240/image
    "transcribe_audio",   # OpenAI Whisper: $0.006/minute
    "web_search",         # Anthropic: $0.01/request
    "execute_python",     # E2B sandbox: $0.000036/second
    "analyze_image",      # Claude API: separate call for image analysis
    "analyze_pdf",        # Claude API: separate call for PDF analysis
    "preview_file",       # Claude Vision API for images/PDF (free for text)
}

def is_paid_tool(tool_name: str) -> bool:
    """Check if tool has external API costs."""
    return tool_name in PAID_TOOLS

def estimate_tool_cost(
    tool_name: str,
    tool_input: Dict[str, Any],
    audio_duration_seconds: Optional[float] = None,
) -> Optional[Decimal]:
    """Estimate tool cost for logging/analytics.

    Returns:
        Estimated cost in USD, or None for free tools.
    """
    if tool_name == "generate_image":
        resolution = tool_input.get("resolution", "2k")
        if resolution == "4k":
            return Decimal("0.240")
        return Decimal("0.134")

    if tool_name == "transcribe_audio":
        if audio_duration_seconds:
            minutes = Decimal(str(audio_duration_seconds)) / 60
            return minutes * Decimal("0.006")
        return Decimal("0.03")  # Estimate 5 min if unknown

    if tool_name == "execute_python":
        # Use timeout from input, default 3600s
        timeout = tool_input.get("timeout", 3600)
        return Decimal(str(timeout)) * Decimal("0.000036")

    return None  # Free tool
```

### 2. Balance Pre-check Flow

**Location:** `telegram/handlers/claude.py` in `execute_single_tool_safe()`

```
Tool Call Request
       │
       ▼
┌──────────────────┐
│ Is Paid Tool?    │
│ (cost_estimator) │
└────────┬─────────┘
         │
    ┌────┴────┐
    │ No      │ Yes
    ▼         ▼
Execute    ┌──────────────────┐
Tool       │ Get Cached       │
           │ Balance (Redis)  │
           └────────┬─────────┘
                    │
                    ▼
           ┌───────────────────┐
           │ balance >= 0?     │
           └────────┬──────────┘
                    │
               ┌────┴────┐
               │ Yes     │ No
               ▼         ▼
           Execute    Return Error
           Tool       to Claude
```

**Simple rule:** If balance < 0 and tool is paid → reject.

### 3. Caching Strategy

**Goal:** No Postgres queries during tool execution loop.

**Implementation:**
1. **Use existing Redis cache:**
   - User balance already cached with 60s TTL (`cache/user_cache.py`)
   - Call `get_cached_user_balance(user_id)` before paid tool
   - Falls back to Postgres if cache miss

2. **No pending charges tracking needed:**
   - Simple rule: balance >= 0 → allow, balance < 0 → reject
   - Actual charges happen after tool execution
   - Next tool call will see updated balance (after cache invalidation)

3. **Cache invalidation:**
   - Balance cache invalidated after each charge (`charge_for_tool`)
   - Next pre-check gets fresh balance

### 4. Error Response Format

**For Claude to understand and not retry:**

```python
{
    "error": "insufficient_balance",
    "message": "Cannot execute generate_image: your balance is negative (-$0.08). "
               "Paid tools are blocked until balance is topped up. "
               "Please inform the user to use /pay command.",
    "balance_usd": "-0.08",
    "tool_name": "generate_image"
}
```

**Key:** Clear message tells Claude to inform user about /pay, not retry the tool.

### 5. Configuration

**In `config.py`:**

```python
# Whether to enforce tool cost pre-check
TOOL_COST_PRECHECK_ENABLED = True
```

No need for negative cap - simple rule: balance < 0 → reject paid tools.

## Implementation Steps

### Step 1: Paid Tools Registry ✅
- [x] Create `core/tools/cost_estimator.py`
- [x] Define `PAID_TOOLS` set
- [x] Add `is_paid_tool()` function
- [x] Add `estimate_tool_cost()` for logging/analytics
- [x] Add tests (17 tests in test_cost_estimator.py)

### Step 2: Pre-check Integration ✅
- [x] Modify `execute_single_tool_safe()` in `claude_tools.py`
- [x] Check `is_paid_tool()` before execution
- [x] Get cached balance via `get_user_balance()` (cache → DB fallback)
- [x] If balance < 0, return structured error
- [x] Log pre-check rejections

### Step 3: Error Response Format ✅
- [x] Define clear error format for Claude
- [x] Include balance, tool name, action required
- [x] Error message tells Claude to inform user about /pay

### Step 4: Monitoring ✅
- [x] Add Prometheus counter `bot_tool_precheck_rejected_total`
- [ ] Add Grafana panel (optional, can be done later)

### Step 5: Testing ✅
- [x] Unit tests for `is_paid_tool()` (5 tests)
- [x] Unit tests for `estimate_tool_cost()` (11 tests)
- [x] Integration test: tool rejected when balance < 0 (6 tests)
- [x] Integration test: free tools work with negative balance
- [x] Total: 28 new tests, all passing

## File Changes

```
bot/
├── core/
│   └── tools/
│       └── cost_estimator.py              # NEW: PAID_TOOLS, is_paid_tool()
├── telegram/
│   └── handlers/
│       ├── claude.py                      # MODIFY: Pass user_id to execute_single_tool_safe
│       └── claude_tools.py                # MODIFY: Add balance pre-check
├── config.py                              # MODIFY: TOOL_COST_PRECHECK_ENABLED
├── utils/
│   └── metrics.py                         # MODIFY: Add TOOL_PRECHECK_REJECTED counter
└── tests/
    ├── core/
    │   └── tools/
    │       └── test_cost_estimator.py     # NEW: 17 tests
    └── telegram/
        └── handlers/
            └── test_tool_precheck.py      # NEW: 11 tests
```

## Edge Cases

1. **Multiple paid tools in parallel:**
   - Check balance before FIRST paid tool
   - If balance < 0, reject all paid tools in batch
   - Free tools in same batch execute normally

2. **Cache miss:**
   - Fall back to Postgres query
   - Refresh cache after query

3. **Race conditions (two requests simultaneously):**
   - Both might pass pre-check if cache shows balance > 0
   - Both execute, one goes negative
   - Next request's tools will be rejected
   - Acceptable: max overshoot is ~1 tool cost

4. **Free tools with negative balance:**
   - Always allowed (analyze_image, web_search, etc.)
   - Only paid external APIs are blocked

## Metrics

```python
# Prometheus counter
tool_precheck_rejected = Counter(
    "bot_tool_precheck_rejected_total",
    "Paid tool calls rejected due to negative balance",
    ["tool_name"]
)
```

## Example Scenario

**User request:** "Нарисуй 10 картинок котиков"

**Without pre-check:**
- Claude calls `generate_image` × 10
- Total cost: $1.34
- User goes from $0.05 to -$1.29

**With pre-check (balance < 0 → reject):**
1. Image 1: balance $0.05 ≥ 0 → allowed, charged $0.134 → balance = -$0.084
2. Image 2: balance -$0.084 < 0 → **REJECTED**

**Claude receives:**
```json
{
  "error": "insufficient_balance",
  "message": "Cannot execute generate_image: your balance is negative (-$0.08). "
             "Please top up with /pay command.",
  "balance_usd": "-0.084",
  "tool_name": "generate_image"
}
```

**Claude responds to user:**
"Я нарисовал 1 картинку. Для продолжения необходимо пополнить баланс командой /pay."

**Result:** User goes from $0.05 to only -$0.084, not -$1.29.

## Future Enhancements

1. **Dynamic cost estimates** based on historical data
2. **User-specific limits** (trusted users get higher cap)
3. **Cost warnings** before expensive operations
4. **Budget mode** - user sets max spend per request
