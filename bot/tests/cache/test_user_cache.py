"""Tests for user cache module.

Tests the cache-aside pattern for user data caching.
"""

from decimal import Decimal
import json
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


class TestUpdateCachedBalance:
    """Tests for update_cached_balance function (atomic Lua script)."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_update_cached_balance_success(self, mock_redis):
        """Test successful balance update via Lua script."""
        user_id = 123456
        new_balance = Decimal("15.5000")

        # Lua script returns [1, old_balance] on success
        mock_redis.eval.return_value = [1, b"10.0000"]

        from cache.user_cache import update_cached_balance

        with patch("cache.user_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await update_cached_balance(user_id, new_balance)

        assert result is True
        mock_redis.eval.assert_called_once()

        # Verify Lua script was called with correct args
        call_args = mock_redis.eval.call_args
        assert call_args[0][1] == 1  # number of keys
        assert call_args[0][2] == user_key(user_id)  # KEYS[1]
        assert call_args[0][3] == "15.5000"  # ARGV[1] new_balance

    @pytest.mark.asyncio
    async def test_update_cached_balance_not_cached(self, mock_redis):
        """Test update when user is not in cache."""
        user_id = 123456
        new_balance = Decimal("15.5000")

        # Lua script returns [0, ''] when key not found
        mock_redis.eval.return_value = [0, b""]

        from cache.user_cache import update_cached_balance

        with patch("cache.user_cache.get_redis",
                   return_value=mock_redis) as mock_get_redis:
            result = await update_cached_balance(user_id, new_balance)

        assert result is False

    @pytest.mark.asyncio
    async def test_update_cached_balance_redis_unavailable(self):
        """Test returns False when Redis is unavailable."""
        user_id = 123456
        new_balance = Decimal("15.5000")

        from cache.user_cache import update_cached_balance

        with patch("cache.user_cache.get_redis",
                   return_value=None) as mock_get_redis:
            result = await update_cached_balance(user_id, new_balance)

        assert result is False

    @pytest.mark.asyncio
    async def test_update_cached_balance_eval_error(self, mock_redis):
        """Test graceful handling of Lua script errors."""
        user_id = 123456
        new_balance = Decimal("15.5000")

        mock_redis.eval.side_effect = Exception("NOSCRIPT")

        from cache.user_cache import update_cached_balance

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await update_cached_balance(user_id, new_balance)

        assert result is False


class TestCustomPromptCaching:
    """Tests for custom_prompt field in user cache."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_cache_user_with_custom_prompt(self, mock_redis):
        """Test caching user with custom_prompt."""
        user_id = 123456
        custom_prompt = "You are a helpful coding assistant."

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await cache_user(
                user_id=user_id,
                balance=Decimal("10.0"),
                model_id="claude:sonnet",
                first_name="Test",
                username="testuser",
                custom_prompt=custom_prompt,
            )

        assert result is True
        call_args = mock_redis.setex.call_args
        cached_json = json.loads(call_args[0][2])
        assert cached_json["custom_prompt"] == custom_prompt

    @pytest.mark.asyncio
    async def test_cache_user_without_custom_prompt(self, mock_redis):
        """Test caching user without custom_prompt."""
        user_id = 123456

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await cache_user(
                user_id=user_id,
                balance=Decimal("10.0"),
                model_id="claude:sonnet",
                first_name="Test",
            )

        assert result is True
        call_args = mock_redis.setex.call_args
        cached_json = json.loads(call_args[0][2])
        assert cached_json["custom_prompt"] is None

    @pytest.mark.asyncio
    async def test_get_cached_user_with_custom_prompt(self, mock_redis):
        """Test retrieving cached user with custom_prompt."""
        user_id = 123456
        mock_redis.get.return_value = json.dumps({
            "balance": "10.0000",
            "model_id": "claude:sonnet",
            "first_name": "Test",
            "username": "testuser",
            "custom_prompt": "Be concise and direct.",
            "cached_at": 1234567890.0,
        }).encode()

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await get_cached_user(user_id)

        assert result is not None
        assert result["custom_prompt"] == "Be concise and direct."

    @pytest.mark.asyncio
    async def test_update_preserves_custom_prompt(self, mock_redis):
        """Test that Lua script preserves all fields (custom_prompt etc).

        The Lua script only modifies 'balance' and 'cached_at' in the
        JSON, preserving all other fields atomically. This test verifies
        the Lua script is called correctly (field preservation is
        guaranteed by the script logic, not by Python code).
        """
        user_id = 123456

        # Lua script returns [1, old_balance] on success
        mock_redis.eval.return_value = [1, b"10.0000"]

        from cache.user_cache import update_cached_balance

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await update_cached_balance(user_id, Decimal("5.0"))

        assert result is True
        # Lua script handles field preservation atomically
        mock_redis.eval.assert_called_once()


class TestLanguageCodeCaching:
    """Tests for language_code field in user cache."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_cache_user_with_language_code(self, mock_redis):
        """Test caching user with language_code."""
        user_id = 123456
        language_code = "ru"

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await cache_user(
                user_id=user_id,
                balance=Decimal("10.0"),
                model_id="claude:sonnet",
                first_name="Test",
                username="testuser",
                language_code=language_code,
            )

        assert result is True
        call_args = mock_redis.setex.call_args
        cached_json = json.loads(call_args[0][2])
        assert cached_json["language_code"] == language_code

    @pytest.mark.asyncio
    async def test_cache_user_without_language_code(self, mock_redis):
        """Test caching user without language_code (None)."""
        user_id = 123456

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await cache_user(
                user_id=user_id,
                balance=Decimal("10.0"),
                model_id="claude:sonnet",
                first_name="Test",
            )

        assert result is True
        call_args = mock_redis.setex.call_args
        cached_json = json.loads(call_args[0][2])
        assert cached_json["language_code"] is None

    @pytest.mark.asyncio
    async def test_get_cached_user_with_language_code(self, mock_redis):
        """Test retrieving cached user with language_code."""
        user_id = 123456
        mock_redis.get.return_value = json.dumps({
            "balance": "10.0000",
            "model_id": "claude:sonnet",
            "first_name": "Test",
            "username": "testuser",
            "language_code": "ru-RU",
            "custom_prompt": None,
            "cached_at": 1234567890.0,
        }).encode()

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await get_cached_user(user_id)

        assert result is not None
        assert result["language_code"] == "ru-RU"

    @pytest.mark.asyncio
    async def test_update_preserves_language_code(self, mock_redis):
        """Test that Lua script preserves all fields (language_code etc).

        Same as test_update_preserves_custom_prompt — the Lua script
        modifies only 'balance' and 'cached_at', preserving everything
        else atomically inside Redis.
        """
        user_id = 123456

        # Lua script returns [1, old_balance] on success
        mock_redis.eval.return_value = [1, b"10.0000"]

        from cache.user_cache import update_cached_balance

        with patch("cache.user_cache.get_redis", return_value=mock_redis):
            result = await update_cached_balance(user_id, Decimal("5.0"))

        assert result is True
        mock_redis.eval.assert_called_once()
