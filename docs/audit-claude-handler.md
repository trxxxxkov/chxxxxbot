# Claude Handler Audit Report

**Date:** 2026-01-26
**File:** `bot/telegram/handlers/claude.py` (~2000 lines)

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High | 5 |
| Medium | 4 |
| Low | 8 |

---

## Critical Issues

### #1: Database Session Concurrency in Parallel Tools

**Location:** Lines 379-474

**Issue:** Multiple tools execute concurrently with SAME database session. SQLAlchemy session is not safe for concurrent async operations.

**Impact:** Lost updates, transaction isolation violations, data corruption.

**Fix:** Create separate sessions per tool OR use session pool.

---

### #2: Unhandled Streaming Exception Returns Without Cleanup

**Location:** Lines 1068-1075

**Issue:** When streaming fails, handler returns immediately without:
- Committing database writes
- Cleaning up generation tracker
- Releasing resources

**Impact:** Orphaned generation state prevents future messages.

**Fix:** Use try/finally for cleanup, don't return early.

---

### #3: Generation Tracker Not Released on Streaming Error

**Location:** Lines 197-206

**Issue:** If exception occurs during streaming and returns early (line 1075), cleanup may be incomplete.

**Fix:** Ensure cleanup in finally block.

---

## High Issues

### #4: Session Not Properly Scoped in Tool Loop

**Location:** Lines 403-474

**Issue:** No rollback mechanism for failed tool execution. Session state becomes inconsistent.

**Fix:** Wrap file processing in try/except with explicit rollback.

---

### #5: Cancellation Not Handled Mid-Event

**Location:** Lines 241-294

**Issue:** Cancellation check only between events, not during event handlers.

**Impact:** Inconsistent state if cancelled mid-event.

---

### #6: No Timeout on stream_events Iterator

**Location:** Lines 241-294

**Issue:** No overall timeout for streaming. If API hangs, handler waits forever.

**Fix:** Wrap with `asyncio.timeout(300)` (5 min max).

---

### #7: Tool Charging Failures Silent

**Location:** Lines 101-106 in claude_tools.py

**Issue:** Charging exceptions caught and logged but user not notified, no retry.

**Impact:** Revenue loss, inconsistent user state.

---

### #8: Partial Cost Calculation Formula Errors

**Location:** Lines 1084-1131

**Issues:**
- Thinking tokens use wrong pricing (output instead of thinking)
- Cache assumption may be wrong (first request)
- 4:1 char-to-token ratio inaccurate
- May double-charge for tools

---

## Medium Issues

### #9: Rate Limiting Missing in Fallback Path

**Location:** Lines 1045-1066

**Issue:** No cumulative delay between fallback messages, fixed retry.

---

### #10: DraftManager Cleanup Not Guaranteed

**Location:** Lines 197-206

**Issue:** If cleanup times out, orphaned drafts remain.

---

### #11: No Validation of continuation_conversation

**Location:** Lines 1022-1023

**Issue:** Structure never validated before use.

---

### #12: Max Continuations Silently Hit

**Location:** Lines 1024-1031

**Issue:** No user warning when limit reached.

---

## Low Issues (Summary)

- Global provider thread safety concerns
- User not found after cache miss
- Available files not refreshed during streaming
- String concatenation inefficiency
- Logging context missing user_id
- Error messages could be clearer
- Tool message validation missing
- No tool deduplication check

---

## Priority Fixes

1. **URGENT:** Fix session concurrency (#1), exception handling (#2), session scope (#4)
2. **HIGH:** Add stream timeout (#6), fix cost calculation (#8)
3. **MEDIUM:** Rate limiting, validation, cleanup guarantees
