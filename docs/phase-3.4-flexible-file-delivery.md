# Phase 3.4: Flexible File Delivery

## Overview

Реализация гибкой системы доставки файлов с двумя ключевыми улучшениями:
1. **preview_file** - анализ файлов (CSV, XLSX, PDF, text) перед отправкой
2. **sequential delivery** - последовательная доставка с текстом между файлами

## Problem Statement

### Текущие ограничения:

1. **Параллельная доставка**: Когда Claude вызывает `deliver_file` несколько раз в одном turn, все файлы отправляются одновременно, без текста между ними.

2. **Ограниченный preview**: Claude видит только метаданные файлов:
   - Изображения: ✅ полный base64 preview
   - CSV: ⚠️ только header + размер
   - XLSX: ❌ только размер файла
   - PDF: ❌ только количество страниц

### Желаемое поведение:

```
Пользователь: "Объясни два метода решения ДУ с формулами"

Claude: "Метод Эйлера - простейший численный метод..."
[render_latex → preview → deliver_file(sequential=True)]
→ Отправляется формула Эйлера

Claude: "Метод Рунге-Кутты более точен..."
[render_latex → preview → deliver_file(sequential=True)]
→ Отправляется формула Рунге-Кутты

Claude: "Сравнение точности методов..."
```

---

## Architecture

### Новые компоненты:

```
bot/core/tools/
├── preview_file.py      # NEW: Анализ файла без отправки
├── deliver_file.py      # MODIFIED: + sequential parameter
└── registry.py          # MODIFIED: + preview_file

bot/telegram/handlers/
├── claude.py            # MODIFIED: handle _force_turn_break
└── claude_tools.py      # MODIFIED: sequential delivery logic
```

### Flow diagram:

```
execute_python/render_latex
        │
        ▼
   output_files: [{temp_id, preview}]
        │
        ├─────────────────────────────────┐
        ▼                                 ▼
  preview_file(temp_id)           deliver_file(temp_id)
  [Для CSV/XLSX/PDF анализа]      [Обычная доставка]
        │                                 │
        ▼                                 ▼
  Полный контент файла            Файл отправлен
  (первые N строк, etc)           пользователю
        │
        ▼
  Claude анализирует
        │
        ▼
  deliver_file(temp_id, sequential=True)
        │
        ▼
  Файл отправлен + TURN BREAK
        │
        ▼
  Claude продолжает в новом turn
```

---

## Implementation Plan

### Stage 1: preview_file tool

**Цель**: Claude может анализировать содержимое файлов перед отправкой.

#### 1.1 Создать `bot/core/tools/preview_file.py`

```python
"""Preview cached file content without delivering to user.

Allows Claude to analyze file content (CSV rows, text content, etc.)
before deciding whether to deliver or regenerate.
"""

from typing import Any, Dict, TYPE_CHECKING
from cache.exec_cache import get_exec_file, get_exec_meta
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

PREVIEW_FILE_TOOL = {
    "name": "preview_file",
    "description": """Preview cached file content without sending to user.

<purpose>
Analyze file content before deciding to deliver. Useful for:
- CSV/XLSX: See actual data rows, verify column values
- Text files: Read full content
- PDF: Cannot preview content (use deliver_file then analyze_pdf)
- Images: Already visible in execute_python/render_latex result
</purpose>

<when_to_use>
- Verify CSV data is correct before sending
- Check text file content matches expectations
- Analyze tabular data quality
</when_to_use>

<parameters>
- temp_id: From output_files (e.g., "exec_abc123")
- max_rows: For CSV/XLSX, limit rows returned (default: 20)
- max_chars: For text files, limit characters (default: 5000)
</parameters>

<workflow>
1. execute_python generates CSV → output_files with temp_id
2. preview_file(temp_id, max_rows=10) → see first 10 rows
3. If data looks good → deliver_file(temp_id)
4. If data wrong → re-run execute_python with fixes
</workflow>""",
    "input_schema": {
        "type": "object",
        "properties": {
            "temp_id": {
                "type": "string",
                "description": "Temporary file ID from output_files"
            },
            "max_rows": {
                "type": "integer",
                "description": "Max rows for CSV/XLSX (default: 20)"
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters for text files (default: 5000)"
            }
        },
        "required": ["temp_id"]
    }
}


async def preview_file(
    temp_id: str,
    bot: 'Bot',
    session: 'AsyncSession',
    max_rows: int = 20,
    max_chars: int = 5000,
) -> Dict[str, Any]:
    """Preview file content from cache.

    Args:
        temp_id: Temporary file ID.
        bot: Bot instance (unused, interface consistency).
        session: DB session (unused, interface consistency).
        max_rows: Maximum rows for tabular data.
        max_chars: Maximum characters for text.

    Returns:
        Dict with file content or error.
    """
    _ = bot, session  # Unused

    logger.info("tools.preview_file.called", temp_id=temp_id)

    # Get metadata
    metadata = await get_exec_meta(temp_id)
    if not metadata:
        return {
            "success": "false",
            "error": f"File '{temp_id}' not found or expired (30 min TTL)"
        }

    # Get content
    content = await get_exec_file(temp_id)
    if not content:
        return {
            "success": "false",
            "error": f"File content for '{temp_id}' not found"
        }

    mime_type = metadata.get("mime_type", "")
    filename = metadata.get("filename", "")

    # Handle different file types
    if mime_type == "text/csv" or filename.endswith(".csv"):
        return _preview_csv(content, metadata, max_rows)

    elif mime_type in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel"
    ) or filename.endswith((".xlsx", ".xls")):
        return _preview_excel(content, metadata, max_rows)

    elif mime_type.startswith("text/") or mime_type in (
        "application/json", "application/xml", "application/javascript"
    ):
        return _preview_text(content, metadata, max_chars)

    elif mime_type.startswith("image/"):
        return {
            "success": "true",
            "message": "Image files are already visible in tool results. "
                       "No separate preview needed.",
            "filename": filename,
            "size_bytes": len(content),
        }

    elif mime_type == "application/pdf":
        return {
            "success": "true",
            "message": "PDF content cannot be previewed directly. "
                       "Use deliver_file first, then analyze_pdf with "
                       "the returned claude_file_id.",
            "filename": filename,
            "size_bytes": len(content),
            "preview": metadata.get("preview", ""),
        }

    else:
        return {
            "success": "true",
            "message": f"Binary file type '{mime_type}' cannot be previewed. "
                       "Use deliver_file to send to user.",
            "filename": filename,
            "size_bytes": len(content),
        }


def _preview_csv(
    content: bytes,
    metadata: dict,
    max_rows: int
) -> Dict[str, Any]:
    """Preview CSV file content."""
    try:
        import io
        import csv

        text = content.decode("utf-8")
        reader = csv.reader(io.StringIO(text))

        rows = []
        for i, row in enumerate(reader):
            if i >= max_rows + 1:  # +1 for header
                break
            rows.append(row)

        if not rows:
            return {"success": "false", "error": "Empty CSV file"}

        header = rows[0]
        data_rows = rows[1:]
        total_rows = text.count('\n')

        # Format as table
        table_str = " | ".join(header) + "\n"
        table_str += "-" * len(table_str) + "\n"
        for row in data_rows:
            table_str += " | ".join(str(cell)[:50] for cell in row) + "\n"

        return {
            "success": "true",
            "filename": metadata.get("filename"),
            "columns": header,
            "column_count": len(header),
            "total_rows": total_rows,
            "previewed_rows": len(data_rows),
            "data_preview": table_str,
            "message": f"Showing {len(data_rows)} of ~{total_rows} rows"
        }

    except Exception as e:
        return {"success": "false", "error": f"CSV parse error: {str(e)}"}


def _preview_excel(
    content: bytes,
    metadata: dict,
    max_rows: int
) -> Dict[str, Any]:
    """Preview Excel file content."""
    try:
        import io
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        sheet = wb.active

        rows = []
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i >= max_rows + 1:
                break
            rows.append([str(cell) if cell is not None else "" for cell in row])

        if not rows:
            return {"success": "false", "error": "Empty Excel file"}

        header = rows[0]
        data_rows = rows[1:]

        # Format as table
        table_str = " | ".join(header) + "\n"
        table_str += "-" * len(table_str) + "\n"
        for row in data_rows:
            table_str += " | ".join(str(cell)[:50] for cell in row) + "\n"

        return {
            "success": "true",
            "filename": metadata.get("filename"),
            "sheet_name": sheet.title,
            "columns": header,
            "column_count": len(header),
            "total_rows": sheet.max_row,
            "previewed_rows": len(data_rows),
            "data_preview": table_str,
            "message": f"Showing {len(data_rows)} of {sheet.max_row} rows"
        }

    except Exception as e:
        return {"success": "false", "error": f"Excel parse error: {str(e)}"}


def _preview_text(
    content: bytes,
    metadata: dict,
    max_chars: int
) -> Dict[str, Any]:
    """Preview text file content."""
    try:
        text = content.decode("utf-8")
        truncated = len(text) > max_chars
        preview = text[:max_chars]

        return {
            "success": "true",
            "filename": metadata.get("filename"),
            "total_chars": len(text),
            "total_lines": text.count('\n') + 1,
            "content": preview,
            "truncated": truncated,
            "message": f"Showing {len(preview)} of {len(text)} characters"
                       if truncated else "Full content shown"
        }

    except Exception as e:
        return {"success": "false", "error": f"Text decode error: {str(e)}"}


def format_preview_file_result(
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> str:
    """Format preview_file result for user display."""
    if result.get("success") == "true":
        filename = result.get("filename", "file")
        if "data_preview" in result:
            rows = result.get("previewed_rows", 0)
            return f"[📋 Previewed {filename}: {rows} rows]"
        elif "content" in result:
            chars = len(result.get("content", ""))
            return f"[📄 Previewed {filename}: {chars} chars]"
        return f"[📁 {result.get('message', 'File info retrieved')}]"

    error = result.get("error", "unknown")
    return f"[❌ Preview failed: {error[:60]}]"


# Tool configuration
from core.tools.base import ToolConfig

TOOL_CONFIG = ToolConfig(
    name="preview_file",
    definition=PREVIEW_FILE_TOOL,
    executor=preview_file,
    emoji="👁️",
    needs_bot_session=True,
    format_result=format_preview_file_result,
)
```

#### 1.2 Добавить в registry.py

```python
from core.tools.preview_file import TOOL_CONFIG as PREVIEW_FILE_CONFIG

TOOLS: Dict[str, ToolConfig] = {
    # ... existing tools ...
    "preview_file": PREVIEW_FILE_CONFIG,
}
```

#### 1.3 Добавить openpyxl в зависимости

```toml
# pyproject.toml
dependencies = [
    # ... existing ...
    "openpyxl>=3.1.0",  # Excel file reading
]
```

---

### Stage 2: Sequential delivery

**Цель**: `deliver_file(sequential=True)` форсирует turn break после доставки.

#### 2.1 Модифицировать `deliver_file.py`

```python
DELIVER_FILE_TOOL = {
    "name": "deliver_file",
    "description": """Deliver a cached file to the user.

<purpose>
Send files generated by execute_python/render_latex to user.
Files are cached for 30 min until delivered.
</purpose>

<delivery_modes>
DEFAULT (sequential=false):
  Multiple deliver_file calls send files in parallel.
  Use when files are related and should appear together.
  Example: "Here are both charts" → deliver_file × 2

SEQUENTIAL (sequential=true):
  Forces a turn break after delivery. Claude continues
  in next turn, allowing text between files.
  Use when explaining files one by one.
  Example: "First method..." → deliver → "Second method..." → deliver
</delivery_modes>

<workflow>
1. execute_python/render_latex → output_files with temp_id
2. (Optional) preview_file(temp_id) to verify content
3. deliver_file(temp_id) or deliver_file(temp_id, sequential=true)
</workflow>""",
    "input_schema": {
        "type": "object",
        "properties": {
            "temp_id": {
                "type": "string",
                "description": "Temporary file ID from output_files"
            },
            "caption": {
                "type": "string",
                "description": "Optional brief caption for the file"
            },
            "sequential": {
                "type": "boolean",
                "description": "If true, forces turn break after delivery. "
                               "Use when you need to write text after this "
                               "file before delivering next file. Default: false"
            }
        },
        "required": ["temp_id"]
    },
}


async def deliver_file(
    temp_id: str,
    bot: 'Bot',
    session: 'AsyncSession',
    caption: str | None = None,
    sequential: bool = False,
) -> Dict[str, Any]:
    """Deliver cached file to user.

    Args:
        temp_id: Temporary file ID.
        bot: Bot instance.
        session: DB session.
        caption: Optional caption.
        sequential: If True, force turn break after delivery.

    Returns:
        Result dict with _file_contents and optional _force_turn_break.
    """
    # ... existing implementation ...

    result: Dict[str, Any] = {
        "success": "true",
        "_file_contents": [{
            "filename": filename,
            "content": content,
            "mime_type": mime_type,
        }],
    }

    if caption:
        result["caption"] = caption

    # NEW: Sequential delivery marker
    if sequential:
        result["_force_turn_break"] = True
        logger.info("tools.deliver_file.sequential_mode",
                    temp_id=temp_id,
                    filename=filename)

    return result
```

#### 2.2 Модифицировать tool loop в `claude.py`

В функции `_stream_with_unified_events`, после обработки tool results:

```python
# After processing all tools in parallel
for coro in asyncio.as_completed(tool_tasks):
    idx, result = await coro
    tool = pending_tools[idx]

    # ... existing file processing ...

    # Check for sequential delivery
    if result.get("_force_turn_break"):
        # Mark that we need to break after this iteration
        force_turn_break = True
        # Store which tool triggered it for logging
        turn_break_tool = tool.name

    results[idx] = clean_result

# After formatting tool results and adding to conversation
if force_turn_break:
    logger.info("stream.unified.forced_turn_break",
                thread_id=thread_id,
                triggered_by=turn_break_tool)

    # Don't continue tool loop - return control to Claude
    # Claude will continue in a new API call with updated context

    # Get current text as partial answer
    partial_answer = stream.get_final_text()
    partial_display = stream.get_final_display()

    # Finalize current draft
    final_message = None
    if partial_display.strip():
        try:
            final_message = await dm.current.finalize(
                final_text=partial_display)
        except Exception as e:
            logger.error("stream.draft_finalize_failed",
                         thread_id=thread_id,
                         error=str(e))

    # Return with marker for handler to continue
    return partial_answer, final_message, True  # True = needs_continuation

# Normal end of iteration
return final_answer, final_message, False
```

#### 2.3 Обработка continuation в `_process_message_batch`

```python
async def _process_message_batch(...):
    # ... existing setup ...

    max_continuations = 5  # Prevent infinite loops

    for continuation in range(max_continuations):
        response_text, bot_message, needs_continuation = \
            await _stream_with_unified_events(...)

        if not needs_continuation:
            break

        logger.info("claude_handler.continuation_needed",
                    thread_id=thread_id,
                    continuation=continuation + 1)

        # Save partial response to DB
        # ... save message ...

        # Continue with new request (context includes tool results)
        # Request is rebuilt with updated conversation history

    else:
        logger.warning("claude_handler.max_continuations",
                       thread_id=thread_id)
```

---

### Stage 3: System prompt updates

#### 3.1 Обновить `GLOBAL_SYSTEM_PROMPT` в `config.py`

Добавить секцию о file delivery:

```python
FILE_DELIVERY_GUIDELINES = """
## File Delivery Guidelines

When generating files (via execute_python, render_latex):

### Verify Before Delivery
- Images: Already visible in tool results - check quality visually
- CSV/XLSX: Use preview_file to verify data before sending
- PDF: Check preview metadata (pages, size), deliver then analyze_pdf if needed

### Delivery Modes

**Parallel delivery** (default):
When files are related and should appear together.
```
execute_python → [chart1.png, chart2.png]
deliver_file(temp_id_1)
deliver_file(temp_id_2)
→ Both charts sent together
```

**Sequential delivery** (sequential=true):
When explaining files one by one with text between them.
```
"Метод Эйлера использует линейную аппроксимацию..."
render_latex → formula1
deliver_file(temp_id_1, sequential=true)
→ Formula sent, turn break

"Метод Рунге-Кутты более точен..."
render_latex → formula2
deliver_file(temp_id_2, sequential=true)
→ Formula sent
```

### Decision Guide
- User asks for "two charts comparing X and Y" → parallel (related)
- User asks to "explain two methods with formulas" → sequential (needs text between)
- User asks to "generate a report" → single file, no sequential needed
- Uncertain? Default to parallel, it's faster
"""
```

---

### Stage 4: Tests

#### 4.1 `tests/core/tools/test_preview_file.py`

```python
"""Tests for preview_file tool."""

import pytest
from core.tools.preview_file import (
    preview_file,
    _preview_csv,
    _preview_excel,
    _preview_text,
)


class TestPreviewCSV:
    """Tests for CSV preview."""

    def test_preview_csv_basic(self):
        content = b"name,age,city\nAlice,30,NYC\nBob,25,LA"
        metadata = {"filename": "data.csv"}

        result = _preview_csv(content, metadata, max_rows=10)

        assert result["success"] == "true"
        assert result["columns"] == ["name", "age", "city"]
        assert result["column_count"] == 3
        assert result["previewed_rows"] == 2
        assert "Alice" in result["data_preview"]

    def test_preview_csv_truncation(self):
        rows = ["col1,col2"] + [f"row{i},val{i}" for i in range(100)]
        content = "\n".join(rows).encode()
        metadata = {"filename": "big.csv"}

        result = _preview_csv(content, metadata, max_rows=5)

        assert result["previewed_rows"] == 5
        assert result["total_rows"] == 101

    def test_preview_csv_empty(self):
        result = _preview_csv(b"", {"filename": "empty.csv"}, 10)
        assert result["success"] == "false"


class TestPreviewText:
    """Tests for text preview."""

    def test_preview_text_full(self):
        content = b"Hello world\nLine 2\nLine 3"
        metadata = {"filename": "test.txt"}

        result = _preview_text(content, metadata, max_chars=1000)

        assert result["success"] == "true"
        assert result["content"] == "Hello world\nLine 2\nLine 3"
        assert result["truncated"] is False

    def test_preview_text_truncated(self):
        content = b"x" * 1000
        metadata = {"filename": "long.txt"}

        result = _preview_text(content, metadata, max_chars=100)

        assert len(result["content"]) == 100
        assert result["truncated"] is True


class TestDeliverFileSequential:
    """Tests for sequential delivery mode."""

    @pytest.mark.asyncio
    async def test_sequential_flag_in_result(self, mock_cache):
        """Sequential=True adds _force_turn_break marker."""
        mock_cache.set_file("exec_abc", b"content", {
            "filename": "test.png",
            "mime_type": "image/png"
        })

        from core.tools.deliver_file import deliver_file

        result = await deliver_file(
            temp_id="exec_abc",
            bot=None,
            session=None,
            sequential=True
        )

        assert result["_force_turn_break"] is True

    @pytest.mark.asyncio
    async def test_default_no_turn_break(self, mock_cache):
        """Default mode has no _force_turn_break."""
        mock_cache.set_file("exec_abc", b"content", {
            "filename": "test.png",
            "mime_type": "image/png"
        })

        from core.tools.deliver_file import deliver_file

        result = await deliver_file(
            temp_id="exec_abc",
            bot=None,
            session=None,
            sequential=False
        )

        assert "_force_turn_break" not in result
```

---

## File Changes Summary

### New Files:
- `bot/core/tools/preview_file.py` - Preview tool implementation
- `bot/tests/core/tools/test_preview_file.py` - Preview tool tests

### Modified Files:
- `bot/core/tools/deliver_file.py` - Add sequential parameter
- `bot/core/tools/registry.py` - Register preview_file
- `bot/telegram/handlers/claude.py` - Handle _force_turn_break
- `bot/config.py` - Update system prompt
- `bot/pyproject.toml` - Add openpyxl dependency
- `bot/Dockerfile` - Ensure openpyxl installed

---

## Migration

No database changes required. Redis cache format unchanged.

## Rollback

Remove `sequential` parameter handling - deliver_file falls back to parallel mode.

---

## Cost Impact

- **preview_file**: No API cost (local processing)
- **sequential=true**: +1 Claude API call per sequential delivery
  - Typical: 2 sequential files = 2 extra turns = ~2x token cost for that interaction
  - Mitigated by: prompt caching, user pays per token anyway

## Performance Impact

- **preview_file**: <10ms for CSV/text, <100ms for XLSX
- **sequential delivery**: +latency for each turn break (~1-3s per file)

---

## Future Enhancements

1. **Inline markers** (V4): Parse `[DELIVER:temp_id]` from text for true mixed content
2. **Batch preview**: `preview_files([temp_id1, temp_id2])` for efficiency
3. **Smart auto-sequential**: Detect when Claude writes text between deliver calls
