"""Tests for tools helpers (Phase 1.5).

Tests helper functions for tool use integration.
"""

from datetime import datetime
from datetime import timedelta
from unittest.mock import AsyncMock
from unittest.mock import Mock

import anthropic
from core.tools.helpers import extract_tool_uses
from core.tools.helpers import format_files_section
from core.tools.helpers import format_size
from core.tools.helpers import format_time_ago
from core.tools.helpers import format_tool_results
from core.tools.helpers import get_available_files
from db.models.user_file import FileSource
from db.models.user_file import FileType
import pytest


class TestFormatSize:
    """Tests for format_size() function."""

    def test_bytes(self):
        """Test formatting bytes."""
        assert format_size(100) == "100.0 B"
        assert format_size(1023) == "1023.0 B"

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        assert format_size(1024) == "1.0 KB"
        assert format_size(2048) == "2.0 KB"

    def test_megabytes(self):
        """Test formatting megabytes."""
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(1500000) == "1.4 MB"

    def test_gigabytes(self):
        """Test formatting gigabytes."""
        assert format_size(1024 * 1024 * 1024) == "1.0 GB"


class TestFormatTimeAgo:
    """Tests for format_time_ago() function."""

    def test_just_now(self):
        """Test 'just now' for recent time."""
        now = datetime.utcnow()
        assert format_time_ago(now) == "just now"

    def test_minutes_ago(self):
        """Test minutes ago."""
        time_5min_ago = datetime.utcnow() - timedelta(minutes=5)
        assert format_time_ago(time_5min_ago) == "5 min ago"

    def test_hours_ago(self):
        """Test hours ago."""
        time_2hours_ago = datetime.utcnow() - timedelta(hours=2)
        assert format_time_ago(time_2hours_ago) == "2 hours ago"

    def test_days_ago(self):
        """Test days ago."""
        time_3days_ago = datetime.utcnow() - timedelta(days=3)
        assert format_time_ago(time_3days_ago) == "3 days ago"


class TestFormatFilesSection:
    """Tests for format_files_section() function."""

    def test_empty_files(self):
        """Test with no files."""
        result = format_files_section([])
        assert result == ""

    def test_single_file(self):
        """Test formatting single file."""
        mock_file = Mock()
        mock_file.filename = "test.jpg"
        mock_file.file_type = FileType.IMAGE
        mock_file.file_size = 1024
        mock_file.uploaded_at = datetime.utcnow()
        mock_file.claude_file_id = "file_abc123"

        result = format_files_section([mock_file])

        assert "Available files in this conversation:" in result
        assert "test.jpg" in result
        assert "file_abc123" in result
        assert "image" in result

    def test_multiple_files(self):
        """Test formatting multiple files."""
        mock_file1 = Mock()
        mock_file1.filename = "image.jpg"
        mock_file1.file_type = FileType.IMAGE
        mock_file1.file_size = 2048
        mock_file1.uploaded_at = datetime.utcnow()
        mock_file1.claude_file_id = "file_1"

        mock_file2 = Mock()
        mock_file2.filename = "doc.pdf"
        mock_file2.file_type = FileType.PDF
        mock_file2.file_size = 5120
        mock_file2.uploaded_at = datetime.utcnow()
        mock_file2.claude_file_id = "file_2"

        result = format_files_section([mock_file1, mock_file2])

        assert "image.jpg" in result
        assert "doc.pdf" in result
        assert "file_1" in result
        assert "file_2" in result


class TestExtractToolUses:
    """Tests for extract_tool_uses() function."""

    def test_no_tool_uses(self):
        """Test with no tool_use blocks."""
        content = [anthropic.types.TextBlock(type="text", text="Hello")]

        result = extract_tool_uses(content)

        assert result == []

    def test_single_tool_use(self):
        """Test extracting single tool_use."""
        tool_use = anthropic.types.ToolUseBlock(
            type="tool_use",
            id="toolu_123",
            name="analyze_image",
            input={
                "claude_file_id": "file_abc",
                "question": "What is this?"
            })
        content = [tool_use]

        result = extract_tool_uses(content)

        assert len(result) == 1
        assert result[0]["id"] == "toolu_123"
        assert result[0]["name"] == "analyze_image"
        assert result[0]["input"]["claude_file_id"] == "file_abc"

    def test_mixed_content(self):
        """Test extracting tool_use from mixed content."""
        content = [
            anthropic.types.TextBlock(type="text", text="Let me check"),
            anthropic.types.ToolUseBlock(type="tool_use",
                                         id="toolu_456",
                                         name="analyze_image",
                                         input={
                                             "claude_file_id": "file_xyz",
                                             "question": "Details?"
                                         })
        ]

        result = extract_tool_uses(content)

        assert len(result) == 1
        assert result[0]["id"] == "toolu_456"


class TestFormatToolResults:
    """Tests for format_tool_results() function."""

    def test_success_result(self):
        """Test formatting successful tool result."""
        tool_uses = [{
            "id": "toolu_123",
            "name": "analyze_image",
            "input": {
                "claude_file_id": "file_abc"
            }
        }]
        results = [{"analysis": "A beautiful sunset", "tokens_used": "150"}]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 1
        assert formatted[0]["type"] == "tool_result"
        assert formatted[0]["tool_use_id"] == "toolu_123"
        assert "is_error" not in formatted[0]
        assert '"analysis"' in formatted[0]["content"]

    def test_error_result(self):
        """Test formatting error result."""
        tool_uses = [{
            "id": "toolu_456",
            "name": "analyze_image",
            "input": {
                "claude_file_id": "file_xyz"
            }
        }]
        results = [{"error": "File not found"}]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 1
        assert formatted[0]["type"] == "tool_result"
        assert formatted[0]["tool_use_id"] == "toolu_456"
        assert formatted[0]["is_error"] is True
        assert formatted[0]["content"] == "File not found"

    def test_mismatched_lengths(self):
        """Test error when tool_uses and results have different lengths."""
        tool_uses = [{"id": "toolu_1", "name": "tool1", "input": {}}]
        results = [{"result": "ok"}, {"result": "ok2"}]

        with pytest.raises(ValueError, match="Mismatch"):
            format_tool_results(tool_uses, results)


@pytest.mark.asyncio
class TestGetAvailableFiles:
    """Tests for get_available_files() function."""

    async def test_get_files_success(self):
        """Test successful retrieval of files."""
        mock_repo = AsyncMock()
        mock_file = Mock()
        mock_file.filename = "test.jpg"
        mock_repo.get_by_thread_id.return_value = [mock_file]

        files = await get_available_files(thread_id=42,
                                          user_file_repo=mock_repo)

        mock_repo.get_by_thread_id.assert_called_once_with(42)
        assert len(files) == 1
        assert files[0].filename == "test.jpg"

    async def test_get_files_empty(self):
        """Test with no files."""
        mock_repo = AsyncMock()
        mock_repo.get_by_thread_id.return_value = []

        files = await get_available_files(thread_id=99,
                                          user_file_repo=mock_repo)

        assert files == []
