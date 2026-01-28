"""Tests for core.subagent.base module."""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

from core.subagent.base import BaseSubagent
from core.subagent.base import SubagentConfig
from core.subagent.base import SubagentResult
import pytest


class TestSubagentResult:
    """Tests for SubagentResult dataclass."""

    def test_success_property_true(self):
        """Test success property returns True for good verdicts."""
        result = SubagentResult(
            verdict="PASS",
            cost_usd=0.05,
            iterations=1,
        )
        assert result.success is True

    def test_success_property_false_on_error(self):
        """Test success property returns False for ERROR verdict."""
        result = SubagentResult(
            verdict="ERROR",
            cost_usd=0.05,
            iterations=1,
        )
        assert result.success is False

    def test_success_property_false_on_cost_cap(self):
        """Test success property returns False for COST_CAP verdict."""
        result = SubagentResult(
            verdict="COST_CAP",
            cost_usd=0.50,
            iterations=5,
        )
        assert result.success is False

    def test_success_property_false_with_error(self):
        """Test success property returns False when error is set."""
        result = SubagentResult(
            verdict="PASS",
            cost_usd=0.05,
            iterations=1,
            error="some error",
        )
        assert result.success is False


class TestSubagentConfig:
    """Tests for SubagentConfig dataclass."""

    def test_config_defaults(self):
        """Test config has sensible defaults."""
        config = SubagentConfig(
            model_id="test-model",
            system_prompt="You are a test agent.",
            tools=[],
        )

        assert config.max_iterations == 8
        assert config.thinking_budget_tokens == 10000
        assert config.max_tokens == 16000
        assert config.cost_cap_usd == Decimal("0.50")
        assert config.min_balance_usd == Decimal("0.50")

    def test_config_custom_values(self):
        """Test config accepts custom values."""
        config = SubagentConfig(
            model_id="custom-model",
            system_prompt="Custom prompt",
            tools=[{
                "name": "test"
            }],
            max_iterations=5,
            thinking_budget_tokens=5000,
            cost_cap_usd=Decimal("1.00"),
        )

        assert config.max_iterations == 5
        assert config.thinking_budget_tokens == 5000
        assert config.cost_cap_usd == Decimal("1.00")


class TestBaseSubagentInit:
    """Tests for BaseSubagent initialization."""

    def test_init_stores_config(self):
        """Test initialization stores configuration."""
        config = SubagentConfig(
            model_id="test",
            system_prompt="Test",
            tools=[],
        )
        client = Mock()
        bot = Mock()
        session = Mock()

        # Create concrete subclass for testing
        class TestSubagent(BaseSubagent):

            async def _execute_tool(self, tool_name, tool_input, tool_use_id):
                return {}

            def _parse_result(self, response_text):
                return {"verdict": "PASS"}

        subagent = TestSubagent(config, client, bot, session, user_id=123)

        assert subagent.config is config
        assert subagent.client is client
        assert subagent.bot is bot
        assert subagent.session is session
        assert subagent.user_id == 123

    def test_init_creates_cost_tracker(self):
        """Test initialization creates cost tracker."""
        config = SubagentConfig(
            model_id="test-model",
            system_prompt="Test",
            tools=[],
        )

        class TestSubagent(BaseSubagent):

            async def _execute_tool(self, tool_name, tool_input, tool_use_id):
                return {}

            def _parse_result(self, response_text):
                return {"verdict": "PASS"}

        subagent = TestSubagent(config, Mock(), Mock(), Mock(), user_id=123)

        assert subagent.cost_tracker is not None
        assert subagent.cost_tracker.model_id == "test-model"
        assert subagent.cost_tracker.user_id == 123


class TestBaseSubagentRun:
    """Tests for BaseSubagent.run method."""

    @pytest.fixture
    def test_subagent_class(self):
        """Create a test subagent class."""

        class TestSubagent(BaseSubagent):

            async def _execute_tool(self, tool_name, tool_input, tool_use_id):
                return {"result": "ok"}

            def _parse_result(self, response_text):
                import json
                return json.loads(response_text)

        return TestSubagent

    @pytest.mark.asyncio
    async def test_run_checks_balance_first(self, test_subagent_class):
        """Test that run checks balance before proceeding."""
        config = SubagentConfig(
            model_id="test",
            system_prompt="Test",
            tools=[],
            min_balance_usd=Decimal("1.00"),
        )

        subagent = test_subagent_class(config,
                                       Mock(),
                                       Mock(),
                                       Mock(),
                                       user_id=123)

        with patch("services.factory.ServiceFactory") as mock_factory_class:
            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("0.50")  # Less than min
            )
            mock_factory_class.return_value = mock_factory

            result = await subagent.run("Test message")

            assert result.verdict == "SKIPPED"
            assert result.error == "insufficient_balance"

    @pytest.mark.asyncio
    async def test_run_end_turn_returns_result(self, test_subagent_class):
        """Test that end_turn response returns parsed result."""
        config = SubagentConfig(
            model_id="test",
            system_prompt="Test",
            tools=[],
        )
        client = AsyncMock()

        # Mock response with end_turn
        mock_response = Mock()
        mock_response.stop_reason = "end_turn"
        mock_response.usage = Mock()
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 50
        mock_response.usage.thinking_tokens = None
        mock_response.content = [
            Mock(type="text", text='{"verdict": "PASS", "score": 95}')
        ]
        client.messages.create = AsyncMock(return_value=mock_response)

        subagent = test_subagent_class(config,
                                       client,
                                       Mock(),
                                       Mock(),
                                       user_id=123)

        with patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.subagent.base.calculate_claude_cost") as mock_calc:
            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("10.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory
            mock_calc.return_value = Decimal("0.01")

            result = await subagent.run("Test message")

            assert result.verdict == "PASS"
            assert result.data["score"] == 95
            assert result.iterations == 1


class TestBaseSubagentAbstractMethods:
    """Tests for abstract method enforcement."""

    def test_cannot_instantiate_without_execute_tool(self):
        """Test that subclass must implement _execute_tool."""

        class IncompleteSubagent(BaseSubagent):

            def _parse_result(self, response_text):
                return {}

        config = SubagentConfig(model_id="test", system_prompt="", tools=[])

        with pytest.raises(TypeError) as exc_info:
            IncompleteSubagent(config, Mock(), Mock(), Mock(), user_id=1)

        assert "_execute_tool" in str(exc_info.value)

    def test_cannot_instantiate_without_parse_result(self):
        """Test that subclass must implement _parse_result."""

        class IncompleteSubagent(BaseSubagent):

            async def _execute_tool(self, tool_name, tool_input, tool_use_id):
                return {}

        config = SubagentConfig(model_id="test", system_prompt="", tools=[])

        with pytest.raises(TypeError) as exc_info:
            IncompleteSubagent(config, Mock(), Mock(), Mock(), user_id=1)

        assert "_parse_result" in str(exc_info.value)
