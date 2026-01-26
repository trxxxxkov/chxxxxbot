# Architecture Audit Results

**Date:** 2026-01-26
**Tests:** 1304 passing

---

## A. File Architecture

### Current State
- **Unified file visibility:** `format_unified_files_section()` shows both delivered (from DB) and pending (from exec_cache) files in system prompt
- **Pending files tracking:** Uses `exec:meta:{temp_id}` keys with `thread_id` field
- **Two delivery patterns:**
  - `_file_contents` → immediate delivery (generate_image, deliver_file)
  - `output_files` → pending state, model decides when to deliver

### Issues Found & Fixed

#### A1. Performance: SCAN for pending files ✅ FIXED
```python
# Was: SCAN exec:meta:* → filter by thread_id (O(n))
# Now: SMEMBERS exec:thread:{thread_id} → batch GET (O(1))
```

#### A2. Missing file context ✅ FIXED
Model didn't know what files it generated (asked "let me look at your files").

**Solution:** Universal `context` field in exec_cache + `upload_context` in user_files.

```
┌─────────────────────────────────────────────────────────────────┐
│                    FILE CONTEXT FLOW                             │
├─────────────────────────────────────────────────────────────────┤
│ User upload     → processor.py   → upload_context = user's text │
│ render_latex    → exec_cache     → context = "LaTeX: {formula}" │
│ execute_python  → exec_cache     → context = "Python output: X" │
│ generate_image  → _file_contents → context = "Generated: ..."   │
│ deliver_file    → user_files     → upload_context = from cache  │
└─────────────────────────────────────────────────────────────────┘
```

**Implementation:**
- `store_exec_file()` now requires `context` parameter
- All tools pass meaningful context when storing files
- `format_unified_files_section()` shows context for both delivered and pending files
- Model sees: `context: "LaTeX: \frac{1}{2}"` in system prompt

### Verdict: ✅ Excellent architecture

---

## B. Message Pipeline

### Current State
- **Single entry point:** `telegram/pipeline/handler.py` handles ALL message types
- **Normalizer pattern:** All I/O (download, upload, transcribe) happens BEFORE queue
- **Race conditions:** Eliminated by design (files ready before queue)

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

### Verdict: ✅ Excellent architecture

---

## C. Payment System

### Current State
- **Tool cost pre-check:** `is_paid_tool()` + balance check before execution
- **Simple rule:** If balance < 0, reject all paid tools
- **6 paid tools:** generate_image, transcribe_audio, web_search, execute_python, analyze_image, analyze_pdf
- **Generation stop:** Partial usage charged on cancellation

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
| Exec files | 30 min | Consumed once, then deleted |

- **Write-behind queue:** 5s flush, batch 100
- **Circuit breaker:** 3 failures → 30s timeout
- **Cache-first reads:** User data, messages

### Verdict: ✅ Good architecture

---

## E. Tools

### Current State
- **9 tools total:** 6 paid, 3 free
- **Unified interface:** All tools return dict with optional `_file_contents` or `output_files`
- **Cost tracking:** Each tool reports `cost_usd` in result
- **Context tracking:** All tools provide `context` for generated files

### Tool Patterns
```python
# Immediate delivery (generate_image)
{"_file_contents": [{"filename": "...", "content": ..., "context": "..."}], "cost_usd": 0.134}

# Pending (execute_python, render_latex)
{"output_files": [{"temp_id": "...", "preview": "...", "context": "..."}]}
```

### Verdict: ✅ Good architecture

---

## Summary

| Area | Status | Issues |
|------|--------|--------|
| File Architecture | ✅ Excellent | A1, A2: ✅ Fixed |
| Message Pipeline | ✅ Excellent | None |
| Payment System | ✅ Good | None |
| Caching | ✅ Good | None |
| Tools | ✅ Good | None |
| Documentation | ✅ Updated | None |

### Completed Actions

1. **✅ A1: Thread index for pending files**
   - Created `exec:thread:{thread_id}` SET
   - O(1) lookup instead of O(n) SCAN

2. **✅ A2: Universal file context**
   - Added `context` parameter to `store_exec_file()`
   - All tools pass context when creating files
   - Context shown in system prompt for model understanding

3. **✅ Documentation updated**
   - Compressed CLAUDE.md (1046 → 171 lines)
   - Updated docs with current architecture

---

## Architecture Diagram

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
│     - Set upload_context = user's text                       │
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
│     - Shows file context for model understanding             │
│  3. Claude API call (streaming)                              │
│  4. Tool execution loop                                      │
│     - Pre-check balance for paid tools                       │
│     - Execute tools in parallel                              │
│     - Store files with context in exec_cache                 │
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
