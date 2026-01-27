# Tools Audit Report

**Date:** 2026-01-26
**Files:** `bot/core/tools/` (12 files)

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 3 |
| Medium | 4 |
| Low | 3 |

---

## Critical Issues

### #1: COMMAND INJECTION IN LATEX RENDERING

**File:** `bot/core/tools/render_latex.py:206-218`

**Issue:** pdflatex subprocess can execute arbitrary commands via LaTeX directives:
- `\immediate\write18{command}` (shell escape)
- `\input|` (pipe commands)
- `\openout` (file writes)

**Impact:** Attacker can execute system commands.

**Fix:**
```python
# Add flag to disable shell escape
'-shell-escape=f',
# OR validate input against dangerous patterns
DANGEROUS_PATTERNS = [r'\\write18', r'\\input\|', r'\\openout']
```

---

## High Issues

### #2: Insufficient Input Validation in execute_python

**File:** `bot/core/tools/execute_python.py:292-308`

**Issue:** No validation that file_ids exist and belong to user.

**Fix:** Validate file ownership before downloading.

---

### #3: API Error Exposure to Users

**Files:** `analyze_image.py:114-146`, `analyze_pdf.py:141-173`

**Issue:** Detailed API errors exposed to users without sanitization.

**Fix:** Implement error classification, sanitize messages.

---

### #4: No Balance Check Before Tool Execution

**File:** `bot/core/tools/registry.py:275-286`

**Issue:** Paid tools can execute without balance verification.

**Fix:** Integrate cost_estimator.is_paid_tool() check.

---

## Medium Issues

### #5: Resource Cleanup in execute_python

**File:** `execute_python.py:200-209`

**Issue:** Sandbox cleanup errors silently ignored, temp files may leak.

---

### #6: Hardcoded 30s Timeout in LaTeX

**File:** `render_latex.py:204-220`

**Issue:** Complex LaTeX may need more time.

---

### #7: No Timeout on Whisper API

**File:** `transcribe_audio.py:121-126`

**Issue:** API call can hang indefinitely.

---

### #8: Filename Safety in preview_file

**File:** `preview_file.py:193-228`

**Issue:** Filenames from execute_python not sanitized.

---

## Low Issues

- Result serialization could expose sensitive data
- Deprecated backward compatibility code
- Missing MIME validation in some tools

---

## Security Matrix

| Tool | Input Valid | Error Handle | Timeout | Cleanup | Cost Check |
|------|-------------|--------------|---------|---------|------------|
| analyze_image | ✓ | ⚠ | ✓ | ✓ | ✗ |
| analyze_pdf | ✓ | ⚠ | ✓ | ✓ | ✗ |
| execute_python | ⚠ | ✓ | ⚠ | ⚠ | ✗ |
| generate_image | ✓ | ✓ | ✓ | ✓ | ✗ |
| transcribe_audio | ✓ | ✓ | ✗ | ✓ | ✗ |
| render_latex | ⚠ CRITICAL | ✓ | ✓ | ✓ | ✓ |
| deliver_file | ✓ | ✓ | ✓ | ✓ | ✓ |

---

## Positive Findings

- No SSRF vulnerabilities
- No path traversal issues
- Good error propagation
- Unified ToolConfig pattern
- Comprehensive logging
- MIME type validation where needed

---

## Priority Fixes

1. **URGENT:** Fix LaTeX command injection (#1)
2. **HIGH:** Add file_id validation (#2), error sanitization (#3), balance checks (#4)
3. **MEDIUM:** Cleanup handling, timeout config
