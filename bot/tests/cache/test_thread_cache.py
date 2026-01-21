"""Tests for thread and messages cache module.

Tests cache-aside pattern for thread and message data caching.
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

from cache.keys import messages_key
from cache.keys import MESSAGES_TTL
from cache.keys import thread_key
from cache.keys import THREAD_TTL
from cache.thread_cache import cache_messages
from cache.thread_cache import cache_thread
from cache.thread_cache import get_cached_messages
from cache.thread_cache import get_cached_thread
from cache.thread_cache import invalidate_messages
from cache.thread_cache import invalidate_thread
import pytest


class TestThreadCache:
    """Tests for thread cache functions."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_get_cached_thread_hit(self, mock_redis):
        """Test cache hit returns cached thread data."""
        chat_id = 123
        user_id = 456
        thread_id = None
        cached_data = {
            "id": 1,
            "chat_id": chat_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "title": "Test Thread",
            "files_context": None,
            "cached_at": 1234567890.0,
        }
        mock_redis.get.return_value = (
            b'{"id": 1, "chat_id": 123, "user_id": 456, '
            b'"thread_id": null, "title": "Test Thread", '
            b'"files_context": null, "cached_at": 1234567890.0}')

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await get_cached_thread(chat_id, user_id, thread_id)

        mock_redis.get.assert_called_once_with(
            thread_key(chat_id, user_id, thread_id))
        assert result is not None
        assert result["id"] == 1
        assert result["chat_id"] == chat_id
        assert result["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_get_cached_thread_miss(self, mock_redis):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await get_cached_thread(123, 456, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_thread_redis_unavailable(self):
        """Test returns None when Redis is unavailable."""
        with patch("cache.thread_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await get_cached_thread(123, 456, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_thread_success(self, mock_redis):
        """Test successful thread caching."""
        chat_id = 123
        user_id = 456
        thread_id = None
        internal_id = 1

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await cache_thread(
                chat_id=chat_id,
                user_id=user_id,
                thread_id=thread_id,
                internal_id=internal_id,
                title="Test",
            )

        assert result is True
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == thread_key(chat_id, user_id, thread_id)
        assert call_args[0][1] == THREAD_TTL

    @pytest.mark.asyncio
    async def test_cache_thread_redis_unavailable(self):
        """Test returns False when Redis is unavailable."""
        with patch("cache.thread_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await cache_thread(
                chat_id=123,
                user_id=456,
                thread_id=None,
                internal_id=1,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_thread_success(self, mock_redis):
        """Test successful thread cache invalidation."""
        mock_redis.delete.return_value = 1

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await invalidate_thread(123, 456, None)

        mock_redis.delete.assert_called_once_with(thread_key(123, 456, None))
        assert result is True

    @pytest.mark.asyncio
    async def test_invalidate_thread_not_found(self, mock_redis):
        """Test invalidation when key doesn't exist."""
        mock_redis.delete.return_value = 0

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await invalidate_thread(123, 456, None)

        assert result is False


class TestMessagesCache:
    """Tests for messages cache functions."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.fixture
    def sample_messages(self):
        """Sample message data for caching."""
        return [
            {
                "chat_id": 123,
                "message_id": 1,
                "thread_id": 1,
                "from_user_id": 456,
                "date": 1234567890,
                "role": "user",
                "text_content": "Hello",
                "caption": None,
                "attachments": [],
            },
            {
                "chat_id": 123,
                "message_id": 2,
                "thread_id": 1,
                "from_user_id": None,
                "date": 1234567891,
                "role": "assistant",
                "text_content": "Hi there!",
                "caption": None,
                "attachments": [],
            },
        ]

    @pytest.mark.asyncio
    async def test_get_cached_messages_hit(self, mock_redis, sample_messages):
        """Test cache hit returns cached messages."""
        thread_id = 1
        import json
        cached_data = {
            "thread_id": thread_id,
            "messages": sample_messages,
            "cached_at": 1234567890.0,
        }
        mock_redis.get.return_value = json.dumps(cached_data).encode("utf-8")

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await get_cached_messages(thread_id)

        mock_redis.get.assert_called_once_with(messages_key(thread_id))
        assert result is not None
        assert len(result) == 2
        assert result[0]["text_content"] == "Hello"
        assert result[1]["text_content"] == "Hi there!"

    @pytest.mark.asyncio
    async def test_get_cached_messages_miss(self, mock_redis):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await get_cached_messages(1)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_messages_redis_unavailable(self):
        """Test returns None when Redis is unavailable."""
        with patch("cache.thread_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await get_cached_messages(1)

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_messages_success(self, mock_redis, sample_messages):
        """Test successful messages caching."""
        thread_id = 1

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await cache_messages(thread_id, sample_messages)

        assert result is True
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == messages_key(thread_id)
        assert call_args[0][1] == MESSAGES_TTL

    @pytest.mark.asyncio
    async def test_cache_messages_redis_unavailable(self, sample_messages):
        """Test returns False when Redis is unavailable."""
        with patch("cache.thread_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await cache_messages(1, sample_messages)

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_messages_success(self, mock_redis):
        """Test successful messages cache invalidation."""
        mock_redis.delete.return_value = 1

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await invalidate_messages(1)

        mock_redis.delete.assert_called_once_with(messages_key(1))
        assert result is True

    @pytest.mark.asyncio
    async def test_invalidate_messages_not_found(self, mock_redis):
        """Test invalidation when key doesn't exist."""
        mock_redis.delete.return_value = 0

        with patch("cache.thread_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await invalidate_messages(1)

        assert result is False


class TestCacheKeys:
    """Tests for cache key generation."""

    def test_thread_key_without_thread_id(self):
        """Test key for main chat thread (no thread_id)."""
        key = thread_key(123, 456, None)
        assert key == "cache:thread:123:456:0"

    def test_thread_key_with_thread_id(self):
        """Test key for forum topic thread."""
        key = thread_key(123, 456, 789)
        assert key == "cache:thread:123:456:789"

    def test_messages_key_format(self):
        """Test key format for messages cache."""
        key = messages_key(1)
        assert key == "cache:messages:1"
