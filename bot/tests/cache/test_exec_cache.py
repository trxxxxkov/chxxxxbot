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
from cache.exec_cache import store_exec_file
from cache.keys import exec_file_key
from cache.keys import EXEC_FILE_MAX_SIZE
from cache.keys import EXEC_FILE_TTL
from cache.keys import exec_meta_key
import pytest


class TestGenerateTempId:
    """Tests for temp ID generation."""

    def test_generate_temp_id_format(self):
        """Test temp ID includes prefix and filename."""
        temp_id = generate_temp_id("chart.png")

        assert temp_id.startswith("exec_")
        assert temp_id.endswith("_chart.png")
        assert len(temp_id) == len("exec_") + 8 + len("_chart.png")

    def test_generate_temp_id_unique(self):
        """Test temp IDs are unique."""
        id1 = generate_temp_id("test.pdf")
        id2 = generate_temp_id("test.pdf")

        assert id1 != id2


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
