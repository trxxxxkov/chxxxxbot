"""Tests for tool cost pre-check functionality.

Tests that paid tools are blocked when user balance is negative,
while free tools continue to work.

Phase 5.3 Refactored: Reduced patches from 22 to ~12.
- Uses real DB session with sample_user fixture for balance lookups
- Only mocks cache layer and external tool execution
"""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.handlers.claude_tools import execute_single_tool_safe
from telegram.handlers.claude_tools import get_user_balance

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_bot():
    """Create mock Telegram bot."""
    return MagicMock()


@pytest.fixture
def user_with_positive_balance(sample_user):
    """User with positive balance for testing."""
    sample_user.balance = Decimal("1.50")
    return sample_user


@pytest.fixture
def user_with_negative_balance(sample_user):
    """User with negative balance for testing."""
    sample_user.balance = Decimal("-0.08")
    return sample_user


@pytest.fixture
def user_with_zero_balance(sample_user):
    """User with zero balance for testing."""
    sample_user.balance = Decimal("0.00")
    return sample_user


# ============================================================================
# Tests for get_user_balance()
# ============================================================================


class TestGetUserBalance:
    """Tests for get_user_balance() function."""

    @pytest.mark.asyncio
    async def test_returns_cached_balance(self, test_session):
        """Returns balance from Redis cache when available."""
        cached_data = {
            "balance": "1.50",
            "model_id": "claude-sonnet-4-6",
            "first_name": "Test",
            "username": None,
            "cached_at": 1234567890.0,
        }

        with patch(
                "services.balance_policy.get_cached_user",
                return_value=cached_data,
        ), patch(
                "services.balance_policy.get_balance_from_cached",
                return_value=Decimal("1.50"),
        ):
            balance = await get_user_balance(123, test_session)

        assert balance == Decimal("1.50")

    @pytest.mark.asyncio
    async def test_fallback_to_database(self, test_session, sample_user):
        """Falls back to database when cache miss."""
        # Set up user with specific balance
        sample_user.balance = Decimal("-0.50")
        await test_session.flush()

        with patch(
                "services.balance_policy.get_cached_user",
                return_value=None,
        ):
            balance = await get_user_balance(sample_user.id, test_session)

        assert balance == Decimal("-0.50")

    @pytest.mark.asyncio
    async def test_returns_zero_if_user_not_found(self, test_session):
        """Returns 0 if user not found in cache or database."""
        with patch(
                "services.balance_policy.get_cached_user",
                return_value=None,
        ):
            balance = await get_user_balance(999999999, test_session)

        # BalancePolicy returns 0 for unknown users (fail-open)
        assert balance == Decimal("0")


# ============================================================================
# Tests for execute_single_tool_safe() pre-check
# ============================================================================


class TestExecuteSingleToolSafePrecheck:
    """Tests for balance pre-check in execute_single_tool_safe()."""

    @pytest.mark.asyncio
    async def test_paid_tool_rejected_when_negative_balance(
            self, test_session, mock_bot, user_with_negative_balance):
        """Paid tool is rejected when user balance is negative."""
        with patch(
                "telegram.handlers.claude_tools.get_user_balance",
                return_value=Decimal("-0.08"),
        ), patch("telegram.handlers.claude_tools.record_tool_precheck_rejected",
                ) as mock_metric:
            result = await execute_single_tool_safe(
                tool_name="generate_image",
                tool_input={"prompt": "a cat"},
                bot=mock_bot,
                session=test_session,
                thread_id=1,
                user_id=user_with_negative_balance.id,
            )

        assert result["error"] == "insufficient_balance"
        assert "balance is negative" in result["message"]
        assert "/pay" in result["message"]
        assert result["balance_usd"] == "-0.08"
        assert result["tool_name"] == "generate_image"
        mock_metric.assert_called_once_with("generate_image")

    @pytest.mark.asyncio
    async def test_paid_tool_allowed_when_positive_balance(
            self, test_session, mock_bot, user_with_positive_balance):
        """Paid tool is allowed when user balance is positive."""
        with patch(
                "telegram.handlers.claude_tools.get_user_balance",
                return_value=Decimal("1.50"),
        ), patch(
                "telegram.handlers.claude_tools.execute_tool",
                return_value={
                    "result": "success",
                    "cost_usd": 0.134
                },
        ):
            result = await execute_single_tool_safe(
                tool_name="generate_image",
                tool_input={"prompt": "a cat"},
                bot=mock_bot,
                session=test_session,
                thread_id=1,
                user_id=user_with_positive_balance.id,
            )

        assert "error" not in result or result.get(
            "error") != "insufficient_balance"
        assert result.get("result") == "success"

    @pytest.mark.asyncio
    async def test_paid_tool_allowed_when_zero_balance(self, test_session,
                                                       mock_bot,
                                                       user_with_zero_balance):
        """Paid tool is allowed when user balance is exactly zero."""
        with patch(
                "telegram.handlers.claude_tools.get_user_balance",
                return_value=Decimal("0.00"),
        ), patch(
                "telegram.handlers.claude_tools.execute_tool",
                return_value={
                    "result": "success",
                    "cost_usd": 0.01
                },
        ):
            result = await execute_single_tool_safe(
                tool_name="web_search",
                tool_input={"query": "test"},
                bot=mock_bot,
                session=test_session,
                thread_id=1,
                user_id=user_with_zero_balance.id,
            )

        assert result.get("error") != "insufficient_balance"
        assert result.get("result") == "success"

    @pytest.mark.asyncio
    async def test_free_tool_allowed_when_negative_balance(
            self, test_session, mock_bot, user_with_negative_balance):
        """Free tool is allowed even when user balance is negative."""
        # get_user_balance is not called for free tools (optimization)
        with patch(
                "telegram.handlers.claude_tools.execute_tool",
                return_value={
                    "result": "success",
                    "latex": "\\frac{1}{2}"
                },
        ):
            result = await execute_single_tool_safe(
                tool_name="render_latex",
                tool_input={"latex": "\\frac{1}{2}"},
                bot=mock_bot,
                session=test_session,
                thread_id=1,
                user_id=user_with_negative_balance.id,
            )

        assert result.get("error") != "insufficient_balance"
        assert result.get("result") == "success"

    @pytest.mark.asyncio
    async def test_precheck_disabled_by_config(self, test_session, mock_bot,
                                               sample_user):
        """Pre-check is skipped when disabled in config."""
        with patch(
                "telegram.handlers.claude_tools.config.TOOL_COST_PRECHECK_ENABLED",
                False,
        ), patch(
                "telegram.handlers.claude_tools.get_user_balance",
                return_value=Decimal("-100"),
        ) as mock_get_balance, patch(
                "telegram.handlers.claude_tools.execute_tool",
                return_value={"result": "success"},
        ):
            result = await execute_single_tool_safe(
                tool_name="generate_image",
                tool_input={"prompt": "a cat"},
                bot=mock_bot,
                session=test_session,
                thread_id=1,
                user_id=sample_user.id,
            )

        # Balance should not be checked when feature disabled
        mock_get_balance.assert_not_called()
        assert result.get("result") == "success"

    @pytest.mark.asyncio
    async def test_all_paid_tools_rejected_when_negative(
            self, test_session, mock_bot, sample_user):
        """All 7 paid tools are rejected when balance is negative."""
        paid_tools = [
            ("generate_image", {
                "prompt": "test"
            }),
            ("transcribe_audio", {
                "file_id": "abc"
            }),
            ("web_search", {
                "query": "test"
            }),
            ("execute_python", {
                "code": "print(1)"
            }),
            ("analyze_image", {
                "file_id": "abc",
                "question": "what is this?"
            }),
            ("analyze_pdf", {
                "file_id": "abc",
                "question": "summarize"
            }),
            ("preview_file", {
                "file_id": "abc"
            }),
        ]

        for tool_name, tool_input in paid_tools:
            with patch(
                    "telegram.handlers.claude_tools.get_user_balance",
                    return_value=Decimal("-0.01"),
            ), patch(
                    "telegram.handlers.claude_tools.record_tool_precheck_rejected",
            ):
                result = await execute_single_tool_safe(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    bot=mock_bot,
                    session=test_session,
                    thread_id=1,
                    user_id=sample_user.id,
                )

            assert result["error"] == "insufficient_balance", (
                f"{tool_name} should be rejected")

    @pytest.mark.asyncio
    async def test_precheck_handles_balance_none(self, test_session, mock_bot,
                                                 sample_user):
        """Pre-check allows execution if balance is None (new user)."""
        with patch(
                "telegram.handlers.claude_tools.get_user_balance",
                return_value=None,
        ), patch(
                "telegram.handlers.claude_tools.execute_tool",
                return_value={
                    "result": "success",
                    "cost_usd": 0.01
                },
        ):
            result = await execute_single_tool_safe(
                tool_name="web_search",
                tool_input={"query": "test"},
                bot=mock_bot,
                session=test_session,
                thread_id=1,
                user_id=sample_user.id,
            )

        assert result.get("error") != "insufficient_balance"
        assert result.get("result") == "success"


# ============================================================================
# Tests for precheck metadata
# ============================================================================


class TestPrecheckMetadata:
    """Tests for metadata in precheck rejection results."""

    @pytest.mark.asyncio
    async def test_rejection_includes_duration(self, test_session, mock_bot,
                                               sample_user):
        """Rejection result includes _duration for consistency."""
        with patch(
                "telegram.handlers.claude_tools.get_user_balance",
                return_value=Decimal("-1"),
        ), patch("telegram.handlers.claude_tools.record_tool_precheck_rejected",
                ):
            result = await execute_single_tool_safe(
                tool_name="generate_image",
                tool_input={"prompt": "test"},
                bot=mock_bot,
                session=test_session,
                thread_id=1,
                user_id=sample_user.id,
            )

        assert "_duration" in result
        assert "_start_time" in result
        assert "_tool_name" in result
        assert result["_tool_name"] == "generate_image"


# ============================================================================
# Tests with real DB lookup (integration style)
# ============================================================================


class TestGetUserBalanceIntegration:
    """Integration tests for get_user_balance with real DB."""

    @pytest.mark.asyncio
    async def test_balance_from_db_positive(self, test_session, sample_user):
        """Get positive balance from database when cache misses."""
        sample_user.balance = Decimal("5.00")
        await test_session.flush()

        with patch(
                "services.balance_policy.get_cached_user",
                return_value=None,
        ):
            balance = await get_user_balance(sample_user.id, test_session)

        assert balance == Decimal("5.00")

    @pytest.mark.asyncio
    async def test_balance_from_db_negative(self, test_session, sample_user):
        """Get negative balance from database when cache misses."""
        sample_user.balance = Decimal("-2.50")
        await test_session.flush()

        with patch(
                "services.balance_policy.get_cached_user",
                return_value=None,
        ):
            balance = await get_user_balance(sample_user.id, test_session)

        assert balance == Decimal("-2.50")

    @pytest.mark.asyncio
    async def test_cache_preferred_over_db(self, test_session, sample_user):
        """Cache value is used when available, even if DB differs."""
        # DB has different value
        sample_user.balance = Decimal("10.00")
        await test_session.flush()

        # But cache returns different value
        with patch(
                "services.balance_policy.get_cached_user",
                return_value={
                    "balance": "5.00",
                    "model_id": "claude:sonnet",
                    "cached_at": 1234567890.0,
                },
        ), patch(
                "services.balance_policy.get_balance_from_cached",
                return_value=Decimal("5.00"),
        ):
            balance = await get_user_balance(sample_user.id, test_session)

        # Cache value should be returned
        assert balance == Decimal("5.00")
