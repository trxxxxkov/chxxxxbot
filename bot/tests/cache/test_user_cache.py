"""Tests for user cache module.

Tests the cache-aside pattern for user data caching.
"""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import patch

from cache.keys import user_key
from cache.keys import USER_TTL
from cache.user_cache import cache_user
from cache.user_cache import get_balance_from_cached
from cache.user_cache import get_cached_user
from cache.user_cache import invalidate_user
import pytest


class TestUserCache:
    """Tests for user cache functions."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_get_cached_user_hit(self, mock_redis):
        """Test cache hit returns cached user data."""
        user_id = 123456
        cached_data = {
            "balance": "10.5000",
            "model_id": "claude:sonnet",
            "first_name": "Test",
            "username": "testuser",
            "cached_at": 1234567890.0,
        }
        mock_redis.get.return_value = (
            b'{"balance": "10.5000", "model_id": "claude:sonnet", '
            b'"first_name": "Test", "username": "testuser", '
            b'"cached_at": 1234567890.0}')

        with patch("cache.user_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await get_cached_user(user_id)

        mock_redis.get.assert_called_once_with(user_key(user_id))
        assert result is not None
        assert result["balance"] == "10.5000"
        assert result["model_id"] == "claude:sonnet"
        assert result["first_name"] == "Test"
        assert result["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_get_cached_user_miss(self, mock_redis):
        """Test cache miss returns None."""
        user_id = 123456
        mock_redis.get.return_value = None

        with patch("cache.user_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await get_cached_user(user_id)

        mock_redis.get.assert_called_once_with(user_key(user_id))
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_user_redis_unavailable(self):
        """Test returns None when Redis is unavailable."""
        user_id = 123456

        with patch("cache.user_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await get_cached_user(user_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_cache_user_success(self, mock_redis):
        """Test successful user caching."""
        user_id = 123456
        balance = Decimal("10.5000")
        model_id = "claude:sonnet"
        first_name = "Test"
        username = "testuser"

        with patch("cache.user_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await cache_user(
                user_id=user_id,
                balance=balance,
                model_id=model_id,
                first_name=first_name,
                username=username,
            )

        assert result is True
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == user_key(user_id)
        assert call_args[0][1] == USER_TTL
        # Verify JSON contains expected fields
        import json
        cached_json = json.loads(call_args[0][2])
        assert cached_json["balance"] == "10.5000"
        assert cached_json["model_id"] == "claude:sonnet"

    @pytest.mark.asyncio
    async def test_cache_user_redis_unavailable(self):
        """Test returns False when Redis is unavailable."""
        user_id = 123456

        with patch("cache.user_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await cache_user(
                user_id=user_id,
                balance=Decimal("10.0"),
                model_id="claude:sonnet",
                first_name="Test",
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_user_success(self, mock_redis):
        """Test successful user cache invalidation."""
        user_id = 123456
        mock_redis.delete.return_value = 1

        with patch("cache.user_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await invalidate_user(user_id)

        mock_redis.delete.assert_called_once_with(user_key(user_id))
        assert result is True

    @pytest.mark.asyncio
    async def test_invalidate_user_not_found(self, mock_redis):
        """Test invalidation when key doesn't exist."""
        user_id = 123456
        mock_redis.delete.return_value = 0

        with patch("cache.user_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await invalidate_user(user_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_invalidate_user_redis_unavailable(self):
        """Test returns False when Redis is unavailable."""
        user_id = 123456

        with patch("cache.user_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await invalidate_user(user_id)

        assert result is False


class TestGetBalanceFromCached:
    """Tests for get_balance_from_cached helper."""

    def test_extracts_balance_as_decimal(self):
        """Test balance extraction from cached data."""
        cached = {
            "balance": "10.5000",
            "model_id": "claude:sonnet",
            "first_name": "Test",
            "username": None,
            "cached_at": 1234567890.0,
        }

        result = get_balance_from_cached(cached)

        assert result == Decimal("10.5000")
        assert isinstance(result, Decimal)

    def test_handles_zero_balance(self):
        """Test zero balance extraction."""
        cached = {"balance": "0.0000"}

        result = get_balance_from_cached(cached)

        assert result == Decimal("0.0000")

    def test_handles_negative_balance(self):
        """Test negative balance extraction."""
        cached = {"balance": "-5.0000"}

        result = get_balance_from_cached(cached)

        assert result == Decimal("-5.0000")
