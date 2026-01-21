"""Tests for file cache module.

Tests binary file caching functionality.
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

from cache.file_cache import cache_file
from cache.file_cache import get_cached_file
from cache.file_cache import invalidate_file
from cache.keys import file_bytes_key
from cache.keys import FILE_BYTES_MAX_SIZE
from cache.keys import FILE_BYTES_TTL
import pytest


class TestFileCache:
    """Tests for file cache functions."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def sample_file_id(self):
        """Sample Telegram file ID."""
        return "AgACAgIAAxkBAAIBVWZGh8qUAe-8CmvOhJ5kOmtNAAGBCQAC_"

    @pytest.fixture
    def sample_content(self):
        """Sample file content."""
        return b"test file content data for caching"

    @pytest.mark.asyncio
    async def test_get_cached_file_hit(self, mock_redis, sample_file_id,
                                       sample_content):
        """Test cache hit returns file content."""
        mock_redis.get.return_value = sample_content

        with patch("cache.file_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await get_cached_file(sample_file_id)

        mock_redis.get.assert_called_once_with(file_bytes_key(sample_file_id))
        assert result == sample_content
        assert isinstance(result, bytes)

    @pytest.mark.asyncio
    async def test_get_cached_file_miss(self, mock_redis, sample_file_id):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None

        with patch("cache.file_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await get_cached_file(sample_file_id)

        mock_redis.get.assert_called_once_with(file_bytes_key(sample_file_id))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_file_redis_unavailable(self, sample_file_id):
        """Test returns None when Redis is unavailable."""
        with patch("cache.file_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await get_cached_file(sample_file_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_file_success(self, mock_redis, sample_file_id,
                                      sample_content):
        """Test successful file caching."""
        with patch("cache.file_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await cache_file(sample_file_id,
                                      sample_content,
                                      filename="test.ogg")

        assert result is True
        mock_redis.setex.assert_called_once_with(
            file_bytes_key(sample_file_id),
            FILE_BYTES_TTL,
            sample_content,
        )

    @pytest.mark.asyncio
    async def test_cache_file_too_large(self, sample_file_id):
        """Test skips caching for files exceeding size limit."""
        large_content = b"x" * (FILE_BYTES_MAX_SIZE + 1)

        with patch("cache.file_cache.get_redis") as mock_get_redis:
            result = await cache_file(sample_file_id,
                                      large_content,
                                      filename="large.bin")

        # Should return False without calling Redis
        assert result is False
        mock_get_redis.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_file_at_size_limit(self, mock_redis, sample_file_id):
        """Test caches files at exactly the size limit."""
        content_at_limit = b"x" * FILE_BYTES_MAX_SIZE

        with patch("cache.file_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await cache_file(sample_file_id,
                                      content_at_limit,
                                      filename="exact.bin")

        assert result is True
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_file_redis_unavailable(self, sample_file_id,
                                                sample_content):
        """Test returns False when Redis is unavailable."""
        with patch("cache.file_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await cache_file(sample_file_id, sample_content)

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_file_success(self, mock_redis, sample_file_id):
        """Test successful file cache invalidation."""
        mock_redis.delete.return_value = 1

        with patch("cache.file_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await invalidate_file(sample_file_id)

        mock_redis.delete.assert_called_once_with(
            file_bytes_key(sample_file_id))
        assert result is True

    @pytest.mark.asyncio
    async def test_invalidate_file_not_found(self, mock_redis, sample_file_id):
        """Test invalidation when key doesn't exist."""
        mock_redis.delete.return_value = 0

        with patch("cache.file_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await invalidate_file(sample_file_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_file_redis_unavailable(self, sample_file_id):
        """Test returns False when Redis is unavailable."""
        with patch("cache.file_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await invalidate_file(sample_file_id)

        assert result is False


class TestFileCacheKeys:
    """Tests for file cache key generation."""

    def test_file_bytes_key_format(self):
        """Test key format for file bytes cache."""
        file_id = "AgACAgIAAxkBAAIBVWZGh8qU"
        key = file_bytes_key(file_id)

        assert key == f"file:bytes:{file_id}"
        assert key.startswith("file:bytes:")
