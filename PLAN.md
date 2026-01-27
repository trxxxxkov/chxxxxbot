# Implementation Plan: Sandbox Reuse & Verification Workflow Fix

## Executive Summary

Two issues to fix:
1. **E2B sandbox resets on every call** — bot can't iterate on work in the same environment
2. **Verification workflow is backwards** — instructions say "deliver first, then analyze" but should be "analyze first, then deliver"

---

## Issue 1: E2B Sandbox Reuse

### Current State

```python
# execute_python.py:65
sandbox = Sandbox.create()  # Fresh every time
try:
    # ... work ...
finally:
    sandbox.kill()  # Destroyed immediately
```

**Problem:** When bot needs to iterate (fix errors, retry conversions), it creates a new sandbox each time:
- Loses installed packages (apt-get, pip)
- Loses generated intermediate files
- Wastes time re-uploading input files
- User sees "sandbox resets between calls" in thinking

### Solution: Cache Sandbox in Redis

**Cache Key:** `sandbox:{user_id}` or `sandbox:{thread_id}`
**TTL:** 3600 seconds (1 hour) — same as EXEC_FILE_TTL

**Architecture:**

```
┌─────────────────────────────────────────────────────────────────┐
│                      execute_python()                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Check Redis for existing sandbox_id                         │
│     ┌─────────────────────────────────────┐                     │
│     │  sandbox:{thread_id}                │                     │
│     │  {                                  │                     │
│     │    "sandbox_id": "sbx_abc123",      │                     │
│     │    "created_at": 1706000000,        │                     │
│     │    "last_used": 1706003500          │                     │
│     │  }                                  │                     │
│     └─────────────────────────────────────┘                     │
│                         │                                        │
│     ┌───────────────────┴───────────────────┐                   │
│     │                                       │                    │
│     ▼ Found                          ▼ Not found                │
│  ┌──────────────┐              ┌──────────────┐                 │
│  │ Reconnect to │              │ Create new   │                 │
│  │ existing     │              │ sandbox      │                 │
│  │ sandbox      │              │              │                 │
│  └──────┬───────┘              └──────┬───────┘                 │
│         │                             │                          │
│         └──────────────┬──────────────┘                          │
│                        ▼                                         │
│  2. Execute code in sandbox                                      │
│                        │                                         │
│                        ▼                                         │
│  3. Update Redis: refresh TTL, update last_used                 │
│                        │                                         │
│                        ▼                                         │
│  4. Return results (DO NOT kill sandbox)                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### E2B Sandbox Reconnect API

E2B supports reconnecting to existing sandboxes:

```python
from e2b_code_interpreter import Sandbox

# Create new
sandbox = Sandbox.create()
sandbox_id = sandbox.sandbox_id  # Save this

# Later: reconnect
sandbox = Sandbox.connect(sandbox_id)
```

### Implementation Plan

**File: `cache/sandbox_cache.py` (NEW)**

```python
"""E2B Sandbox caching for reuse between execute_python calls.

Sandboxes are expensive to create (~2-5 seconds). By caching them:
- Packages (apt-get, pip) stay installed
- Intermediate files persist
- Input files don't need re-upload
- Faster iteration on code fixes

TTL: 3600 seconds (1 hour) — same as EXEC_FILE_TTL
Key: sandbox:{thread_id} or sandbox:{user_id}
"""

import json
import time
from typing import Optional, TypedDict

from cache.connection import get_redis
from cache.keys import SANDBOX_TTL  # Add to keys.py: 3600

class SandboxMeta(TypedDict):
    sandbox_id: str
    created_at: float
    last_used: float


async def get_cached_sandbox(thread_id: int) -> Optional[str]:
    """Get cached sandbox_id for thread.

    Returns:
        sandbox_id if exists and valid, None otherwise.
    """
    redis = await get_redis()
    key = f"sandbox:{thread_id}"
    data = await redis.get(key)

    if not data:
        return None

    meta = json.loads(data)
    return meta.get("sandbox_id")


async def cache_sandbox(thread_id: int, sandbox_id: str) -> None:
    """Cache sandbox_id for thread.

    Args:
        thread_id: Thread identifier.
        sandbox_id: E2B sandbox ID.
    """
    redis = await get_redis()
    key = f"sandbox:{thread_id}"
    now = time.time()

    meta = SandboxMeta(
        sandbox_id=sandbox_id,
        created_at=now,
        last_used=now,
    )

    await redis.setex(key, SANDBOX_TTL, json.dumps(meta))


async def refresh_sandbox_ttl(thread_id: int) -> None:
    """Refresh sandbox TTL after use."""
    redis = await get_redis()
    key = f"sandbox:{thread_id}"

    data = await redis.get(key)
    if data:
        meta = json.loads(data)
        meta["last_used"] = time.time()
        await redis.setex(key, SANDBOX_TTL, json.dumps(meta))


async def invalidate_sandbox(thread_id: int) -> None:
    """Remove sandbox from cache (e.g., on error)."""
    redis = await get_redis()
    key = f"sandbox:{thread_id}"
    await redis.delete(key)
```

**File: `cache/keys.py` — Add constant**

```python
# Sandbox reuse TTL (same as exec files)
SANDBOX_TTL = 3600  # 1 hour
```

**File: `core/tools/execute_python.py` — Modify _run_sandbox_sync**

```python
def _run_sandbox_sync(
    code: str,
    downloaded_files: Dict[str, bytes],
    requirements: Optional[str],
    timeout: float,
    sandbox_id: Optional[str] = None,  # NEW: reuse existing
) -> Tuple[Dict[str, Any], float, str]:  # NEW: return sandbox_id
    """Run code in E2B sandbox.

    Returns:
        Tuple of (result_dict, duration, sandbox_id).
        sandbox_id is returned for caching (do NOT kill sandbox).
    """
    import os
    import time

    api_key = get_e2b_api_key()
    os.environ["E2B_API_KEY"] = api_key

    sandbox_start_time = time.time()

    # Try to reconnect to existing sandbox
    sandbox = None
    reused = False

    if sandbox_id:
        try:
            sandbox = Sandbox.connect(sandbox_id)
            reused = True
            logger.info("tools.execute_python.sandbox_reused",
                       sandbox_id=sandbox_id)
        except Exception as e:
            logger.warning("tools.execute_python.sandbox_reconnect_failed",
                          sandbox_id=sandbox_id,
                          error=str(e))
            sandbox = None

    # Create new if reconnect failed or no cached sandbox
    if sandbox is None:
        sandbox = Sandbox.create()
        logger.info("tools.execute_python.sandbox_created",
                   sandbox_id=sandbox.sandbox_id)

    try:
        # Upload files (skip if reusing and files already there)
        if downloaded_files:
            sandbox.commands.run("mkdir -p /tmp/inputs")
            for filename, file_content in downloaded_files.items():
                sandbox_path = f"/tmp/inputs/{filename}"
                # Only upload if file doesn't exist or content changed
                sandbox.files.write(sandbox_path, file_content)

        # Install packages (skip if already installed when reusing)
        if requirements and not reused:
            sandbox.commands.run(f"pip install {requirements}")

        # Execute code
        execution = sandbox.run_code(code=code, timeout=timeout)

        # ... process results (same as before) ...

        sandbox_end_time = time.time()
        sandbox_duration = sandbox_end_time - sandbox_start_time

        # DO NOT kill sandbox — return ID for caching
        return result, sandbox_duration, sandbox.sandbox_id

    except Exception as e:
        # On error, kill sandbox to avoid stale state
        try:
            sandbox.kill()
        except:
            pass
        raise
```

**File: `core/tools/execute_python.py` — Modify execute_python**

```python
async def execute_python(
    code: str,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    # ... other params ...
) -> Dict[str, Any]:
    """Execute Python code with sandbox reuse."""

    # Step 1: Check for cached sandbox
    from cache.sandbox_cache import (
        get_cached_sandbox,
        cache_sandbox,
        refresh_sandbox_ttl,
        invalidate_sandbox,
    )

    cached_sandbox_id = None
    if thread_id:
        cached_sandbox_id = await get_cached_sandbox(thread_id)

    # Step 2: Download input files (same as before)
    downloaded_files = {}
    if file_inputs:
        # ... same download logic ...

    # Step 3: Run in thread pool
    try:
        result, sandbox_duration, sandbox_id = await asyncio.to_thread(
            _run_sandbox_sync,
            code,
            downloaded_files,
            requirements,
            timeout or 3600.0,
            cached_sandbox_id,  # Pass cached ID
        )

        # Step 4: Cache sandbox for reuse
        if thread_id and sandbox_id:
            await cache_sandbox(thread_id, sandbox_id)

    except Exception as e:
        # Invalidate cached sandbox on error
        if thread_id:
            await invalidate_sandbox(thread_id)
        raise

    # ... rest of the function (same as before) ...
```

### Sandbox Cleanup

**Problem:** Sandboxes cost money while running. Need cleanup mechanism.

**Option A: Let E2B auto-expire (simplest)**
- E2B sandboxes auto-terminate after idle timeout (configurable)
- Default: 5 minutes idle → auto-kill
- We just cache the ID; if reconnect fails, create new

**Option B: Background cleanup task**
- Periodic task checks Redis for stale sandbox keys
- Explicitly kills sandboxes older than TTL

**Recommendation:** Start with Option A (simpler), add Option B if needed.

---

## Issue 2: Verification Workflow Fix

### Current State (BROKEN)

**In `execute_python.py:536-537`:**
```
- For PDFs: analyze_pdf with temp_id (use deliver_file first, then analyze)
- For images: analyze_image with temp_id (use deliver_file first, then analyze)
```

**Problem:** Bot is told to deliver first, then analyze. User sees file before bot verifies it.

### Root Cause Analysis

The instructions were written when `preview_file` couldn't handle images/PDFs from exec_cache. But looking at current code:

**`preview_file.py:674-679` (images):**
```python
async def _handle_image_preview(...):
    if not claude_file_id:
        from core.claude.files_api import upload_to_files_api
        claude_file_id = await upload_to_files_api(content, filename, mime_type)
    # Then analyze with Vision API
```

**`preview_file.py:705-710` (PDFs):**
```python
async def _handle_pdf_preview(...):
    if not claude_file_id:
        from core.claude.files_api import upload_to_files_api
        claude_file_id = await upload_to_files_api(content, filename, mime_type)
    # Then analyze with PDF API
```

**Conclusion:** `preview_file` ALREADY uploads to Files API internally. The instructions are outdated!

### Solution: Update Instructions

**Changes needed:**

1. **`execute_python.py` tool definition** — fix verification section
2. **`system_prompt.py`** — fix workflow examples
3. **`preview_file.py` tool definition** — clarify it works with all sources

### Updated Tool Definition (`execute_python.py`)

```python
"""
<verification_workflow>
VERIFY BEFORE DELIVERING - especially after negative feedback:

After generating files, verify the result BEFORE delivering to user.
This catches issues that code-level checks miss (corrupted files,
encoding problems, incomplete conversions, wrong output format).

**Verification process:**
1. Check output_files preview (size, dimensions, format info)
2. For images <1MB: base64 preview is in tool results — look at it!
3. If preview insufficient or need detailed analysis:
   - Use preview_file(file_id="exec_xxx", question="...") for ANY file type
   - preview_file handles images/PDFs by uploading to Files API internally
   - This does NOT send the file to user — it's internal analysis
4. If problems found, iterate with different approach
5. Only deliver_file when confident file is correct

**Example workflow (PDF generation):**
Turn 1: execute_python → output_files: [{temp_id: "exec_abc_output.pdf", preview: "PDF, 8KB"}]
        Preview shows suspiciously small size
Turn 2: preview_file(file_id="exec_abc_output.pdf", question="Is this a complete presentation?")
        → "The PDF appears to be only 2 pages with placeholder text"
Turn 3: execute_python (fix code) → output_files: [{preview: "PDF, 245KB"}]
Turn 4: preview_file → confirms content is correct
Turn 5: deliver_file(temp_id=...) → sends PDF to user ✓

**Key point:** preview_file does NOT deliver to user. It's for YOUR verification.
</verification_workflow>
"""
```

### Updated System Prompt (`system_prompt.py`)

**Section: File Preview & Delivery (around line 237)**

```python
"""
**File Preview & Delivery:**
- `preview_file`: Analyze ANY cached file content BEFORE sending to user
  - Works with ALL file types from ALL sources:
    * exec_xxx: Files from execute_python (images, PDFs, CSV, text, etc.)
    * file_xxx: Files in Claude Files API
    * Telegram file_id: Files from user uploads
  - For images/PDFs: automatically uploads to Files API for Vision analysis
  - This does NOT send file to user — it's YOUR internal verification tool
  - USE FOR: Verifying generated content matches user's request
  - Parameters: file_id (required), question (for images/PDFs), max_rows, max_chars
  - Cost: FREE for text/CSV/XLSX, PAID for images/PDFs (Vision API)

- `deliver_file`: Send cached file to user AFTER verification
  - Only use AFTER you've verified the file is correct
  - Use temp_id from execute_python's or render_latex's output_files
  - Files cached for 30 minutes — deliver promptly after verification
"""
```

**Section: self_correction (around line 148)**

```python
"""
<self_correction>
**Iterative self-review after negative feedback:**

When user expresses dissatisfaction ("not right", "redo", "that's wrong"):

1. **First attempt** (user's initial request):
   - Generate file (execute_python, render_latex, generate_image)
   - For images: check base64 preview in tool results
   - Deliver promptly if looks correct
   - This is the fast path — trust your work

2. **After negative feedback** (user asks to redo):
   - Switch to careful mode with MANDATORY self-verification
   - Generate new version
   - **ALWAYS verify BEFORE delivering:**
     * Images <1MB: Check base64 preview in tool results
     * Images >1MB: Use preview_file(file_id="exec_xxx", question="...")
     * PDFs: Use preview_file(file_id="exec_xxx", question="...")
     * CSV/XLSX: Use preview_file to check actual data rows
     * Text files: Use preview_file to read content
   - Ask yourself: "Does this match what the user wanted?"
   - If not satisfactory → regenerate and verify again
   - Only deliver_file when YOU are confident it's correct

3. **Verification loop** (max 5 iterations):
   - Generate → preview_file → Assess → (Regenerate if needed) → deliver_file
   - After 5 failed attempts, deliver best version with explanation

**CRITICAL:** preview_file does NOT send to user. Use it freely for verification.
deliver_file is what sends to user — only call it when verified.
</self_correction>
"""
```

### Updated preview_file Tool Definition

**In `preview_file.py`:**

```python
PREVIEW_FILE_TOOL = {
    "name": "preview_file",
    "description": """Preview ANY file content BEFORE deciding to deliver to user.

<purpose>
YOUR internal verification tool — see what's in any file before sending to user.
Works with ALL file types from ALL sources. Does NOT deliver to user.

Use this to verify generated content matches user's request before calling deliver_file.
</purpose>

<file_sources>
- exec_xxx: Files from execute_python (images, PDFs, CSV, text, binary)
- file_xxx: Files already in Claude Files API
- Telegram file_id: Files from user messages

ALL sources supported — just pass the file_id.
</file_sources>

<processing_by_type>
- CSV/XLSX: Shows table with rows (FREE, local parsing)
- Text/JSON/XML/code: Shows content with line numbers (FREE)
- Images: Claude Vision describes what's visible (PAID)
  → For exec_xxx images, auto-uploads to Files API first
- PDF: Claude PDF analyzes document content (PAID)
  → For exec_xxx PDFs, auto-uploads to Files API first
- Audio/Video: Shows metadata, use transcribe_audio for content
</processing_by_type>

<verification_workflow>
1. execute_python/render_latex → output_files with temp_id
2. preview_file(file_id="exec_xxx", question="Does this show...?")
   → Your internal check, NOT sent to user
3. If correct: deliver_file(temp_id="exec_xxx") → sends to user
4. If wrong: regenerate, preview again, then deliver
</verification_workflow>

<examples>
1. Verify generated PDF before sending:
   preview_file(file_id="exec_abc_report.pdf",
                question="Does this PDF have all 5 sections the user requested?")

2. Check chart data is correct:
   preview_file(file_id="exec_xyz_chart.png",
                question="Does the chart show sales data for Q1-Q4 2024?")

3. Verify CSV export:
   preview_file(file_id="exec_def_data.csv", max_rows=5)
</examples>

<cost>
FREE for text/CSV/XLSX (local parsing).
PAID for images/PDF (Claude Vision API, ~$0.003-0.01).
</cost>""",
    # ... rest of schema unchanged ...
}
```

---

## Implementation Checklist

### Phase 1: Sandbox Reuse
- [ ] Add `SANDBOX_TTL = 3600` to `cache/keys.py`
- [ ] Create `cache/sandbox_cache.py` with get/cache/refresh/invalidate functions
- [ ] Modify `_run_sandbox_sync` to accept optional `sandbox_id` and return it
- [ ] Modify `execute_python` to check cache, pass ID, and cache result
- [ ] Handle reconnect failures gracefully (create new sandbox)
- [ ] Test sandbox reuse works across multiple calls
- [ ] Test package installation persists
- [ ] Test file persistence in sandbox

### Phase 2: Verification Workflow Fix
- [ ] Update `execute_python.py` `<verification_workflow>` section
- [ ] Update `system_prompt.py` `<self_correction>` section
- [ ] Update `system_prompt.py` tool descriptions (preview_file, deliver_file)
- [ ] Update `preview_file.py` tool definition with clearer instructions
- [ ] Remove misleading "deliver_file first, then analyze" instructions
- [ ] Add explicit "preview_file does NOT send to user" messaging
- [ ] Test: generate PDF, preview, then deliver — verify order is correct

### Phase 3: Testing
- [ ] Manual test: Ask bot to create LaTeX presentation
- [ ] Manual test: Ask bot to redo/fix the presentation
- [ ] Verify bot uses preview_file BEFORE deliver_file after negative feedback
- [ ] Verify sandbox reuse reduces iteration time

---

## Claude 4 Best Practices Alignment

| Best Practice | Current State | After Fix |
|---------------|---------------|-----------|
| Explicit instructions | ✅ Good | ✅ Same |
| Context/motivation (WHY) | ⚠️ Some missing | ✅ Added "does NOT send to user" |
| Parallel tool calls | ✅ Good | ✅ Same |
| default_to_action | ✅ Good | ✅ Same |
| reflection_after_tool_use | ✅ Good | ✅ Enhanced with verification |
| Avoid "think" word (Opus) | ⚠️ Not checked | 🔲 To check |
| Clear workflow examples | ⚠️ Misleading | ✅ Fixed with correct order |

---

## Benefits

1. **Sandbox Reuse:**
   - Faster iterations (no sandbox creation overhead)
   - Packages stay installed
   - Intermediate files persist
   - Better user experience for complex tasks

2. **Verification Workflow:**
   - Bot verifies before sending (not after)
   - Fewer "redo" requests from users
   - Better quality on first delivery after feedback
   - Clear separation: preview_file = verify, deliver_file = send

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Sandbox reconnect fails | Create new sandbox, log warning |
| Stale sandbox state | E2B auto-expires idle sandboxes |
| Cost increase from kept sandboxes | Same TTL as files (1 hour), auto-cleanup |
| preview_file cost for images/PDFs | Already PAID, worth it for quality |

---

## Ready for Implementation

Awaiting approval to proceed with Phase 1 (Sandbox Reuse) and Phase 2 (Verification Workflow Fix).
