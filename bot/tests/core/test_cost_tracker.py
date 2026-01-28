"""Tests for core.cost_tracker module."""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

from core.cost_tracker import CostTracker
import pytest


class TestCostTrackerInit:
    """Tests for CostTracker initialization."""

    def test_init_basic(self):
        """Test basic initialization."""
        tracker = CostTracker(model_id="test-model", user_id=123)

        assert tracker.model_id == "test-model"
        assert tracker.user_id == 123
        assert tracker.total_input_tokens == 0
        assert tracker.total_output_tokens == 0
        assert tracker.total_thinking_tokens == 0
        assert tracker.tool_costs == []

    def test_init_with_callbacks(self):
        """Test initialization with callbacks."""
        on_api = Mock()
        on_tool = Mock()
        on_final = Mock()

        tracker = CostTracker(
            model_id="test",
            user_id=1,
            on_api_usage=on_api,
            on_tool_cost=on_tool,
            on_finalize=on_final,
        )

        assert tracker._on_api_usage is on_api
        assert tracker._on_tool_cost is on_tool
        assert tracker._on_finalize is on_final


class TestAddApiUsage:
    """Tests for add_api_usage method."""

    def test_add_api_usage_basic(self):
        """Test adding API usage."""
        tracker = CostTracker(model_id="test", user_id=1)

        tracker.add_api_usage(1000, 500)

        assert tracker.total_input_tokens == 1000
        assert tracker.total_output_tokens == 500
        assert tracker.total_thinking_tokens == 0

    def test_add_api_usage_with_thinking(self):
        """Test adding API usage with thinking tokens."""
        tracker = CostTracker(model_id="test", user_id=1)

        tracker.add_api_usage(1000, 500, thinking_tokens=200)

        assert tracker.total_thinking_tokens == 200

    def test_add_api_usage_cumulative(self):
        """Test that API usage accumulates."""
        tracker = CostTracker(model_id="test", user_id=1)

        tracker.add_api_usage(1000, 500)
        tracker.add_api_usage(500, 300, thinking_tokens=100)

        assert tracker.total_input_tokens == 1500
        assert tracker.total_output_tokens == 800
        assert tracker.total_thinking_tokens == 100

    def test_add_api_usage_calls_callback(self):
        """Test that callback is called."""
        callback = Mock()
        tracker = CostTracker(model_id="test", user_id=1, on_api_usage=callback)

        tracker.add_api_usage(1000, 500, thinking_tokens=200)

        callback.assert_called_once_with(1000, 500, 200)


class TestAddToolCost:
    """Tests for add_tool_cost method."""

    def test_add_tool_cost_basic(self):
        """Test adding tool cost."""
        tracker = CostTracker(model_id="test", user_id=1)

        tracker.add_tool_cost("execute_python", Decimal("0.001"))

        assert len(tracker.tool_costs) == 1
        assert tracker.tool_costs[0] == ("execute_python", Decimal("0.001"))

    def test_add_tool_cost_multiple(self):
        """Test adding multiple tool costs."""
        tracker = CostTracker(model_id="test", user_id=1)

        tracker.add_tool_cost("execute_python", Decimal("0.001"))
        tracker.add_tool_cost("analyze_image", Decimal("0.01"))

        assert len(tracker.tool_costs) == 2

    def test_add_tool_cost_calls_callback(self):
        """Test that callback is called."""
        callback = Mock()
        tracker = CostTracker(model_id="test", user_id=1, on_tool_cost=callback)

        tracker.add_tool_cost("test_tool", Decimal("0.05"))

        callback.assert_called_once_with("test_tool", Decimal("0.05"))


class TestCalculateTotalCost:
    """Tests for calculate_total_cost method."""

    def test_calculate_total_cost_tokens_only(self):
        """Test calculating cost with only tokens."""
        tracker = CostTracker(model_id="claude-opus-4-5-20251101", user_id=1)
        tracker.add_api_usage(1000000, 100000)  # 1M in, 100K out

        with patch("core.cost_tracker.calculate_claude_cost") as mock_calc:
            mock_calc.return_value = Decimal("7.50")  # $5 in + $2.50 out
            cost = tracker.calculate_total_cost()

            mock_calc.assert_called_once()
            assert cost == Decimal("7.50")

    def test_calculate_total_cost_with_tools(self):
        """Test calculating cost with tokens and tools."""
        tracker = CostTracker(model_id="test", user_id=1)
        tracker.add_api_usage(1000, 500)
        tracker.add_tool_cost("tool1", Decimal("0.10"))
        tracker.add_tool_cost("tool2", Decimal("0.20"))

        with patch("core.cost_tracker.calculate_claude_cost") as mock_calc:
            mock_calc.return_value = Decimal("0.50")
            cost = tracker.calculate_total_cost()

            # 0.50 tokens + 0.10 + 0.20 tools = 0.80
            assert cost == Decimal("0.80")


class TestGetTokenSummary:
    """Tests for get_token_summary method."""

    def test_get_token_summary(self):
        """Test getting token summary."""
        tracker = CostTracker(model_id="test", user_id=1)
        tracker.add_api_usage(1000, 500, thinking_tokens=200)

        summary = tracker.get_token_summary()

        assert summary == {
            "input": 1000,
            "output": 500,
            "thinking": 200,
        }


class TestGetToolCostSummary:
    """Tests for get_tool_cost_summary method."""

    def test_get_tool_cost_summary_empty(self):
        """Test summary with no tools."""
        tracker = CostTracker(model_id="test", user_id=1)

        summary = tracker.get_tool_cost_summary()

        assert summary == {"costs": [], "total": 0.0}

    def test_get_tool_cost_summary_with_costs(self):
        """Test summary with tool costs."""
        tracker = CostTracker(model_id="test", user_id=1)
        tracker.add_tool_cost("tool1", Decimal("0.10"))
        tracker.add_tool_cost("tool2", Decimal("0.25"))

        summary = tracker.get_tool_cost_summary()

        assert summary["costs"] == [("tool1", 0.10), ("tool2", 0.25)]
        assert summary["total"] == 0.35


class TestFinalizeAndCharge:
    """Tests for finalize_and_charge method."""

    @pytest.mark.asyncio
    async def test_finalize_and_charge_basic(self):
        """Test finalizing and charging user."""
        tracker = CostTracker(model_id="test-model", user_id=123)
        tracker.add_api_usage(1000, 500)

        mock_session = AsyncMock()

        with patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.cost_tracker.calculate_claude_cost") as mock_calc:
            mock_calc.return_value = Decimal("0.05")
            mock_factory = Mock()
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            total = await tracker.finalize_and_charge(
                session=mock_session,
                user_id=123,
                source="test_source",
                verdict="PASS",
                iterations=2,
            )

            assert total == Decimal("0.05")
            mock_factory.balance.charge_user.assert_called_once()
            call_kwargs = mock_factory.balance.charge_user.call_args.kwargs
            assert call_kwargs["user_id"] == 123
            assert call_kwargs["amount"] == Decimal("0.05")
            assert "test_source" in call_kwargs["description"]

    @pytest.mark.asyncio
    async def test_finalize_and_charge_calls_callback(self):
        """Test that finalize callback is called."""
        callback = Mock()
        tracker = CostTracker(
            model_id="test",
            user_id=1,
            on_finalize=callback,
        )

        mock_session = AsyncMock()

        with patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.cost_tracker.calculate_claude_cost") as mock_calc:
            mock_calc.return_value = Decimal("0.10")
            mock_factory = Mock()
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            await tracker.finalize_and_charge(
                session=mock_session,
                user_id=1,
                source="test",
                verdict="PASS",
                iterations=3,
            )

            callback.assert_called_once_with("PASS", 3, Decimal("0.10"))
