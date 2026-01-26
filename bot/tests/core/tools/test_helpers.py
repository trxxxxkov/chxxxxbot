"""Tests for tools helpers (Phase 1.5).

Tests helper functions for tool use integration.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
import time
from unittest.mock import AsyncMock
from unittest.mock import Mock

import anthropic
from core.tools.helpers import extract_tool_uses
from core.tools.helpers import format_files_section
from core.tools.helpers import format_size
from core.tools.helpers import format_time_ago
from core.tools.helpers import format_tool_results
from core.tools.helpers import format_ttl_remaining
from core.tools.helpers import format_unified_files_section
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
        now = datetime.now(timezone.utc)
        assert format_time_ago(now) == "just now"

    def test_minutes_ago(self):
        """Test minutes ago."""
        time_5min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert format_time_ago(time_5min_ago) == "5 min ago"

    def test_hours_ago(self):
        """Test hours ago."""
        time_2hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
        assert format_time_ago(time_2hours_ago) == "2 hours ago"

    def test_days_ago(self):
        """Test days ago."""
        time_3days_ago = datetime.now(timezone.utc) - timedelta(days=3)
        assert format_time_ago(time_3days_ago) == "3 days ago"

    def test_timezone_naive_datetime(self):
        """Test that timezone-naive datetimes are handled correctly.

        Regression test: Database datetimes may be timezone-naive while
        datetime.now(timezone.utc) is timezone-aware. This caused:
        TypeError: can't subtract offset-naive and offset-aware datetimes
        """
        # Create timezone-naive datetime (like from SQLAlchemy DateTime)
        naive_time = datetime.now() - timedelta(hours=1)
        assert naive_time.tzinfo is None

        # Should not raise an error
        result = format_time_ago(naive_time)
        assert result == "1 hour ago"


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
        mock_file.uploaded_at = datetime.now(timezone.utc)
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
        mock_file1.uploaded_at = datetime.now(timezone.utc)
        mock_file1.claude_file_id = "file_1"

        mock_file2 = Mock()
        mock_file2.filename = "doc.pdf"
        mock_file2.file_type = FileType.PDF
        mock_file2.file_size = 5120
        mock_file2.uploaded_at = datetime.now(timezone.utc)
        mock_file2.claude_file_id = "file_2"

        result = format_files_section([mock_file1, mock_file2])

        assert "image.jpg" in result
        assert "doc.pdf" in result
        assert "file_1" in result
        assert "file_2" in result

    def test_upload_context_displayed(self):
        """Test that upload_context is displayed for files."""
        mock_file = Mock()
        mock_file.filename = "homework.jpg"
        mock_file.file_type = FileType.IMAGE
        mock_file.file_size = 1024
        mock_file.uploaded_at = datetime.now(timezone.utc)
        mock_file.claude_file_id = "file_homework"
        mock_file.upload_context = "Here's my math homework"

        result = format_files_section([mock_file])

        assert "Here's my math homework" in result
        assert 'context: "Here\'s my math homework"' in result

    def test_upload_context_truncated(self):
        """Test that long upload_context is truncated."""
        mock_file = Mock()
        mock_file.filename = "doc.pdf"
        mock_file.file_type = FileType.PDF
        mock_file.file_size = 5000
        mock_file.uploaded_at = datetime.now(timezone.utc)
        mock_file.claude_file_id = "file_doc"
        mock_file.upload_context = "A" * 150  # > 100 chars

        result = format_files_section([mock_file])

        # Should show first 100 chars + "..."
        assert "A" * 100 + "..." in result

    def test_upload_context_none_not_shown(self):
        """Test that None upload_context is not shown."""
        mock_file = Mock()
        mock_file.filename = "test.jpg"
        mock_file.file_type = FileType.IMAGE
        mock_file.file_size = 1024
        mock_file.uploaded_at = datetime.now(timezone.utc)
        mock_file.claude_file_id = "file_test"
        mock_file.upload_context = None

        result = format_files_section([mock_file])

        assert "context:" not in result


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


class TestFormatTtlRemaining:
    """Tests for format_ttl_remaining() function."""

    def test_expired(self):
        """Test expired TTL."""
        past = time.time() - 100
        assert format_ttl_remaining(past) == "expired"

    def test_seconds(self):
        """Test TTL in seconds."""
        future = time.time() + 45
        result = format_ttl_remaining(future)
        assert "seconds" in result

    def test_minutes(self):
        """Test TTL in minutes."""
        future = time.time() + 25 * 60 + 30  # 25+ minutes
        result = format_ttl_remaining(future)
        assert "minutes" in result
        # Should be around 25 minutes (can be 24-26 due to timing)
        assert any(f"{m} minute" in result for m in range(24, 27))

    def test_single_minute(self):
        """Test TTL of 1 minute."""
        future = time.time() + 90  # 1.5 minutes
        result = format_ttl_remaining(future)
        assert "1 minute" in result and "minutes" not in result

    def test_hours(self):
        """Test TTL in hours."""
        future = time.time() + 2 * 3600 + 60  # 2+ hours
        result = format_ttl_remaining(future)
        assert "hour" in result


class TestFormatUnifiedFilesSection:
    """Tests for format_unified_files_section() function."""

    def test_empty_both(self):
        """Test with no files of any kind."""
        result = format_unified_files_section([], [])
        assert result == ""

    def test_delivered_files_only(self):
        """Test with only delivered files."""
        mock_file = Mock()
        mock_file.filename = "image.jpg"
        mock_file.file_type = FileType.IMAGE
        mock_file.file_size = 1024
        mock_file.uploaded_at = datetime.now(timezone.utc)
        mock_file.claude_file_id = "file_abc123"
        mock_file.source = FileSource.USER

        result = format_unified_files_section([mock_file], [])

        assert "=== AVAILABLE FILES (delivered to user) ===" in result
        assert "image.jpg" in result
        assert "[user]" in result
        assert "file_abc123" in result
        assert "PENDING FILES" not in result
        assert "Total: 1 available, 0 pending" in result

    def test_pending_files_only(self):
        """Test with only pending files."""
        pending = [{
            "temp_id": "exec_abc123",
            "filename": "chart.png",
            "size_bytes": 2048,
            "preview": "Image 800x600 (RGB)",
            "expires_at": time.time() + 25 * 60,
        }]

        result = format_unified_files_section([], pending)

        assert "=== PENDING FILES (not yet delivered) ===" in result
        assert "chart.png" in result
        assert "exec_abc123" in result
        assert "Image 800x600 (RGB)" in result
        assert "AVAILABLE FILES" not in result
        assert "Total: 0 available, 1 pending" in result

    def test_both_delivered_and_pending(self):
        """Test with both delivered and pending files."""
        mock_file = Mock()
        mock_file.filename = "uploaded.pdf"
        mock_file.file_type = FileType.PDF
        mock_file.file_size = 5000
        mock_file.uploaded_at = datetime.now(timezone.utc)
        mock_file.claude_file_id = "file_xyz789"
        mock_file.source = FileSource.ASSISTANT

        pending = [{
            "temp_id": "exec_def456",
            "filename": "output.csv",
            "size_bytes": 1000,
            "preview": "CSV file, 50 rows",
            "expires_at": time.time() + 50 * 60,
        }]

        result = format_unified_files_section([mock_file], pending)

        assert "=== AVAILABLE FILES (delivered to user) ===" in result
        assert "=== PENDING FILES (not yet delivered) ===" in result
        assert "uploaded.pdf" in result
        assert "[assistant]" in result
        assert "output.csv" in result
        assert "exec_def456" in result
        assert "Total: 1 available, 1 pending" in result

    def test_file_source_tags(self):
        """Test that source tags are correctly displayed."""
        user_file = Mock()
        user_file.filename = "user_upload.jpg"
        user_file.file_type = FileType.IMAGE
        user_file.file_size = 1024
        user_file.uploaded_at = datetime.now(timezone.utc)
        user_file.claude_file_id = "file_user"
        user_file.source = FileSource.USER

        assistant_file = Mock()
        assistant_file.filename = "generated.png"
        assistant_file.file_type = FileType.GENERATED
        assistant_file.file_size = 2048
        assistant_file.uploaded_at = datetime.now(timezone.utc)
        assistant_file.claude_file_id = "file_assistant"
        assistant_file.source = FileSource.ASSISTANT

        result = format_unified_files_section([user_file, assistant_file], [])

        assert "[user]" in result
        assert "[assistant]" in result

    def test_instructions_included(self):
        """Test that usage instructions are included."""
        mock_file = Mock()
        mock_file.filename = "test.jpg"
        mock_file.file_type = FileType.IMAGE
        mock_file.file_size = 1024
        mock_file.uploaded_at = datetime.now(timezone.utc)
        mock_file.claude_file_id = "file_test"
        mock_file.source = FileSource.USER

        pending = [{
            "temp_id": "exec_test",
            "filename": "output.txt",
            "size_bytes": 100,
            "preview": "Text file",
            "expires_at": time.time() + 30 * 60,
        }]

        result = format_unified_files_section([mock_file], pending)

        # Instructions for available files
        assert "analyze_image" in result
        assert "analyze_pdf" in result

        # Instructions for pending files
        assert "deliver_file" in result
        assert "preview_file" in result

    def test_multiple_pending_files(self):
        """Test with multiple pending files."""
        pending = [
            {
                "temp_id": "exec_1",
                "filename": "chart1.png",
                "size_bytes": 1000,
                "preview": "Chart 1",
                "expires_at": time.time() + 20 * 60,
            },
            {
                "temp_id": "exec_2",
                "filename": "chart2.png",
                "size_bytes": 2000,
                "preview": "Chart 2",
                "expires_at": time.time() + 25 * 60,
            },
        ]

        result = format_unified_files_section([], pending)

        assert "chart1.png" in result
        assert "chart2.png" in result
        assert "exec_1" in result
        assert "exec_2" in result
        assert "Total: 0 available, 2 pending" in result
