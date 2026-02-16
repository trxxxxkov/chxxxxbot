"""Tests for session rollback on charge failure.

Regression tests for the PendingRollbackError cascade bug:
when charge_user() fails (e.g., UniqueViolationError), the session
must be rolled back so subsequent operations don't fail.

Bug: 2026-02-15 — duplicate key on balance_operations_pkey caused
PendingRollbackError cascade that broke the entire handler session.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from telegram.handlers.claude_tools import charge_for_tool


class TestChargeForToolRollback:
    """Test charge_for_tool rolls back session on failure."""

    @pytest.mark.asyncio
    async def test_charge_for_tool_success(self):
        """Test normal charge_for_tool flow commits nothing extra."""
        session = AsyncMock()
        mock_service = AsyncMock()
        mock_service.balance.charge_user.return_value = Decimal("1.0")

        with patch(
                "telegram.handlers.claude_tools.ServiceFactory",
                return_value=mock_service,
        ):
            await charge_for_tool(
                session=session,
                user_id=123,
                tool_name="analyze_image",
                result={"cost_usd": 0.025},
                message_id=456,
            )

        # charge_user already commits internally, no extra commit
        mock_service.balance.charge_user.assert_awaited_once()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_charge_for_tool_rollback_on_integrity_error(self):
        """Test session is rolled back when charge_user raises IntegrityError.

        Regression test: UniqueViolationError on balance_operations_pkey
        must not leave session in PendingRollbackError state.
        """
        session = AsyncMock()
        mock_service = AsyncMock()
        mock_service.balance.charge_user.side_effect = IntegrityError(
            statement="INSERT INTO balance_operations ...",
            params={},
            orig=Exception("duplicate key"),
        )

        with patch(
                "telegram.handlers.claude_tools.ServiceFactory",
                return_value=mock_service,
        ):
            # Should NOT raise — error is caught and logged
            await charge_for_tool(
                session=session,
                user_id=123,
                tool_name="analyze_image",
                result={"cost_usd": 0.025},
                message_id=456,
            )

        # Session MUST be rolled back to clear PendingRollbackError state
        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_charge_for_tool_rollback_on_any_exception(self):
        """Test session is rolled back on any exception from charge_user."""
        session = AsyncMock()
        mock_service = AsyncMock()
        mock_service.balance.charge_user.side_effect = RuntimeError(
            "unexpected DB error")

        with patch(
                "telegram.handlers.claude_tools.ServiceFactory",
                return_value=mock_service,
        ):
            await charge_for_tool(
                session=session,
                user_id=123,
                tool_name="web_search",
                result={"cost_usd": 0.01},
                message_id=789,
            )

        session.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_charge_for_tool_session_usable_after_error(self):
        """Test that session can be used after charge_for_tool error.

        After rollback, the session must not be in PendingRollbackError
        state, so subsequent flush/commit should work.
        """
        session = AsyncMock()
        mock_service = AsyncMock()
        mock_service.balance.charge_user.side_effect = IntegrityError(
            statement="INSERT",
            params={},
            orig=Exception("duplicate key"),
        )

        with patch(
                "telegram.handlers.claude_tools.ServiceFactory",
                return_value=mock_service,
        ):
            await charge_for_tool(
                session=session,
                user_id=123,
                tool_name="analyze_image",
                result={"cost_usd": 0.025},
                message_id=456,
            )

        # After rollback, session should be usable
        session.rollback.assert_awaited_once()

        # Simulate subsequent operation — should not raise
        session.reset_mock()
        await session.flush()
        session.flush.assert_awaited_once()
