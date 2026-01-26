"""Tests for execution output cache module.

Tests temporary file storage for execute_python tool output.
"""

import json
from unittest.mock import AsyncMock
from unittest.mock import patch

from cache.exec_cache import _generate_preview
from cache.exec_cache import delete_exec_file
from cache.exec_cache import generate_temp_id
from cache.exec_cache import get_exec_file
from cache.exec_cache import get_exec_meta
from cache.exec_cache import get_pending_files_for_thread
from cache.exec_cache import store_exec_file
from cache.keys import exec_file_key
from cache.keys import EXEC_FILE_MAX_SIZE
from cache.keys import EXEC_FILE_TTL
from cache.keys import exec_meta_key
import pytest


class TestGenerateTempId:
    """Tests for temp ID generation."""

    def test_generate_temp_id_format(self):
        """Test temp ID uses only exec_ prefix and UUID.

        Format: exec_{8-char-uuid}
        Filename is stored in metadata, not in temp_id.
        This prevents Claude from mistyping complex filenames.
        """
        temp_id = generate_temp_id("chart.png")

        assert temp_id.startswith("exec_")
        # exec_ (5 chars) + 8-char uuid = 13 chars total
        assert len(temp_id) == 13
        # Verify UUID part is hex
        uuid_part = temp_id[5:]  # After "exec_"
        assert all(c in '0123456789abcdef' for c in uuid_part)

    def test_generate_temp_id_unique(self):
        """Test temp IDs are unique."""
        id1 = generate_temp_id("test.pdf")
        id2 = generate_temp_id("test.pdf")

        assert id1 != id2

    def test_generate_temp_id_ignores_filename(self):
        """Test that filename is ignored (stored in metadata instead)."""
        id1 = generate_temp_id("chart.png")
        id2 = generate_temp_id("report.pdf")

        # Both should have same format (exec_ + 8 hex chars)
        assert len(id1) == len(id2) == 13
        assert id1.startswith("exec_")
        assert id2.startswith("exec_")


class TestGeneratePreview:
    """Tests for file preview generation."""

    def test_preview_image_with_dimensions(self):
        """Test image preview includes dimensions."""
        # Minimal PNG header (1x1 pixel)
        png_bytes = (
            b'\x89PNG\r\n\x1a\n'
            b'\x00\x00\x00\rIHDR'
            b'\x00\x00\x00\x01'  # width=1
            b'\x00\x00\x00\x01'  # height=1
            b'\x08\x02'  # bit depth 8, color type 2 (RGB)
            b'\x00\x00\x00')
        # Add more data to make it realistic
        png_bytes += b'\x00' * 100

        preview = _generate_preview("test.png", png_bytes, "image/png")

        assert "Image" in preview or "image" in preview.lower()

    def test_preview_pdf(self):
        """Test PDF preview."""
        pdf_bytes = b"%PDF-1.4\n" + b"\x00" * 1000

        preview = _generate_preview("doc.pdf", pdf_bytes, "application/pdf")

        assert "PDF" in preview
        assert "KB" in preview or "bytes" in preview

    def test_preview_text_file(self):
        """Test text file preview includes first line."""
        text_content = b"First line of text\nSecond line\nThird line"

        preview = _generate_preview("data.txt", text_content, "text/plain")

        assert "Text" in preview or "text" in preview.lower()
        assert "First line" in preview or "lines" in preview

    def test_preview_csv_file(self):
        """Test CSV preview includes header info."""
        csv_content = b"name,age,city\nAlice,30,NYC\nBob,25,LA"

        preview = _generate_preview("data.csv", csv_content, "text/csv")

        # CSV files show header in preview (handled as text with CSV detection)
        assert "name,age,city" in preview or "CSV" in preview

    def test_preview_binary_file(self):
        """Test binary file shows mime type and size."""
        binary_content = b"\x00\x01\x02\x03" * 1000

        preview = _generate_preview("data.bin", binary_content,
                                    "application/octet-stream")

        assert "KB" in preview or "bytes" in preview

    def test_preview_size_formatting_bytes(self):
        """Test size shown in bytes for small files."""
        content = b"small"

        preview = _generate_preview("tiny.txt", content, "text/plain")

        # Should mention bytes for very small files
        assert "bytes" in preview or "chars" in preview

    def test_preview_size_formatting_kb(self):
        """Test size shown in KB for medium files."""
        content = b"x" * 5000  # 5KB

        preview = _generate_preview("medium.bin", content,
                                    "application/octet-stream")

        assert "KB" in preview

    def test_preview_size_formatting_mb(self):
        """Test size shown in MB for large files."""
        content = b"x" * (2 * 1024 * 1024)  # 2MB

        preview = _generate_preview("large.bin", content,
                                    "application/octet-stream")

        assert "MB" in preview


class TestStoreExecFile:
    """Tests for storing execution output files."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def sample_content(self):
        """Sample file content."""
        return b"test output content"

    @pytest.mark.asyncio
    async def test_store_exec_file_success(self, mock_redis, sample_content):
        """Test successful file storage."""
        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="output.txt",
                content=sample_content,
                mime_type="text/plain",
            )

        assert result is not None
        assert "temp_id" in result
        assert result["filename"] == "output.txt"
        assert result["mime_type"] == "text/plain"
        assert result["size_bytes"] == len(sample_content)
        assert "preview" in result
        assert "created_at" in result
        assert "expires_at" in result

        # Verify Redis calls
        assert mock_redis.setex.call_count == 2  # file + meta

    @pytest.mark.asyncio
    async def test_store_exec_file_with_execution_id(self, mock_redis,
                                                     sample_content):
        """Test storage includes execution ID in metadata."""
        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="chart.png",
                content=sample_content,
                mime_type="image/png",
                execution_id="abc123",
            )

        assert result is not None
        assert result["execution_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_store_exec_file_bytearray(self, mock_redis):
        """Test storage works with bytearray content (E2B sandbox returns this).

        Regression test for: Redis DataError with bytearray type.
        E2B sandbox returns bytearray, but Redis only accepts bytes.
        """
        bytearray_content = bytearray(b"content from E2B sandbox")

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="sandbox_output.png",
                content=bytearray_content,
                mime_type="image/png",
            )

        assert result is not None
        assert result["filename"] == "sandbox_output.png"
        assert result["size_bytes"] == len(bytearray_content)

        # Verify Redis was called with bytes, not bytearray
        file_call = mock_redis.setex.call_args_list[0]
        stored_content = file_call[0][2]
        assert isinstance(stored_content,
                          bytes), "Redis should receive bytes, not bytearray"

    @pytest.mark.asyncio
    async def test_store_exec_file_too_large(self):
        """Test rejects files exceeding size limit."""
        large_content = b"x" * (EXEC_FILE_MAX_SIZE + 1)

        with patch("cache.exec_cache.get_redis") as mock_get_redis:
            result = await store_exec_file(
                filename="huge.bin",
                content=large_content,
                mime_type="application/octet-stream",
            )

        assert result is None
        mock_get_redis.assert_not_called()

    @pytest.mark.asyncio
    async def test_store_exec_file_at_size_limit(self, mock_redis):
        """Test accepts files at exactly size limit."""
        content_at_limit = b"x" * EXEC_FILE_MAX_SIZE

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="exact.bin",
                content=content_at_limit,
                mime_type="application/octet-stream",
            )

        assert result is not None
        assert result["size_bytes"] == EXEC_FILE_MAX_SIZE

    @pytest.mark.asyncio
    async def test_store_exec_file_redis_unavailable(self, sample_content):
        """Test returns None when Redis is unavailable."""
        with patch("cache.exec_cache.get_redis", return_value=None):
            result = await store_exec_file(
                filename="test.txt",
                content=sample_content,
                mime_type="text/plain",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_store_exec_file_ttl(self, mock_redis, sample_content):
        """Test file stored with correct TTL."""
        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            await store_exec_file(
                filename="test.txt",
                content=sample_content,
                mime_type="text/plain",
            )

        # Check TTL in setex calls
        for call in mock_redis.setex.call_args_list:
            assert call[0][1] == EXEC_FILE_TTL


class TestGetExecFile:
    """Tests for retrieving execution output files."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def sample_temp_id(self):
        """Sample temp ID."""
        return "exec_abc12345_chart.png"

    @pytest.fixture
    def sample_content(self):
        """Sample file content."""
        return b"cached file content"

    @pytest.mark.asyncio
    async def test_get_exec_file_hit(self, mock_redis, sample_temp_id,
                                     sample_content):
        """Test cache hit returns file content."""
        mock_redis.get.return_value = sample_content

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_exec_file(sample_temp_id)

        mock_redis.get.assert_called_once_with(exec_file_key(sample_temp_id))
        assert result == sample_content

    @pytest.mark.asyncio
    async def test_get_exec_file_miss(self, mock_redis, sample_temp_id):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_exec_file(sample_temp_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_exec_file_redis_unavailable(self, sample_temp_id):
        """Test returns None when Redis unavailable."""
        with patch("cache.exec_cache.get_redis", return_value=None):
            result = await get_exec_file(sample_temp_id)

        assert result is None


class TestGetExecMeta:
    """Tests for retrieving execution file metadata."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def sample_temp_id(self):
        """Sample temp ID."""
        return "exec_abc12345_report.pdf"

    @pytest.fixture
    def sample_metadata(self):
        """Sample metadata dict."""
        return {
            "temp_id": "exec_abc12345_report.pdf",
            "filename": "report.pdf",
            "size_bytes": 12345,
            "mime_type": "application/pdf",
            "preview": "PDF document, ~3 pages, 12.1 KB",
            "execution_id": "xyz789",
            "created_at": 1234567890.0,
            "expires_at": 1234569690.0,
        }

    @pytest.mark.asyncio
    async def test_get_exec_meta_hit(self, mock_redis, sample_temp_id,
                                     sample_metadata):
        """Test cache hit returns metadata dict."""
        mock_redis.get.return_value = json.dumps(sample_metadata).encode()

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_exec_meta(sample_temp_id)

        mock_redis.get.assert_called_once_with(exec_meta_key(sample_temp_id))
        assert result == sample_metadata

    @pytest.mark.asyncio
    async def test_get_exec_meta_miss(self, mock_redis, sample_temp_id):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_exec_meta(sample_temp_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_exec_meta_redis_unavailable(self, sample_temp_id):
        """Test returns None when Redis unavailable."""
        with patch("cache.exec_cache.get_redis", return_value=None):
            result = await get_exec_meta(sample_temp_id)

        assert result is None


class TestDeleteExecFile:
    """Tests for deleting execution output files."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def sample_temp_id(self):
        """Sample temp ID."""
        return "exec_abc12345_data.csv"

    @pytest.mark.asyncio
    async def test_delete_exec_file_success(self, mock_redis, sample_temp_id):
        """Test successful deletion."""
        mock_redis.delete.return_value = 2  # Both keys deleted

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await delete_exec_file(sample_temp_id)

        mock_redis.delete.assert_called_once_with(
            exec_file_key(sample_temp_id),
            exec_meta_key(sample_temp_id),
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_exec_file_not_found(self, mock_redis, sample_temp_id):
        """Test deletion when file doesn't exist."""
        mock_redis.delete.return_value = 0

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await delete_exec_file(sample_temp_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_exec_file_redis_unavailable(self, sample_temp_id):
        """Test returns False when Redis unavailable."""
        with patch("cache.exec_cache.get_redis", return_value=None):
            result = await delete_exec_file(sample_temp_id)

        assert result is False


class TestExecCacheKeys:
    """Tests for exec cache key generation."""

    def test_exec_file_key_format(self):
        """Test file key format."""
        temp_id = "exec_abc12345_chart.png"
        key = exec_file_key(temp_id)

        assert key == f"exec:file:{temp_id}"

    def test_exec_meta_key_format(self):
        """Test metadata key format."""
        temp_id = "exec_abc12345_report.pdf"
        key = exec_meta_key(temp_id)

        assert key == f"exec:meta:{temp_id}"


class TestStoreExecFileWithThreadId:
    """Tests for storing files with thread_id tracking."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def sample_content(self):
        """Sample file content."""
        return b"test output content"

    @pytest.mark.asyncio
    async def test_store_exec_file_with_thread_id(self, mock_redis,
                                                  sample_content):
        """Test storage includes thread_id in metadata."""
        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="chart.png",
                content=sample_content,
                mime_type="image/png",
                thread_id=12345,
            )

        assert result is not None
        assert result["thread_id"] == 12345

    @pytest.mark.asyncio
    async def test_store_exec_file_thread_id_none(self, mock_redis,
                                                  sample_content):
        """Test storage works without thread_id (backward compat)."""
        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="chart.png",
                content=sample_content,
                mime_type="image/png",
            )

        assert result is not None
        assert result["thread_id"] is None

    @pytest.mark.asyncio
    async def test_store_exec_file_with_both_ids(self, mock_redis,
                                                 sample_content):
        """Test storage with both execution_id and thread_id."""
        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="output.csv",
                content=sample_content,
                mime_type="text/csv",
                execution_id="exec123",
                thread_id=42,
            )

        assert result is not None
        assert result["execution_id"] == "exec123"
        assert result["thread_id"] == 42


class TestGetPendingFilesForThread:
    """Tests for getting pending files by thread_id."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_get_pending_files_success(self, mock_redis):
        """Test retrieving pending files for a thread."""
        # Simulate two files for thread 42
        metadata1 = {
            "temp_id": "exec_abc12345",
            "filename": "chart.png",
            "thread_id": 42,
            "created_at": 1000.0,
            "expires_at": 2000.0,
        }
        metadata2 = {
            "temp_id": "exec_def67890",
            "filename": "data.csv",
            "thread_id": 42,
            "created_at": 1100.0,
            "expires_at": 2100.0,
        }
        # File for different thread
        metadata3 = {
            "temp_id": "exec_ghi11111",
            "filename": "other.txt",
            "thread_id": 99,
            "created_at": 1200.0,
            "expires_at": 2200.0,
        }

        # Mock SCAN returning all keys, then cursor=0 to stop
        mock_redis.scan.return_value = (
            0,  # cursor=0 means complete
            [
                b"exec:meta:exec_abc12345", b"exec:meta:exec_def67890",
                b"exec:meta:exec_ghi11111"
            ],
        )
        mock_redis.get.side_effect = [
            json.dumps(metadata1).encode(),
            json.dumps(metadata2).encode(),
            json.dumps(metadata3).encode(),
        ]

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_pending_files_for_thread(42)

        # Should only include files for thread 42
        assert len(result) == 2
        assert result[0]["temp_id"] == "exec_abc12345"  # Older first
        assert result[1]["temp_id"] == "exec_def67890"

    @pytest.mark.asyncio
    async def test_get_pending_files_empty(self, mock_redis):
        """Test returns empty list when no files for thread."""
        mock_redis.scan.return_value = (0, [])

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_pending_files_for_thread(999)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_pending_files_redis_unavailable(self):
        """Test returns empty list when Redis unavailable."""
        with patch("cache.exec_cache.get_redis", return_value=None):
            result = await get_pending_files_for_thread(42)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_pending_files_sorted_by_time(self, mock_redis):
        """Test files are sorted by creation time (oldest first)."""
        # Files in reverse chronological order
        metadata1 = {
            "temp_id": "exec_newer",
            "thread_id": 42,
            "created_at": 3000.0,
            "expires_at": 4000.0,
        }
        metadata2 = {
            "temp_id": "exec_older",
            "thread_id": 42,
            "created_at": 1000.0,
            "expires_at": 2000.0,
        }

        mock_redis.scan.return_value = (
            0,
            [b"exec:meta:exec_newer", b"exec:meta:exec_older"],
        )
        mock_redis.get.side_effect = [
            json.dumps(metadata1).encode(),
            json.dumps(metadata2).encode(),
        ]

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_pending_files_for_thread(42)

        # Older should be first
        assert len(result) == 2
        assert result[0]["temp_id"] == "exec_older"
        assert result[1]["temp_id"] == "exec_newer"

    @pytest.mark.asyncio
    async def test_get_pending_files_handles_parse_error(self, mock_redis):
        """Test gracefully handles corrupted metadata."""
        valid_metadata = {
            "temp_id": "exec_valid",
            "thread_id": 42,
            "created_at": 1000.0,
            "expires_at": 2000.0,
        }

        mock_redis.scan.return_value = (
            0,
            [b"exec:meta:exec_valid", b"exec:meta:exec_corrupt"],
        )
        mock_redis.get.side_effect = [
            json.dumps(valid_metadata).encode(),
            b"not valid json",  # Corrupted entry
        ]

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_pending_files_for_thread(42)

        # Should only include valid entry
        assert len(result) == 1
        assert result[0]["temp_id"] == "exec_valid"
