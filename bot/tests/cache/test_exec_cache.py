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
                context="Test output file",
            )

        assert result is not None
        assert "temp_id" in result
        assert result["filename"] == "output.txt"
        assert result["mime_type"] == "text/plain"
        assert result["size_bytes"] == len(sample_content)
        assert "preview" in result
        assert "context" in result
        assert result["context"] == "Test output file"
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
                context="Python output: chart.png",
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
                context="Python output: sandbox_output.png",
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
                context="Test large file",
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
                context="Test file at size limit",
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
                context="Test file",
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
                context="Test file",
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
        """Test successful deletion with thread index cleanup."""
        # File has thread_id, so it should be removed from index
        metadata = {
            "temp_id": sample_temp_id,
            "thread_id": 42,
        }
        mock_redis.get.return_value = json.dumps(metadata).encode()
        mock_redis.delete.return_value = 2  # Both keys deleted
        mock_redis.srem.return_value = 1  # Removed from index

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await delete_exec_file(sample_temp_id)

        mock_redis.delete.assert_called_once_with(
            exec_file_key(sample_temp_id),
            exec_meta_key(sample_temp_id),
        )
        # Should also remove from thread index
        mock_redis.srem.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_exec_file_not_found(self, mock_redis, sample_temp_id):
        """Test deletion when file doesn't exist."""
        mock_redis.get.return_value = None  # No metadata
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
                context="Python output: chart.png",
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
                context="Python output: chart.png",
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
                context="Python output: output.csv",
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
        """Test retrieving pending files for a thread using thread index."""
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

        # Mock SMEMBERS returning temp_ids from thread index
        mock_redis.smembers.return_value = {
            b"exec_abc12345",
            b"exec_def67890",
        }

        # Mock MGET for batch metadata retrieval (optimized path)
        # mget returns list in same order as keys requested
        mock_redis.mget.return_value = [
            json.dumps(metadata1).encode(),
            json.dumps(metadata2).encode(),
        ]

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_pending_files_for_thread(42)

        # Should include both files, sorted by created_at
        assert len(result) == 2
        assert result[0]["temp_id"] == "exec_abc12345"  # Older first
        assert result[1]["temp_id"] == "exec_def67890"
        # Verify mget was called (batch operation)
        mock_redis.mget.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_pending_files_empty(self, mock_redis):
        """Test returns empty list when no files for thread."""
        mock_redis.smembers.return_value = set()  # Empty index

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

        # Mock SMEMBERS returning temp_ids
        mock_redis.smembers.return_value = {b"exec_newer", b"exec_older"}

        # Mock MGET - returns in order of keys, but result sorted by created_at
        # Order depends on set iteration, so we need to handle both orders
        def mget_side_effect(keys):
            result = []
            for key in keys:
                if "exec_newer" in key:
                    result.append(json.dumps(metadata1).encode())
                elif "exec_older" in key:
                    result.append(json.dumps(metadata2).encode())
                else:
                    result.append(None)
            return result

        mock_redis.mget.side_effect = mget_side_effect

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_pending_files_for_thread(42)

        # Older should be first (sorted by created_at)
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

        # Mock SMEMBERS returning temp_ids (including one with corrupt data)
        mock_redis.smembers.return_value = {b"exec_valid", b"exec_corrupt"}
        mock_redis.srem.return_value = 1  # For stale cleanup

        # Mock MGET - returns valid JSON for one key, corrupt for another
        def mget_side_effect(keys):
            result = []
            for key in keys:
                if "exec_valid" in key:
                    result.append(json.dumps(valid_metadata).encode())
                elif "exec_corrupt" in key:
                    result.append(b"not valid json")  # Corrupted entry
                else:
                    result.append(None)
            return result

        mock_redis.mget.side_effect = mget_side_effect

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_pending_files_for_thread(42)

        # Should only include valid entry
        assert len(result) == 1
        assert result[0]["temp_id"] == "exec_valid"


class TestAsyncOptimizations:
    """Tests for async optimization patterns (parallel Redis operations)."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def sample_content(self):
        """Sample file content."""
        return b"test output content"

    @pytest.mark.asyncio
    async def test_store_with_thread_id_uses_parallel_ops(
            self, mock_redis, sample_content):
        """Test that store with thread_id uses parallel Redis operations.

        When thread_id is provided, 4 Redis operations should run in parallel:
        - setex file content
        - setex metadata
        - sadd to thread index
        - expire on thread index
        """
        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="chart.png",
                content=sample_content,
                mime_type="image/png",
                context="Python output",
                thread_id=42,
            )

        assert result is not None
        # With thread_id: 2 setex + 1 sadd + 1 expire = 4 operations
        assert mock_redis.setex.call_count == 2
        assert mock_redis.sadd.call_count == 1
        assert mock_redis.expire.call_count == 1

    @pytest.mark.asyncio
    async def test_store_without_thread_id_uses_two_parallel_ops(
            self, mock_redis, sample_content):
        """Test that store without thread_id uses 2 parallel Redis operations.

        Without thread_id, only 2 Redis operations run in parallel:
        - setex file content
        - setex metadata
        """
        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await store_exec_file(
                filename="chart.png",
                content=sample_content,
                mime_type="image/png",
                context="Python output",
            )

        assert result is not None
        # Without thread_id: only 2 setex operations
        assert mock_redis.setex.call_count == 2
        assert mock_redis.sadd.call_count == 0
        assert mock_redis.expire.call_count == 0

    @pytest.mark.asyncio
    async def test_get_pending_uses_mget_batch(self, mock_redis):
        """Test that get_pending_files uses mget for batch retrieval.

        Using mget instead of multiple get calls reduces round-trips.
        """
        metadata1 = {
            "temp_id": "exec_a",
            "created_at": 1000.0,
        }
        metadata2 = {
            "temp_id": "exec_b",
            "created_at": 2000.0,
        }

        mock_redis.smembers.return_value = {b"exec_a", b"exec_b"}
        mock_redis.mget.return_value = [
            json.dumps(metadata1).encode(),
            json.dumps(metadata2).encode(),
        ]

        with patch("cache.exec_cache.get_redis", return_value=mock_redis):
            result = await get_pending_files_for_thread(42)

        # Should use single mget call instead of multiple get calls
        mock_redis.mget.assert_called_once()
        # Should NOT use individual get calls
        mock_redis.get.assert_not_called()
        assert len(result) == 2
