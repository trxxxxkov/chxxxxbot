"""Tests for tool cost pre-check functionality.

Tests that paid tools are blocked when user balance is negative,
while free tools continue to work.
"""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.handlers.claude_tools import execute_single_tool_safe
from telegram.handlers.claude_tools import get_user_balance


class TestGetUserBalance:
    """Tests for get_user_balance() function."""

    @pytest.mark.asyncio
    async def test_returns_cached_balance(self):
        """Returns balance from Redis cache when available."""
        mock_session = AsyncMock()
        cached_data = {
            "balance": "1.50",
            "model_id": "claude-sonnet-4-5-20250929",
            "first_name": "Test",
            "username": None,
            "cached_at": 1234567890.0,
        }

        with patch(
                "telegram.handlers.claude_tools.get_cached_user",
                return_value=cached_data,
        ):
            balance = await get_user_balance(123, mock_session)

        assert balance == Decimal("1.50")
        # Should not query database when cache hit
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_to_database(self):
        """Falls back to database when cache miss."""
        mock_user = MagicMock()
        mock_user.balance = Decimal("-0.50")

        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=mock_user)

        mock_services = MagicMock()
        mock_services.users = mock_repo

        with patch(
                "telegram.handlers.claude_tools.get_cached_user",
                return_value=None,
        ), patch(
                "telegram.handlers.claude_tools.ServiceFactory",
                return_value=mock_services,
        ):
            mock_session = AsyncMock()
            balance = await get_user_balance(123, mock_session)

        assert balance == Decimal("-0.50")
        mock_repo.get.assert_called_once_with(123)

    @pytest.mark.asyncio
    async def test_returns_none_if_user_not_found(self):
        """Returns None if user not found in cache or database."""
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=None)

        mock_services = MagicMock()
        mock_services.users = mock_repo

        with patch(
                "telegram.handlers.claude_tools.get_cached_user",
                return_value=None,
        ), patch(
                "telegram.handlers.claude_tools.ServiceFactory",
                return_value=mock_services,
        ):
            mock_session = AsyncMock()
            balance = await get_user_balance(999, mock_session)

        assert balance is None


class TestExecuteSingleToolSafePrecheck:
    """Tests for balance pre-check in execute_single_tool_safe()."""

    @pytest.mark.asyncio
    async def test_paid_tool_rejected_when_negative_balance(self):
        """Paid tool is rejected when user balance is negative."""
        mock_session = AsyncMock()
        mock_bot = MagicMock()

        with patch(
                "telegram.handlers.claude_tools.get_user_balance",
                return_value=Decimal("-0.08"),
        ), patch("telegram.handlers.claude_tools.record_tool_precheck_rejected",
                ) as mock_metric:
            result = await execute_single_tool_safe(
                tool_name="generate_image",
                tool_input={"prompt": "a cat"},
                bot=mock_bot,
                session=mock_session,
                thread_id=1,
                user_id=123,
            )

        assert result["error"] == "insufficient_balance"
        assert "balance is negative" in result["message"]
        assert "/pay" in result["message"]
        assert result["balance_usd"] == "-0.08"
        assert result["tool_name"] == "generate_image"
        mock_metric.assert_called_once_with("generate_image")

    @pytest.mark.asyncio
    async def test_paid_tool_allowed_when_positive_balance(self):
        """Paid tool is allowed when user balance is positive."""
        mock_session = AsyncMock()
        mock_bot = MagicMock()

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
                session=mock_session,
                thread_id=1,
                user_id=123,
            )

        assert "error" not in result or result.get(
            "error") != "insufficient_balance"
        assert result.get("result") == "success"

    @pytest.mark.asyncio
    async def test_paid_tool_allowed_when_zero_balance(self):
        """Paid tool is allowed when user balance is exactly zero."""
        mock_session = AsyncMock()
        mock_bot = MagicMock()

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
                session=mock_session,
                thread_id=1,
                user_id=123,
            )

        assert result.get("error") != "insufficient_balance"
        assert result.get("result") == "success"

    @pytest.mark.asyncio
    async def test_free_tool_allowed_when_negative_balance(self):
        """Free tool is allowed even when user balance is negative."""
        mock_session = AsyncMock()
        mock_bot = MagicMock()

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
                session=mock_session,
                thread_id=1,
                user_id=123,
            )

        assert result.get("error") != "insufficient_balance"
        assert result.get("result") == "success"

    @pytest.mark.asyncio
    async def test_precheck_disabled_by_config(self):
        """Pre-check is skipped when disabled in config."""
        mock_session = AsyncMock()
        mock_bot = MagicMock()

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
                session=mock_session,
                thread_id=1,
                user_id=123,
            )

        # Balance should not be checked when feature disabled
        mock_get_balance.assert_not_called()
        assert result.get("result") == "success"

    @pytest.mark.asyncio
    async def test_all_paid_tools_rejected_when_negative(self):
        """All 7 paid tools are rejected when balance is negative."""
        mock_session = AsyncMock()
        mock_bot = MagicMock()

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
                    session=mock_session,
                    thread_id=1,
                    user_id=123,
                )

            assert result["error"] == "insufficient_balance", (
                f"{tool_name} should be rejected")

    @pytest.mark.asyncio
    async def test_precheck_handles_balance_none(self):
        """Pre-check allows execution if balance is None (new user)."""
        mock_session = AsyncMock()
        mock_bot = MagicMock()

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
                session=mock_session,
                thread_id=1,
                user_id=123,
            )

        assert result.get("error") != "insufficient_balance"
        assert result.get("result") == "success"


class TestPrecheckMetadata:
    """Tests for metadata in precheck rejection results."""

    @pytest.mark.asyncio
    async def test_rejection_includes_duration(self):
        """Rejection result includes _duration for consistency."""
        mock_session = AsyncMock()
        mock_bot = MagicMock()

        with patch(
                "telegram.handlers.claude_tools.get_user_balance",
                return_value=Decimal("-1"),
        ), patch("telegram.handlers.claude_tools.record_tool_precheck_rejected",
                ):
            result = await execute_single_tool_safe(
                tool_name="generate_image",
                tool_input={"prompt": "test"},
                bot=mock_bot,
                session=mock_session,
                thread_id=1,
                user_id=123,
            )

        assert "_duration" in result
        assert "_start_time" in result
        assert "_tool_name" in result
        assert result["_tool_name"] == "generate_image"
