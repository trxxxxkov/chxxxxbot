# Architecture Audit Results

**Date:** 2026-01-26
**Tests:** 1301 passing

---

## A. File Architecture

### Current State
- **Unified file visibility:** `format_unified_files_section()` shows both delivered (from DB) and pending (from exec_cache) files in system prompt
- **Pending files tracking:** Uses `exec:meta:{temp_id}` keys with `thread_id` field
- **Two delivery patterns:**
  - `_file_contents` → immediate delivery (generate_image, deliver_file)
  - `output_files` → pending state, model decides when to deliver

### Issues Found

#### A1. Performance: SCAN for pending files ✅ FIXED
```python
# Was: SCAN exec:meta:* → filter by thread_id (O(n))
# Now: SMEMBERS exec:thread:{thread_id} → batch GET (O(1))
```

**Implementation:**
- Added `exec:thread:{thread_id}` SET index
- `store_exec_file()` adds to index with SADD
- `delete_exec_file()` removes from index with SREM
- `get_pending_files_for_thread()` uses SMEMBERS + lazy cleanup

#### A2. No file state transitions (Priority: Low)
Files have states: pending → delivered (or expired)
Currently no explicit state machine, relies on:
- pending: exists in exec_cache
- delivered: exists in user_files DB table

**Status:** Works correctly, but could be more explicit.

### Verdict: ✅ Excellent architecture
The unified file visibility (`format_unified_files_section`) solves the main concern.
Thread index optimization implemented for O(1) pending files lookup.

---

## B. Message Pipeline

### Current State
- **Single entry point:** `telegram/pipeline/handler.py` handles ALL message types
- **Normalizer pattern:** All I/O (download, upload, transcribe) happens BEFORE queue
- **Race conditions:** Eliminated by design (files ready before queue)
- **Old handlers removed:** `files.py`, `media_handlers.py` deleted

### Pipeline Structure
```
telegram/pipeline/
├── handler.py     # Single @router.message handler
├── models.py      # ProcessedMessage, UploadedFile, etc.
├── normalizer.py  # MessageNormalizer (all I/O)
├── processor.py   # Saves files, calls Claude handler
├── queue.py       # ProcessedMessageQueue (200ms batching)
└── tracker.py     # Message tracking for batching
```

### Issues Found
None. The pipeline is well-architected.

### Verdict: ✅ Excellent architecture
The "Unified Message Pipeline" plan was fully implemented.

---

## C. Payment System

### Current State
- **Tool cost pre-check:** `is_paid_tool()` + balance check before execution
- **Simple rule:** If balance < 0, reject all paid tools
- **6 paid tools:** generate_image, transcribe_audio, web_search, execute_python, analyze_image, analyze_pdf
- **Generation stop:** Partial usage charged on cancellation

### Flow
```
User request → Balance middleware (fail-open) → Tool execution
                                                     ↓
                                              is_paid_tool?
                                                     ↓
                                            balance < 0? → Reject
                                                     ↓
                                              Execute → Charge
```

### Issues Found
None. The system is universal and simple.

### Verdict: ✅ Good architecture

---

## D. Caching

### Current State
| Cache Type | TTL | Invalidation Strategy |
|------------|-----|----------------------|
| User data | 1 hour | Update on balance change |
| Thread | 1 hour | Rarely changes |
| Messages | 1 hour | Invalidate on new message |
| Files | 1 hour | Invalidate on new file |
| File bytes | 1 hour | Immutable content |
| Exec files | 1 hour | Consumed once, then deleted |

- **Write-behind queue:** 5s flush, batch 100
- **Circuit breaker:** 3 failures → 30s timeout
- **Cache-first reads:** User data, messages

### Issues Found

#### D1. All TTLs identical (Priority: Low)
All caches use 1 hour TTL. Could be tuned:
- User balance: shorter (60s) for faster reflection
- Thread metadata: longer (24h) since rarely changes
- Messages: keep 1h (balance between freshness and performance)

**Status:** Current approach works, optimization optional.

### Verdict: ✅ Good architecture

---

## E. Tools

### Current State
- **9 tools total:** 6 paid, 3 free
- **Unified interface:** All tools return dict with optional `_file_contents` or `output_files`
- **Cost tracking:** Each tool reports `cost_usd` in result

### Tool Patterns
```python
# Immediate delivery (generate_image)
{"_file_contents": [...], "cost_usd": 0.134}

# Pending (execute_python)
{"output_files": [...], "cost_usd": 0.001}

# Free tool (render_latex)
{"output_files": [...]}  # No cost_usd
```

### Issues Found
None significant. Tools are well-structured.

### Verdict: ✅ Good architecture

---

## F. Documentation

### Issues Found

#### F1. Outdated docs (Priority: High)
Several docs reference old architecture:
- Phase docs mention files that no longer exist
- Test counts outdated

#### F2. CLAUDE.md was bloated
Fixed: Compressed from 1046 to 171 lines.

### Recommendation
Review and update all docs in `docs/` directory.

---

## Summary

| Area | Status | Issues |
|------|--------|--------|
| File Architecture | ✅ Excellent | A1: ✅ Fixed (thread index) |
| Message Pipeline | ✅ Excellent | None |
| Payment System | ✅ Good | None |
| Caching | ✅ Good | D1: TTL tuning optional |
| Tools | ✅ Good | None |
| Documentation | ✅ Updated | F1: ✅ Fixed |

### Critical Issues
None found.

### Completed Actions

1. **✅ A1: Thread index for pending files**
   - Created `exec:thread:{thread_id}` SET
   - Updated `store_exec_file()` to SADD
   - Updated `delete_exec_file()` to SREM
   - Updated `get_pending_files_for_thread()` to use SMEMBERS

2. **✅ F1: Updated documentation**
   - Compressed CLAUDE.md (1046 → 171 lines)
   - Updated docs/README.md with current phase status
   - Removed DevOps Agent references

---

## Architecture Diagram (Current)

```
┌─────────────────────────────────────────────────────────────┐
│                    Telegram Update                           │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Middlewares (Logging, DB, Balance)              │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Unified Pipeline Handler                        │
│  (telegram/pipeline/handler.py)                              │
│                                                              │
│  1. MessageNormalizer → ProcessedMessage                    │
│     - Download media                                         │
│     - Upload to Files API                                    │
│     - Transcribe (voice/video_note)                          │
│                                                              │
│  2. ProcessedMessageQueue (200ms batching)                   │
│                                                              │
│  3. Processor → claude.py:_process_message_batch             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Claude Handler                            │
│  (telegram/handlers/claude.py)                               │
│                                                              │
│  1. Cache-first reads (user, messages, files)               │
│  2. Build context (format_unified_files_section)            │
│  3. Claude API call (streaming)                              │
│  4. Tool execution loop                                      │
│     - Pre-check balance for paid tools                       │
│     - Execute tools in parallel                              │
│     - Handle _file_contents (immediate delivery)             │
│  5. Write-behind queue (messages, stats)                     │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│    Redis     │    │  PostgreSQL  │    │   Claude     │
│   (Cache)    │    │     (DB)     │    │    API       │
└──────────────┘    └──────────────┘    └──────────────┘
```
