"""Tests for preview_file tool.

Tests the preview_file tool functionality including:
- CSV file preview with data table
- Excel file preview (requires openpyxl)
- Text file preview
- Image/PDF info messages
- Error handling for missing files
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest


class TestPreviewCSV:
    """Tests for CSV preview functionality."""

    def test_preview_csv_basic(self):
        """Test basic CSV preview with header and data."""
        from core.tools.preview_file import _preview_csv

        content = b"name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,SF"
        metadata = {"filename": "data.csv"}

        result = _preview_csv(content, metadata, max_rows=10)

        assert result["success"] == "true"
        assert result["columns"] == ["name", "age", "city"]
        assert result["column_count"] == 3
        assert result["previewed_rows"] == 3
        assert "Alice" in result["data_preview"]
        assert "Bob" in result["data_preview"]
        assert "Charlie" in result["data_preview"]

    def test_preview_csv_truncation(self):
        """Test CSV preview respects max_rows limit."""
        from core.tools.preview_file import _preview_csv

        rows = ["col1,col2"] + [f"row{i},val{i}" for i in range(100)]
        content = "\n".join(rows).encode()
        metadata = {"filename": "big.csv"}

        result = _preview_csv(content, metadata, max_rows=5)

        assert result["success"] == "true"
        assert result["previewed_rows"] == 5
        # total_rows counts newlines, so 101 lines = 100 newlines
        assert result["total_rows"] == 100
        assert "row4" in result["data_preview"]
        assert "row5" not in result["data_preview"]  # 6th row (0-indexed)

    def test_preview_csv_empty(self):
        """Test CSV preview handles empty file."""
        from core.tools.preview_file import _preview_csv

        result = _preview_csv(b"", {"filename": "empty.csv"}, 10)

        assert result["success"] == "false"
        assert "Empty CSV" in result["error"]

    def test_preview_csv_latin1_encoding(self):
        """Test CSV preview handles latin-1 encoding."""
        from core.tools.preview_file import _preview_csv

        # Latin-1 encoded content (not valid UTF-8)
        content = "name,value\nTest,café".encode("latin-1")
        metadata = {"filename": "latin.csv"}

        result = _preview_csv(content, metadata, max_rows=10)

        assert result["success"] == "true"
        assert result["previewed_rows"] == 1


class TestPreviewText:
    """Tests for text file preview functionality."""

    def test_preview_text_full(self):
        """Test text preview shows full content when under limit."""
        from core.tools.preview_file import _preview_text

        content = b"Hello world\nLine 2\nLine 3"
        metadata = {"filename": "test.txt"}

        result = _preview_text(content, metadata, max_chars=1000)

        assert result["success"] == "true"
        assert result["truncated"] is False
        assert result["total_lines"] == 3
        assert "Hello world" in result["content"]

    def test_preview_text_truncated(self):
        """Test text preview truncates long content."""
        from core.tools.preview_file import _preview_text

        content = b"x" * 1000
        metadata = {"filename": "long.txt"}

        result = _preview_text(content, metadata, max_chars=100)

        assert result["success"] == "true"
        assert result["truncated"] is True
        assert result["total_chars"] == 1000
        assert "100 of 1000" in result["message"]

    def test_preview_text_line_numbers(self):
        """Test text preview includes line numbers."""
        from core.tools.preview_file import _preview_text

        content = b"Line 1\nLine 2\nLine 3"
        metadata = {"filename": "numbered.txt"}

        result = _preview_text(content, metadata, max_chars=1000)

        assert result["success"] == "true"
        # Check line numbers in output
        assert "1 |" in result["content"]
        assert "2 |" in result["content"]


class TestPreviewFile:
    """Tests for main preview_file function."""

    @pytest.mark.asyncio
    async def test_preview_file_not_found(self):
        """Test preview_file returns error when file not in cache."""
        from core.tools.preview_file import preview_file

        with patch("core.tools.preview_file.get_exec_meta",
                   new_callable=AsyncMock) as mock_meta:
            mock_meta.return_value = None

            result = await preview_file(
                temp_id="nonexistent",
                bot=None,
                session=None,
            )

            assert result["success"] == "false"
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_preview_file_content_missing(self):
        """Test preview_file returns error when content missing."""
        from core.tools.preview_file import preview_file

        with patch("core.tools.preview_file.get_exec_meta",
                   new_callable=AsyncMock) as mock_meta, \
             patch("core.tools.preview_file.get_exec_file",
                   new_callable=AsyncMock) as mock_file:

            mock_meta.return_value = {
                "filename": "test.csv",
                "mime_type": "text/csv"
            }
            mock_file.return_value = None

            result = await preview_file(
                temp_id="exec_abc",
                bot=None,
                session=None,
            )

            assert result["success"] == "false"
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_preview_file_csv(self):
        """Test preview_file routes CSV to correct handler."""
        from core.tools.preview_file import preview_file

        with patch("core.tools.preview_file.get_exec_meta",
                   new_callable=AsyncMock) as mock_meta, \
             patch("core.tools.preview_file.get_exec_file",
                   new_callable=AsyncMock) as mock_file:

            mock_meta.return_value = {
                "filename": "data.csv",
                "mime_type": "text/csv"
            }
            mock_file.return_value = b"a,b,c\n1,2,3"

            result = await preview_file(
                temp_id="exec_abc",
                bot=None,
                session=None,
            )

            assert result["success"] == "true"
            assert result["file_type"] == "csv"
            assert "a" in result["columns"]

    @pytest.mark.asyncio
    async def test_preview_file_image_info(self):
        """Test preview_file returns info message for images."""
        from core.tools.preview_file import preview_file

        with patch("core.tools.preview_file.get_exec_meta",
                   new_callable=AsyncMock) as mock_meta, \
             patch("core.tools.preview_file.get_exec_file",
                   new_callable=AsyncMock) as mock_file:

            mock_meta.return_value = {
                "filename": "chart.png",
                "mime_type": "image/png",
                "preview": "Image 800x600"
            }
            mock_file.return_value = b"fake png data"

            result = await preview_file(
                temp_id="exec_abc",
                bot=None,
                session=None,
            )

            assert result["success"] == "true"
            assert result["file_type"] == "image"
            assert "already visible" in result["message"]

    @pytest.mark.asyncio
    async def test_preview_file_pdf_info(self):
        """Test preview_file returns info message for PDFs."""
        from core.tools.preview_file import preview_file

        with patch("core.tools.preview_file.get_exec_meta",
                   new_callable=AsyncMock) as mock_meta, \
             patch("core.tools.preview_file.get_exec_file",
                   new_callable=AsyncMock) as mock_file:

            mock_meta.return_value = {
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "preview": "PDF, 5 pages"
            }
            mock_file.return_value = b"fake pdf data"

            result = await preview_file(
                temp_id="exec_abc",
                bot=None,
                session=None,
            )

            assert result["success"] == "true"
            assert result["file_type"] == "pdf"
            assert "deliver_file" in result["message"]
            assert "analyze_pdf" in result["message"]


class TestToolConfig:
    """Tests for preview_file tool configuration."""

    def test_tool_config_name(self):
        """Test tool config has correct name."""
        from core.tools.preview_file import TOOL_CONFIG

        assert TOOL_CONFIG.name == "preview_file"

    def test_tool_config_emoji(self):
        """Test tool config has emoji."""
        from core.tools.preview_file import TOOL_CONFIG

        assert TOOL_CONFIG.emoji == "👁️"

    def test_tool_config_needs_bot_session(self):
        """Test tool config requires bot session."""
        from core.tools.preview_file import TOOL_CONFIG

        assert TOOL_CONFIG.needs_bot_session is True

    def test_tool_definition_has_required_params(self):
        """Test tool definition has temp_id as required."""
        from core.tools.preview_file import PREVIEW_FILE_TOOL

        assert "temp_id" in PREVIEW_FILE_TOOL["input_schema"]["required"]

    def test_tool_definition_has_optional_params(self):
        """Test tool definition has optional max_rows and max_chars."""
        from core.tools.preview_file import PREVIEW_FILE_TOOL

        props = PREVIEW_FILE_TOOL["input_schema"]["properties"]
        assert "max_rows" in props
        assert "max_chars" in props


class TestFormatPreviewFileResult:
    """Tests for preview_file result formatting."""

    def test_format_csv_result(self):
        """Test formatting CSV preview result."""
        from core.tools.preview_file import format_preview_file_result

        result = {
            "success": "true",
            "filename": "data.csv",
            "file_type": "csv",
            "previewed_rows": 10,
            "column_count": 5,
        }

        formatted = format_preview_file_result({}, result)

        assert "data.csv" in formatted
        assert "10 rows" in formatted
        assert "5 cols" in formatted

    def test_format_text_result(self):
        """Test formatting text preview result."""
        from core.tools.preview_file import format_preview_file_result

        result = {
            "success": "true",
            "filename": "readme.txt",
            "file_type": "text",
            "total_lines": 50,
        }

        formatted = format_preview_file_result({}, result)

        assert "readme.txt" in formatted
        assert "50 lines" in formatted

    def test_format_error_result(self):
        """Test formatting error result."""
        from core.tools.preview_file import format_preview_file_result

        result = {"success": "false", "error": "File not found in cache"}

        formatted = format_preview_file_result({}, result)

        assert "Preview failed" in formatted
        assert "not found" in formatted
