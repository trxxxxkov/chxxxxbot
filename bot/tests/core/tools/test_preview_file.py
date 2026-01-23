"""Tests for universal preview_file tool.

Tests the preview_file tool functionality including:
- CSV file preview with data table
- Excel file preview (requires openpyxl)
- Text file preview
- Image preview via Claude Vision API
- PDF preview via Claude PDF API
- Audio/video metadata
- Binary file suggestions
- Error handling for missing files
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
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
        assert "Alice" in result["content"]
        assert "Bob" in result["content"]
        assert "Charlie" in result["content"]

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
        assert "row4" in result["content"]
        # row5 is not shown (6th row, 0-indexed)
        assert "row5" not in result["content"]

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
    async def test_preview_file_exec_not_found(self):
        """Test preview_file returns error when exec file not in cache."""
        from core.tools.preview_file import preview_file

        with patch("core.tools.preview_file.get_exec_meta",
                   new_callable=AsyncMock) as mock_meta:
            mock_meta.return_value = None

            result = await preview_file(
                file_id="exec_nonexistent",
                bot=MagicMock(),
                session=AsyncMock(),
            )

            assert result["success"] == "false"
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_preview_file_exec_content_missing(self):
        """Test preview_file returns error when exec content missing."""
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
                file_id="exec_abc",
                bot=MagicMock(),
                session=AsyncMock(),
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
                file_id="exec_abc",
                bot=MagicMock(),
                session=AsyncMock(),
            )

            assert result["success"] == "true"
            assert result["file_type"] == "csv"
            assert "a" in result["columns"]

    @pytest.mark.asyncio
    async def test_preview_file_audio_video(self):
        """Test preview_file returns metadata for audio/video."""
        from core.tools.preview_file import preview_file

        with patch("core.tools.preview_file.get_exec_meta",
                   new_callable=AsyncMock) as mock_meta, \
             patch("core.tools.preview_file.get_exec_file",
                   new_callable=AsyncMock) as mock_file:

            mock_meta.return_value = {
                "filename": "audio.mp3",
                "mime_type": "audio/mpeg"
            }
            mock_file.return_value = b"fake mp3 data"

            result = await preview_file(
                file_id="exec_abc",
                bot=MagicMock(),
                session=AsyncMock(),
            )

            assert result["success"] == "true"
            assert result["file_type"] == "audio_video"
            assert "transcribe_audio" in result["message"]

    @pytest.mark.asyncio
    async def test_preview_file_binary(self):
        """Test preview_file suggests library for binary files."""
        from core.tools.preview_file import preview_file

        with patch("core.tools.preview_file.get_exec_meta",
                   new_callable=AsyncMock) as mock_meta, \
             patch("core.tools.preview_file.get_exec_file",
                   new_callable=AsyncMock) as mock_file:

            mock_meta.return_value = {
                "filename": "data.parquet",
                "mime_type": "application/octet-stream"
            }
            mock_file.return_value = b"parquet binary data"

            result = await preview_file(
                file_id="exec_abc",
                bot=MagicMock(),
                session=AsyncMock(),
            )

            assert result["success"] == "true"
            assert result["file_type"] == "binary"
            assert result["suggested_library"] == "pandas or pyarrow"
            assert "execute_python" in result["content"]

    @pytest.mark.asyncio
    async def test_preview_file_db_not_found(self):
        """Test preview_file returns error when file not in database."""
        from core.tools.preview_file import preview_file

        mock_repo = MagicMock()
        mock_repo.get_by_claude_file_id = AsyncMock(return_value=None)
        mock_repo.get_by_telegram_file_id = AsyncMock(return_value=None)

        with patch("core.tools.preview_file.UserFileRepository",
                   return_value=mock_repo):
            result = await preview_file(
                file_id="file_unknown",
                bot=MagicMock(),
                session=AsyncMock(),
            )

            assert result["success"] == "false"
            assert "not found" in result["error"]


class TestFileTypeDetection:
    """Tests for file type detection helpers."""

    def test_is_text_format(self):
        """Test text format detection."""
        from core.tools.preview_file import _is_text_format

        assert _is_text_format("text/plain", "test.txt") is True
        assert _is_text_format("text/csv", "data.csv") is True
        assert _is_text_format("application/json", "config.json") is True
        assert _is_text_format("application/octet-stream", "script.py") is True
        assert _is_text_format("application/octet-stream",
                               "binary.bin") is False

    def test_is_spreadsheet(self):
        """Test spreadsheet detection."""
        from core.tools.preview_file import _is_spreadsheet

        assert _is_spreadsheet("text/csv", "data.csv") is True
        assert _is_spreadsheet(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet", "data.xlsx") is True
        assert _is_spreadsheet("application/octet-stream", "file.xlsx") is True
        assert _is_spreadsheet("text/plain", "file.txt") is False

    def test_is_image(self):
        """Test image detection."""
        from core.tools.preview_file import _is_image

        assert _is_image("image/png") is True
        assert _is_image("image/jpeg") is True
        assert _is_image("text/plain") is False

    def test_is_pdf(self):
        """Test PDF detection."""
        from core.tools.preview_file import _is_pdf

        assert _is_pdf("application/pdf", "doc.pdf") is True
        assert _is_pdf("application/octet-stream", "doc.pdf") is True
        assert _is_pdf("application/octet-stream", "doc.txt") is False

    def test_is_audio_video(self):
        """Test audio/video detection."""
        from core.tools.preview_file import _is_audio_video

        assert _is_audio_video("audio/mpeg") is True
        assert _is_audio_video("video/mp4") is True
        assert _is_audio_video("text/plain") is False


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
        """Test tool definition has file_id as required."""
        from core.tools.preview_file import PREVIEW_FILE_TOOL

        assert "file_id" in PREVIEW_FILE_TOOL["input_schema"]["required"]

    def test_tool_definition_has_optional_params(self):
        """Test tool definition has optional max_rows, max_chars, question."""
        from core.tools.preview_file import PREVIEW_FILE_TOOL

        props = PREVIEW_FILE_TOOL["input_schema"]["properties"]
        assert "max_rows" in props
        assert "max_chars" in props
        assert "question" in props


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

    def test_format_image_result(self):
        """Test formatting image preview result."""
        from core.tools.preview_file import format_preview_file_result

        result = {
            "success": "true",
            "filename": "photo.jpg",
            "file_type": "image",
            "cost_usd": "0.001234",
        }

        formatted = format_preview_file_result({}, result)

        assert "photo.jpg" in formatted
        assert "analyzed" in formatted

    def test_format_error_result(self):
        """Test formatting error result."""
        from core.tools.preview_file import format_preview_file_result

        result = {"success": "false", "error": "File not found in cache"}

        formatted = format_preview_file_result({}, result)

        assert "Preview failed" in formatted
        assert "not found" in formatted
