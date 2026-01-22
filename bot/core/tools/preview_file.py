"""Preview cached file content without delivering to user.

Allows Claude to analyze file content (CSV rows, text content, etc.)
before deciding whether to deliver or regenerate the file.

Supports:
- CSV: Shows header + first N rows as table
- XLSX: Shows sheet data (requires openpyxl)
- Text/JSON/XML: Shows first N characters
- PDF/Images: Returns info message (use other tools)

NO __init__.py - use direct import:
    from core.tools.preview_file import preview_file, PREVIEW_FILE_TOOL
"""

from typing import Any, Dict, TYPE_CHECKING

from cache.exec_cache import get_exec_file
from cache.exec_cache import get_exec_meta
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

PREVIEW_FILE_TOOL = {
    "name":
        "preview_file",
    "description":
        """Preview cached file content without sending to user.

<purpose>
Analyze file content before deciding to deliver. Useful for:
- CSV/XLSX: See actual data rows, verify column values
- Text files: Read full content
- PDF: Cannot preview content (use deliver_file then analyze_pdf)
- Images: Already visible in execute_python/render_latex result
</purpose>

<when_to_use>
- Verify CSV/XLSX data is correct before sending
- Check text file content matches expectations
- Analyze tabular data quality
- Review generated code or config files
</when_to_use>

<supported_formats>
- CSV: Shows header + data rows as formatted table
- XLSX/XLS: Shows first sheet data as table
- Text/JSON/XML/JS: Shows content with line numbers
- Images: Already visible in tool results (no preview needed)
- PDF: Use deliver_file then analyze_pdf
</supported_formats>

<workflow>
1. execute_python generates CSV → output_files with temp_id
2. preview_file(temp_id, max_rows=10) → see first 10 rows
3. If data looks good → deliver_file(temp_id)
4. If data wrong → re-run execute_python with fixes
</workflow>

<cost>
FREE - local processing only.
</cost>""",
    "input_schema": {
        "type": "object",
        "properties": {
            "temp_id": {
                "type": "string",
                "description": "Temporary file ID from output_files "
                               "(e.g., 'exec_abc123')"
            },
            "max_rows": {
                "type": "integer",
                "description": "Max rows to show for CSV/XLSX (default: 20)"
            },
            "max_chars": {
                "type":
                    "integer",
                "description":
                    "Max characters to show for text files (default: 5000)"
            }
        },
        "required": ["temp_id"]
    }
}


def _preview_csv(
    content: bytes,
    metadata: Dict[str, Any],
    max_rows: int,
) -> Dict[str, Any]:
    """Preview CSV file content.

    Args:
        content: Raw file bytes.
        metadata: File metadata from cache.
        max_rows: Maximum data rows to include.

    Returns:
        Dict with parsed CSV data or error.
    """
    try:
        import csv  # pylint: disable=import-outside-toplevel
        import io  # pylint: disable=import-outside-toplevel

        # Decode with fallback
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

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

        # Format as table with column width limits
        col_widths = []
        for col_idx, col_name in enumerate(header):
            col_vals = [col_name] + [
                row[col_idx] if col_idx < len(row) else "" for row in data_rows
            ]
            max_width = min(30, max(len(str(v)) for v in col_vals))
            col_widths.append(max_width)

        def format_row(row):
            cells = []
            for i, cell in enumerate(row):
                width = col_widths[i] if i < len(col_widths) else 20
                cell_str = str(cell)[:width]
                cells.append(cell_str.ljust(width))
            return " | ".join(cells)

        table_lines = [format_row(header)]
        table_lines.append("-" * len(table_lines[0]))
        for row in data_rows:
            table_lines.append(format_row(row))

        table_str = "\n".join(table_lines)

        logger.info("preview_file.csv_parsed",
                    filename=metadata.get("filename"),
                    columns=len(header),
                    rows_shown=len(data_rows),
                    total_rows=total_rows)

        return {
            "success": "true",
            "filename": metadata.get("filename"),
            "file_type": "csv",
            "columns": header,
            "column_count": len(header),
            "total_rows": total_rows,
            "previewed_rows": len(data_rows),
            "data_preview": table_str,
            "message": f"Showing {len(data_rows)} of ~{total_rows} rows"
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("preview_file.csv_error",
                       error=str(e),
                       filename=metadata.get("filename"))
        return {"success": "false", "error": f"CSV parse error: {str(e)}"}


def _preview_excel(
    content: bytes,
    metadata: Dict[str, Any],
    max_rows: int,
) -> Dict[str, Any]:
    """Preview Excel file content.

    Args:
        content: Raw file bytes.
        metadata: File metadata from cache.
        max_rows: Maximum data rows to include.

    Returns:
        Dict with parsed Excel data or error.
    """
    try:
        import io  # pylint: disable=import-outside-toplevel

        import openpyxl  # pylint: disable=import-outside-toplevel

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        sheet = wb.active

        if sheet is None:
            return {"success": "false", "error": "No active sheet in workbook"}

        rows = []
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i >= max_rows + 1:
                break
            rows.append([str(cell) if cell is not None else "" for cell in row])

        wb.close()

        if not rows:
            return {"success": "false", "error": "Empty Excel file"}

        header = rows[0]
        data_rows = rows[1:]

        # Format as table
        col_widths = []
        for col_idx, col_name in enumerate(header):
            col_vals = [col_name] + [
                row[col_idx] if col_idx < len(row) else "" for row in data_rows
            ]
            max_width = min(30, max(len(str(v)) for v in col_vals))
            col_widths.append(max_width)

        def format_row(row):
            cells = []
            for i, cell in enumerate(row):
                width = col_widths[i] if i < len(col_widths) else 20
                cell_str = str(cell)[:width]
                cells.append(cell_str.ljust(width))
            return " | ".join(cells)

        table_lines = [format_row(header)]
        table_lines.append("-" * len(table_lines[0]))
        for row in data_rows:
            table_lines.append(format_row(row))

        table_str = "\n".join(table_lines)

        logger.info("preview_file.excel_parsed",
                    filename=metadata.get("filename"),
                    sheet=sheet.title,
                    columns=len(header),
                    rows_shown=len(data_rows),
                    total_rows=sheet.max_row)

        return {
            "success": "true",
            "filename": metadata.get("filename"),
            "file_type": "xlsx",
            "sheet_name": sheet.title,
            "columns": header,
            "column_count": len(header),
            "total_rows": sheet.max_row or 0,
            "previewed_rows": len(data_rows),
            "data_preview": table_str,
            "message": f"Showing {len(data_rows)} of {sheet.max_row} rows "
                       f"from sheet '{sheet.title}'"
        }

    except ImportError:
        return {
            "success": "false",
            "error": "openpyxl not installed. Cannot preview Excel files."
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("preview_file.excel_error",
                       error=str(e),
                       filename=metadata.get("filename"))
        return {"success": "false", "error": f"Excel parse error: {str(e)}"}


def _preview_text(
    content: bytes,
    metadata: Dict[str, Any],
    max_chars: int,
) -> Dict[str, Any]:
    """Preview text file content.

    Args:
        content: Raw file bytes.
        metadata: File metadata from cache.
        max_chars: Maximum characters to include.

    Returns:
        Dict with text content or error.
    """
    try:
        # Decode with fallback
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        total_chars = len(text)
        total_lines = text.count('\n') + 1
        truncated = total_chars > max_chars

        preview = text[:max_chars]

        # Add line numbers for readability
        lines = preview.split('\n')
        numbered_lines = []
        for i, line in enumerate(lines, 1):
            # Truncate long lines
            if len(line) > 120:
                line = line[:117] + "..."
            numbered_lines.append(f"{i:4d} | {line}")

        content_with_numbers = "\n".join(numbered_lines)

        logger.info("preview_file.text_parsed",
                    filename=metadata.get("filename"),
                    total_chars=total_chars,
                    shown_chars=len(preview),
                    truncated=truncated)

        return {
            "success":
                "true",
            "filename":
                metadata.get("filename"),
            "file_type":
                "text",
            "total_chars":
                total_chars,
            "total_lines":
                total_lines,
            "content":
                content_with_numbers,
            "truncated":
                truncated,
            "message": (f"Showing {len(preview)} of {total_chars} characters"
                        if truncated else "Full content shown")
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("preview_file.text_error",
                       error=str(e),
                       filename=metadata.get("filename"))
        return {"success": "false", "error": f"Text decode error: {str(e)}"}


# pylint: disable=too-many-return-statements
async def preview_file(
    temp_id: str,
    bot: 'Bot',
    session: 'AsyncSession',
    max_rows: int = 20,
    max_chars: int = 5000,
) -> Dict[str, Any]:
    """Preview file content from cache without delivering.

    Args:
        temp_id: Temporary file ID from output_files.
        bot: Bot instance (unused, interface consistency).
        session: DB session (unused, interface consistency).
        max_rows: Maximum rows for tabular data (CSV/XLSX).
        max_chars: Maximum characters for text files.

    Returns:
        Dict with file content preview or error message.
    """
    # Mark unused args
    _ = bot
    _ = session

    logger.info("tools.preview_file.called",
                temp_id=temp_id,
                max_rows=max_rows,
                max_chars=max_chars)

    # Get metadata
    metadata = await get_exec_meta(temp_id)
    if not metadata:
        logger.warning("tools.preview_file.not_found", temp_id=temp_id)
        return {
            "success": "false",
            "error": f"File '{temp_id}' not found or expired (30 min TTL). "
                     "Use execute_python to regenerate."
        }

    # Get content
    content = await get_exec_file(temp_id)
    if not content:
        logger.warning("tools.preview_file.content_missing", temp_id=temp_id)
        return {
            "success": "false",
            "error": f"File content for '{temp_id}' not found. "
                     "Use execute_python to regenerate."
        }

    mime_type = metadata.get("mime_type", "")
    filename = metadata.get("filename", "unknown")

    logger.debug("tools.preview_file.processing",
                 temp_id=temp_id,
                 filename=filename,
                 mime_type=mime_type,
                 size_bytes=len(content))

    # Route to appropriate preview handler based on type
    if mime_type == "text/csv" or filename.endswith(".csv"):
        return _preview_csv(content, metadata, max_rows)

    if mime_type in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
    ) or filename.endswith((".xlsx", ".xls")):
        return _preview_excel(content, metadata, max_rows)

    if mime_type.startswith("text/") or mime_type in (
            "application/json",
            "application/xml",
            "application/javascript",
    ) or filename.endswith((".txt", ".json", ".xml", ".js", ".py", ".md")):
        return _preview_text(content, metadata, max_chars)

    if mime_type.startswith("image/"):
        return {
            "success": "true",
            "filename": filename,
            "file_type": "image",
            "size_bytes": len(content),
            "message": "Image files are already visible in tool results. "
                       "No separate preview needed - you can see the image "
                       "in the execute_python or render_latex response.",
            "preview": metadata.get("preview", ""),
        }

    if mime_type == "application/pdf":
        return {
            "success": "true",
            "filename": filename,
            "file_type": "pdf",
            "size_bytes": len(content),
            "message": "PDF content cannot be previewed directly. "
                       "To analyze: deliver_file(temp_id) first, then use "
                       "analyze_pdf(claude_file_id) with the returned ID.",
            "preview": metadata.get("preview", ""),
        }

    # Binary/unknown type
    return {
        "success": "true",
        "filename": filename,
        "file_type": "binary",
        "mime_type": mime_type,
        "size_bytes": len(content),
        "message": f"Binary file type '{mime_type}' cannot be previewed. "
                   "Use deliver_file(temp_id) to send to user.",
        "preview": metadata.get("preview", ""),
    }


def format_preview_file_result(
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> str:
    """Format preview_file result for user display.

    Args:
        tool_input: The input parameters.
        result: The result dictionary.

    Returns:
        Formatted system message string.
    """
    _ = tool_input  # Unused

    if result.get("success") == "true":
        filename = result.get("filename", "file")
        file_type = result.get("file_type", "")

        if file_type in ("csv", "xlsx"):
            rows = result.get("previewed_rows", 0)
            cols = result.get("column_count", 0)
            return f"[📋 Preview {filename}: {rows} rows × {cols} cols]"

        if file_type == "text":
            lines = result.get("total_lines", 0)
            return f"[📄 Preview {filename}: {lines} lines]"

        # Image, PDF, binary - just info message
        return f"[📁 {filename}: {result.get('message', 'info')[:60]}]"

    error = result.get("error", "unknown error")
    preview = error[:60] + "..." if len(error) > 60 else error
    return f"[❌ Preview failed: {preview}]"


# Unified tool configuration
from core.tools.base import ToolConfig  # pylint: disable=wrong-import-position

TOOL_CONFIG = ToolConfig(
    name="preview_file",
    definition=PREVIEW_FILE_TOOL,
    executor=preview_file,
    emoji="👁️",
    needs_bot_session=True,
    format_result=format_preview_file_result,
)
