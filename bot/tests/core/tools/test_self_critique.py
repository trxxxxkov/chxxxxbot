"""Tests for self_critique verification subagent tool.

Tests include:
- Unit tests for CostTracker
- Unit tests for context building
- Unit tests for balance checks
- Unit tests for tool routing
- Integration tests with mocked Claude API
- E2E tests for full verification flow
"""

import asyncio
from decimal import Decimal
import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import pytest

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_clients():
    """Reset global clients before and after each test."""
    import core.clients
    core.clients._anthropic_sync_client = None
    core.clients._anthropic_sync_files = None
    yield
    core.clients._anthropic_sync_client = None
    core.clients._anthropic_sync_files = None


@pytest.fixture
def mock_bot():
    """Mock Telegram Bot for tests."""
    return Mock()


@pytest.fixture
def mock_session():
    """Mock database session with commit."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.add = Mock()
    return session


@pytest.fixture
def mock_user_repo():
    """Mock user repository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_balance_op_repo():
    """Mock balance operation repository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_model_config():
    """Mock model configuration for Opus."""
    config = Mock()
    config.model_id = "claude-opus-4-5-20251101"
    config.pricing_input = 15.0  # $15 per 1M input
    config.pricing_output = 75.0  # $75 per 1M output
    config.pricing_cache_read = None
    config.pricing_cache_write_5m = None
    return config


def create_mock_usage(input_tokens: int = 100,
                      output_tokens: int = 50,
                      thinking_tokens: int = 0):
    """Create a mock usage object with explicit thinking_tokens."""
    usage = Mock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.thinking_tokens = thinking_tokens
    return usage


def create_mock_response(
        stop_reason: str = "end_turn",
        content_text:
    str = '{"verdict": "PASS", "alignment_score": 90, "issues": []}',
        input_tokens: int = 100,
        output_tokens: int = 50,
        thinking_tokens: int = 0):
    """Create a mock API response."""
    mock_response = Mock()
    mock_response.stop_reason = stop_reason
    mock_response.usage = create_mock_usage(input_tokens, output_tokens,
                                            thinking_tokens)

    mock_text_block = Mock()
    mock_text_block.type = "text"
    mock_text_block.text = content_text
    mock_response.content = [mock_text_block]

    return mock_response


# =============================================================================
# CostTracker Unit Tests
# =============================================================================


class TestCostTracker:
    """Tests for CostTracker class."""

    def test_init(self):
        """Test CostTracker initialization."""
        from core.tools.self_critique import CostTracker

        tracker = CostTracker(model_id="claude-opus-4-5-20251101",
                              user_id=12345)

        assert tracker.model_id == "claude-opus-4-5-20251101"
        assert tracker.user_id == 12345
        assert tracker.total_input_tokens == 0
        assert tracker.total_output_tokens == 0
        assert tracker.total_thinking_tokens == 0
        assert tracker.tool_costs == []

    def test_add_api_usage(self):
        """Test adding API token usage."""
        from core.tools.self_critique import CostTracker

        tracker = CostTracker(model_id="claude-opus-4-5-20251101",
                              user_id=12345)

        tracker.add_api_usage(input_tokens=1000,
                              output_tokens=500,
                              thinking_tokens=200)

        assert tracker.total_input_tokens == 1000
        assert tracker.total_output_tokens == 500
        assert tracker.total_thinking_tokens == 200

    def test_add_api_usage_cumulative(self):
        """Test that API usage accumulates across calls."""
        from core.tools.self_critique import CostTracker

        tracker = CostTracker(model_id="claude-opus-4-5-20251101",
                              user_id=12345)

        tracker.add_api_usage(input_tokens=1000, output_tokens=500)
        tracker.add_api_usage(input_tokens=500, output_tokens=250)

        assert tracker.total_input_tokens == 1500
        assert tracker.total_output_tokens == 750

    def test_add_tool_cost(self):
        """Test adding tool costs."""
        from core.tools.self_critique import CostTracker

        tracker = CostTracker(model_id="claude-opus-4-5-20251101",
                              user_id=12345)

        tracker.add_tool_cost("execute_python", Decimal("0.005"))
        tracker.add_tool_cost("preview_file", Decimal("0.002"))

        assert len(tracker.tool_costs) == 2
        assert tracker.tool_costs[0] == ("execute_python", Decimal("0.005"))
        assert tracker.tool_costs[1] == ("preview_file", Decimal("0.002"))

    def test_calculate_total_cost(self):
        """Test total cost calculation."""
        from core.tools.self_critique import CostTracker

        tracker = CostTracker(model_id="claude-opus-4-5-20251101",
                              user_id=12345)

        # Add API usage
        tracker.add_api_usage(
            input_tokens=10000,  # 10K input
            output_tokens=2000,  # 2K output
            thinking_tokens=5000  # 5K thinking
        )

        # Add tool costs
        tracker.add_tool_cost("execute_python", Decimal("0.01"))

        with patch("core.cost_tracker.calculate_claude_cost") as mock_calc:
            mock_calc.return_value = Decimal("0.05")

            total = tracker.calculate_total_cost()

            mock_calc.assert_called_once_with(
                model_id="claude-opus-4-5-20251101",
                input_tokens=10000,
                output_tokens=2000,
                thinking_tokens=5000,
            )
            # Token cost (0.05) + tool cost (0.01) = 0.06
            assert total == Decimal("0.06")


# =============================================================================
# Context Building Tests
# =============================================================================


class TestBuildVerificationContext:
    """Tests for _build_verification_context function."""

    def test_basic_context(self):
        """Test basic context with only user_request."""
        from core.tools.self_critique import _build_verification_context

        result = _build_verification_context(
            user_request="Write a Python function",
            content=None,
            file_ids=None,
            verification_hints=None,
            focus_areas=None)

        assert "<verification_task>" in result
        assert "<original_user_request>" in result
        assert "Write a Python function" in result
        assert "<instructions>" in result

    def test_context_with_content(self):
        """Test context includes content to verify."""
        from core.tools.self_critique import _build_verification_context

        result = _build_verification_context(
            user_request="Write hello world",
            content="def hello():\n    print('Hello, World!')",
            file_ids=None,
            verification_hints=None,
            focus_areas=None)

        assert "<content_to_verify>" in result
        assert "def hello():" in result
        assert "print('Hello, World!')" in result

    def test_context_with_file_ids(self):
        """Test context includes file IDs."""
        from core.tools.self_critique import _build_verification_context

        result = _build_verification_context(
            user_request="Generate chart",
            content=None,
            file_ids=["exec_abc123_chart.png", "exec_def456_data.csv"],
            verification_hints=None,
            focus_areas=None)

        assert "<files_to_verify>" in result
        assert "exec_abc123_chart.png" in result
        assert "exec_def456_data.csv" in result

    def test_context_with_hints(self):
        """Test context includes verification hints."""
        from core.tools.self_critique import _build_verification_context

        result = _build_verification_context(
            user_request="Calculate sum",
            content="result = sum(numbers)",
            file_ids=None,
            verification_hints=["run_tests", "check_edge_cases"],
            focus_areas=None)

        assert "<suggested_verification_approaches>" in result
        assert "run_tests" in result
        assert "check_edge_cases" in result

    def test_context_with_focus_areas(self):
        """Test context includes focus areas."""
        from core.tools.self_critique import _build_verification_context

        result = _build_verification_context(
            user_request="Write algorithm",
            content="def algo(): pass",
            file_ids=None,
            verification_hints=None,
            focus_areas=["accuracy", "code_correctness", "edge_cases"])

        assert "<focus_areas>" in result
        assert "accuracy" in result
        assert "code_correctness" in result
        assert "edge_cases" in result

    def test_full_context(self):
        """Test context with all parameters."""
        from core.tools.self_critique import _build_verification_context

        result = _build_verification_context(
            user_request="Create report",
            content="Report content here",
            file_ids=["exec_report.pdf"],
            verification_hints=["visualize_data"],
            focus_areas=["completeness"])

        assert "<verification_task>" in result
        assert "<original_user_request>" in result
        assert "<content_to_verify>" in result
        assert "<files_to_verify>" in result
        assert "<suggested_verification_approaches>" in result
        assert "<focus_areas>" in result
        assert "<instructions>" in result


# =============================================================================
# Balance Check Tests
# =============================================================================


class TestBalanceCheck:
    """Tests for balance checking in execute_self_critique."""

    @pytest.mark.asyncio
    async def test_insufficient_balance_rejects(self, mock_bot, mock_session):
        """Test that insufficient balance returns SKIPPED verdict."""
        from core.tools.self_critique import execute_self_critique

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.balance_service.BalanceService") as mock_bs_class, \
             patch("db.repositories.user_repository.UserRepository"), \
             patch("db.repositories.balance_operation_repository.BalanceOperationRepository"):

            # Setup mocks
            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_balance_service = AsyncMock()
            mock_balance_service.get_balance = AsyncMock(
                return_value=Decimal("0.25"))
            mock_bs_class.return_value = mock_balance_service

            result = await execute_self_critique(user_request="Test request",
                                                 content="Test content",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345)

            assert result["error"] == "insufficient_balance"
            assert result["verdict"] == "SKIPPED"
            assert result["required_balance"] == 0.50
            assert result["current_balance"] == 0.25

    @pytest.mark.asyncio
    async def test_sufficient_balance_proceeds(self, mock_bot, mock_session):
        """Test that sufficient balance allows execution."""
        from core.tools.self_critique import execute_self_critique

        mock_response = create_mock_response(content_text=json.dumps({
            "verdict": "PASS",
            "alignment_score": 90,
            "issues": [],
            "recommendations": []
        }),
                                             input_tokens=1000,
                                             output_tokens=500)

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class:

            # Setup model config
            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            # Setup ServiceFactory
            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("1.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            # Setup Anthropic client
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)

            result = await execute_self_critique(user_request="Test request",
                                                 content="Test content",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client)

            assert result["verdict"] == "PASS"
            assert result["alignment_score"] == 90
            assert "error" not in result

    @pytest.mark.asyncio
    async def test_exact_threshold_balance_proceeds(self, mock_bot,
                                                    mock_session):
        """Test that balance exactly at threshold allows execution."""
        from core.tools.self_critique import execute_self_critique
        from core.tools.self_critique import MIN_BALANCE_FOR_CRITIQUE

        mock_response = create_mock_response(
            content_text=
            '{"verdict": "PASS", "alignment_score": 85, "issues": []}')

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            # Setup ServiceFactory
            mock_factory = Mock()
            # Exactly at threshold
            mock_factory.balance.get_balance = AsyncMock(
                return_value=MIN_BALANCE_FOR_CRITIQUE)
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)

            result = await execute_self_critique(user_request="Test",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client)

            # Should proceed (>= threshold)
            assert result["verdict"] == "PASS"


# =============================================================================
# Tool Definition Tests
# =============================================================================


class TestToolDefinition:
    """Tests for SELF_CRITIQUE_TOOL definition."""

    def test_tool_has_name(self):
        """Test tool has correct name."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        assert SELF_CRITIQUE_TOOL["name"] == "self_critique"

    def test_tool_has_description(self):
        """Test tool has description."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        assert "description" in SELF_CRITIQUE_TOOL
        assert "verification" in SELF_CRITIQUE_TOOL["description"].lower()
        # Tool description includes trigger phrases
        assert "when to use" in SELF_CRITIQUE_TOOL["description"].lower()

    def test_tool_has_input_schema(self):
        """Test tool has input schema."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        schema = SELF_CRITIQUE_TOOL["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        assert "user_request" in schema["required"]

    def test_tool_schema_properties(self):
        """Test tool schema has expected properties."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        props = SELF_CRITIQUE_TOOL["input_schema"]["properties"]

        assert "content" in props
        assert "file_ids" in props
        assert "user_request" in props
        assert "verification_hints" in props
        assert "focus_areas" in props


# =============================================================================
# Tool Config Tests
# =============================================================================


class TestToolConfig:
    """Tests for TOOL_CONFIG."""

    def test_tool_config_name(self):
        """Test TOOL_CONFIG has correct name."""
        from core.tools.self_critique import TOOL_CONFIG

        assert TOOL_CONFIG.name == "self_critique"

    def test_tool_config_emoji(self):
        """Test TOOL_CONFIG has emoji."""
        from core.tools.self_critique import TOOL_CONFIG

        assert TOOL_CONFIG.emoji == "🔍"

    def test_tool_config_needs_bot_session(self):
        """Test TOOL_CONFIG requires bot and session."""
        from core.tools.self_critique import TOOL_CONFIG

        assert TOOL_CONFIG.needs_bot_session is True

    def test_tool_config_has_executor(self):
        """Test TOOL_CONFIG has executor function."""
        from core.tools.self_critique import execute_self_critique
        from core.tools.self_critique import TOOL_CONFIG

        assert TOOL_CONFIG.executor == execute_self_critique

    def test_tool_registered_in_registry(self):
        """Test tool is registered in TOOLS registry."""
        from core.tools.registry import TOOLS

        assert "self_critique" in TOOLS
        assert TOOLS["self_critique"].name == "self_critique"


# =============================================================================
# Subagent Tool Routing Tests
# =============================================================================


class TestSubagentToolRouting:
    """Tests for _execute_subagent_tool function.

    These tests mock execute_tool from registry since _execute_subagent_tool
    now delegates to it (DRY refactoring).
    """

    @pytest.mark.asyncio
    async def test_route_execute_python(self, mock_bot, mock_session):
        """Test routing to execute_python tool via execute_tool."""
        from core.tools.self_critique import _execute_subagent_tool
        from core.tools.self_critique import CostTracker

        cost_tracker = CostTracker(model_id="test", user_id=123)

        # Mock execute_tool from registry (imported inside _execute_subagent_tool)
        with patch("core.tools.registry.execute_tool") as mock_exec:
            mock_exec.return_value = {"output": "Hello", "execution_time": 0.5}

            result = await _execute_subagent_tool(
                tool_name="execute_python",
                tool_input={"code": "print('Hello')"},
                tool_use_id="toolu_123",
                bot=mock_bot,
                session=mock_session,
                thread_id=1,
                cost_tracker=cost_tracker)

            mock_exec.assert_called_once_with(
                tool_name="execute_python",
                tool_input={"code": "print('Hello')"},
                bot=mock_bot,
                session=mock_session,
                thread_id=1,
            )
            assert result["type"] == "tool_result"
            assert result["tool_use_id"] == "toolu_123"
            assert "Hello" in result["content"]

    @pytest.mark.asyncio
    async def test_route_preview_file(self, mock_bot, mock_session):
        """Test routing to preview_file tool via execute_tool."""
        from core.tools.self_critique import _execute_subagent_tool
        from core.tools.self_critique import CostTracker

        cost_tracker = CostTracker(model_id="test", user_id=123)

        with patch("core.tools.registry.execute_tool") as mock_exec:
            mock_exec.return_value = {
                "success": "true",
                "content": "File content here"
            }

            result = await _execute_subagent_tool(
                tool_name="preview_file",
                tool_input={"file_id": "exec_abc123"},
                tool_use_id="toolu_456",
                bot=mock_bot,
                session=mock_session,
                thread_id=1,
                cost_tracker=cost_tracker)

            mock_exec.assert_called_once()
            assert result["type"] == "tool_result"
            assert "File content" in result["content"]

    @pytest.mark.asyncio
    async def test_route_analyze_image(self, mock_bot, mock_session):
        """Test routing to analyze_image tool and cost tracking."""
        from core.tools.self_critique import _execute_subagent_tool
        from core.tools.self_critique import CostTracker

        cost_tracker = CostTracker(model_id="test", user_id=123)

        with patch("core.tools.registry.execute_tool") as mock_exec:
            mock_exec.return_value = {
                "description": "A chart showing data",
                "cost_usd": 0.01
            }

            result = await _execute_subagent_tool(
                tool_name="analyze_image",
                tool_input={
                    "claude_file_id": "file_abc",
                    "question": "Is this correct?"
                },
                tool_use_id="toolu_789",
                bot=mock_bot,
                session=mock_session,
                thread_id=1,
                cost_tracker=cost_tracker)

            mock_exec.assert_called_once()
            assert result["type"] == "tool_result"
            # Check cost was tracked from result["cost_usd"]
            assert len(cost_tracker.tool_costs) == 1
            assert cost_tracker.tool_costs[0][0] == "analyze_image"

    @pytest.mark.asyncio
    async def test_route_unknown_tool(self, mock_bot, mock_session):
        """Test routing unknown tool returns error via execute_tool ValueError."""
        from core.tools.self_critique import _execute_subagent_tool
        from core.tools.self_critique import CostTracker

        cost_tracker = CostTracker(model_id="test", user_id=123)

        # execute_tool raises ValueError for unknown tools
        with patch("core.tools.registry.execute_tool") as mock_exec:
            mock_exec.side_effect = ValueError("Tool 'unknown_tool' not found")

            result = await _execute_subagent_tool(tool_name="unknown_tool",
                                                  tool_input={},
                                                  tool_use_id="toolu_xxx",
                                                  bot=mock_bot,
                                                  session=mock_session,
                                                  thread_id=1,
                                                  cost_tracker=cost_tracker)

            assert result["type"] == "tool_result"
            assert result["is_error"] is True
            assert "not found" in result["content"]

    @pytest.mark.asyncio
    async def test_tool_error_handling(self, mock_bot, mock_session):
        """Test error handling in tool execution."""
        from core.tools.self_critique import _execute_subagent_tool
        from core.tools.self_critique import CostTracker

        cost_tracker = CostTracker(model_id="test", user_id=123)

        with patch("core.tools.registry.execute_tool") as mock_exec:
            mock_exec.side_effect = Exception("Sandbox error")

            result = await _execute_subagent_tool(
                tool_name="execute_python",
                tool_input={"code": "bad code"},
                tool_use_id="toolu_err",
                bot=mock_bot,
                session=mock_session,
                thread_id=1,
                cost_tracker=cost_tracker)

            assert result["type"] == "tool_result"
            assert result["is_error"] is True
            assert "Sandbox error" in result["content"]


# =============================================================================
# JSON Parsing Tests
# =============================================================================


class TestJSONParsing:
    """Tests for JSON response parsing in execute_self_critique."""

    @pytest.mark.asyncio
    async def test_parse_clean_json(self, mock_bot, mock_session):
        """Test parsing clean JSON response."""
        from core.tools.self_critique import execute_self_critique

        mock_response = create_mock_response(content_text=json.dumps({
            "verdict": "NEEDS_IMPROVEMENT",
            "alignment_score": 65,
            "issues": [{
                "severity": "major",
                "description": "Missing edge case"
            }],
            "recommendations": ["Add null check"]
        }))

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("1.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)

            result = await execute_self_critique(user_request="Test",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client)

            assert result["verdict"] == "NEEDS_IMPROVEMENT"
            assert result["alignment_score"] == 65
            assert len(result["issues"]) == 1

    @pytest.mark.asyncio
    async def test_parse_json_in_code_block(self, mock_bot, mock_session):
        """Test parsing JSON wrapped in markdown code block."""
        from core.tools.self_critique import execute_self_critique

        mock_response = create_mock_response(content_text="""```json
{
    "verdict": "FAIL",
    "alignment_score": 30,
    "issues": [{"severity": "critical", "description": "Wrong output"}],
    "recommendations": ["Fix algorithm"]
}
```""")

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("1.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)

            result = await execute_self_critique(user_request="Test",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client)

            assert result["verdict"] == "FAIL"
            assert result["alignment_score"] == 30

    @pytest.mark.asyncio
    async def test_parse_invalid_json(self, mock_bot, mock_session):
        """Test handling of invalid JSON response."""
        from core.tools.self_critique import execute_self_critique

        mock_response = create_mock_response(
            content_text="This is not JSON at all")

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("1.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)

            result = await execute_self_critique(user_request="Test",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client)

            assert result["verdict"] == "ERROR"
            assert result["error"] == "invalid_response_format"
            assert "raw_response" in result


# =============================================================================
# Tool Loop Integration Tests
# =============================================================================


class TestToolLoopIntegration:
    """Integration tests for the full tool loop."""

    @pytest.mark.asyncio
    async def test_single_iteration_pass(self, mock_bot, mock_session):
        """Test successful single-iteration verification."""
        from core.tools.self_critique import execute_self_critique

        mock_response = create_mock_response(content_text=json.dumps({
            "verdict": "PASS",
            "alignment_score": 95,
            "confidence": 90,
            "issues": [],
            "verification_methods_used": ["code_review"],
            "recommendations": [],
            "summary": "Code looks correct."
        }),
                                             input_tokens=2000,
                                             output_tokens=800)

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("2.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)

            result = await execute_self_critique(
                user_request="Write a function to add two numbers",
                content="def add(a, b): return a + b",
                bot=mock_bot,
                session=mock_session,
                user_id=12345,
                anthropic_client=mock_client)

            assert result["verdict"] == "PASS"
            assert result["iterations"] == 1
            assert "cost_usd" in result
            assert "tokens_used" in result

    @pytest.mark.asyncio
    async def test_tool_use_then_response(self, mock_bot, mock_session):
        """Test verification with tool use followed by response."""
        from core.tools.self_critique import execute_self_critique

        # First response: tool use
        mock_response_1 = Mock()
        mock_response_1.stop_reason = "tool_use"
        mock_response_1.usage = create_mock_usage(1500, 300)

        mock_thinking = Mock()
        mock_thinking.type = "thinking"
        mock_thinking.thinking = "Let me test this code..."
        mock_thinking.model_dump = Mock(return_value={
            "type": "thinking",
            "thinking": "..."
        })

        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "toolu_test123"
        mock_tool_use.name = "execute_python"
        mock_tool_use.input = {"code": "assert add(2, 3) == 5"}
        mock_tool_use.model_dump = Mock(
            return_value={
                "type": "tool_use",
                "id": "toolu_test123",
                "name": "execute_python",
                "input": {
                    "code": "assert add(2, 3) == 5"
                }
            })

        mock_response_1.content = [mock_thinking, mock_tool_use]

        # Second response: final verdict
        mock_response_2 = create_mock_response(content_text=json.dumps({
            "verdict": "PASS",
            "alignment_score": 95,
            "issues": [],
            "verification_methods_used": ["ran_tests"],
            "recommendations": []
        }),
                                               input_tokens=2000,
                                               output_tokens=400)

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.tools.registry.execute_tool") as mock_exec_tool:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("2.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_response_1, mock_response_2])

            # Mock execute_tool from registry
            mock_exec_tool.return_value = {
                "output": "Test passed!",
                "execution_time": 0.1
            }

            result = await execute_self_critique(
                user_request="Write add function",
                content="def add(a, b): return a + b",
                bot=mock_bot,
                session=mock_session,
                user_id=12345,
                anthropic_client=mock_client)

            assert result["verdict"] == "PASS"
            assert result["iterations"] == 2
            # Verify execute_tool was called (via registry)
            mock_exec_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_parallel_tool_execution(self, mock_bot, mock_session):
        """Test that multiple tools are executed in parallel."""
        from core.tools.self_critique import execute_self_critique

        # Response with multiple tool uses
        mock_response_1 = Mock()
        mock_response_1.stop_reason = "tool_use"
        mock_response_1.usage = create_mock_usage(1500, 300)

        mock_tool_use_1 = Mock()
        mock_tool_use_1.type = "tool_use"
        mock_tool_use_1.id = "toolu_1"
        mock_tool_use_1.name = "execute_python"
        mock_tool_use_1.input = {"code": "test1"}
        mock_tool_use_1.model_dump = Mock(
            return_value={
                "type": "tool_use",
                "id": "toolu_1",
                "name": "execute_python",
                "input": {
                    "code": "test1"
                }
            })

        mock_tool_use_2 = Mock()
        mock_tool_use_2.type = "tool_use"
        mock_tool_use_2.id = "toolu_2"
        mock_tool_use_2.name = "preview_file"
        mock_tool_use_2.input = {"file_id": "exec_test"}
        mock_tool_use_2.model_dump = Mock(
            return_value={
                "type": "tool_use",
                "id": "toolu_2",
                "name": "preview_file",
                "input": {
                    "file_id": "exec_test"
                }
            })

        mock_response_1.content = [mock_tool_use_1, mock_tool_use_2]

        # Final response
        mock_response_2 = create_mock_response(
            content_text=
            '{"verdict": "PASS", "alignment_score": 90, "issues": []}',
            input_tokens=2500,
            output_tokens=500)

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.tools.registry.execute_tool") as mock_exec_tool:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("2.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_response_1, mock_response_2])

            # Mock execute_tool to return different results based on tool name
            def mock_tool_dispatch(tool_name, tool_input, **kwargs):
                if tool_name == "execute_python":
                    return {"output": "OK", "execution_time": 0.1}
                elif tool_name == "preview_file":
                    return {"content": "File OK"}
                return {"error": "Unknown tool"}

            mock_exec_tool.side_effect = mock_tool_dispatch

            result = await execute_self_critique(user_request="Test",
                                                 content="Content",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client)

            assert result["verdict"] == "PASS"
            # Both tools should have been called via execute_tool
            assert mock_exec_tool.call_count == 2


# =============================================================================
# Max Iterations Test
# =============================================================================


class TestMaxIterations:
    """Tests for max iterations limit."""

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self, mock_bot, mock_session):
        """Test that max iterations triggers final call without tools."""
        from core.tools.self_critique import execute_self_critique
        from core.tools.self_critique import MAX_SUBAGENT_ITERATIONS

        # Create a response that always requests tool use
        mock_tool_response = Mock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.usage = create_mock_usage(100, 50)

        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "toolu_loop"
        mock_tool_use.name = "execute_python"
        mock_tool_use.input = {"code": "pass"}
        mock_tool_use.model_dump = Mock(
            return_value={
                "type": "tool_use",
                "id": "toolu_loop",
                "name": "execute_python",
                "input": {
                    "code": "pass"
                }
            })
        mock_tool_response.content = [mock_tool_use]

        # Final response (after max iterations, called without tools)
        mock_final_response = create_mock_response(
            content_text='{"verdict": "PASS", "alignment_score": 75, '
            '"issues": [], "summary": "Limited verification"}',
            input_tokens=200,
            output_tokens=100)

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.tools.registry.execute_tool") as mock_exec_tool:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("5.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            # Return tool_use for MAX_SUBAGENT_ITERATIONS, then end_turn for final
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_tool_response] * MAX_SUBAGENT_ITERATIONS +
                [mock_final_response])

            mock_exec_tool.return_value = {
                "output": "OK",
                "execution_time": 0.01
            }

            result = await execute_self_critique(
                user_request="Infinite loop test",
                bot=mock_bot,
                session=mock_session,
                user_id=12345,
                anthropic_client=mock_client)

            # Now we get a verdict from final call, not ERROR
            assert result["verdict"] == "PASS"
            assert result.get("tool_limit_reached") is True
            # MAX_SUBAGENT_ITERATIONS + 1 final call
            assert result["iterations"] == MAX_SUBAGENT_ITERATIONS + 1
            # Should have been called MAX_SUBAGENT_ITERATIONS + 1 times
            assert mock_client.messages.create.call_count == MAX_SUBAGENT_ITERATIONS + 1


# =============================================================================
# Cancellation Tests
# =============================================================================


class TestCancellation:
    """Tests for cancellation via cancel_event."""

    @pytest.mark.asyncio
    async def test_cancel_event_stops_subagent(self, mock_bot, mock_session):
        """Test that setting cancel_event stops the subagent."""
        import asyncio

        from core.tools.self_critique import execute_self_critique

        # Create a cancel event that's already set
        cancel_event = asyncio.Event()
        cancel_event.set()

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("5.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            # Should never be called - cancelled before first iteration
            mock_client.messages.create = AsyncMock()

            result = await execute_self_critique(user_request="Test request",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client,
                                                 cancel_event=cancel_event)

            assert result["verdict"] == "CANCELLED"
            assert result["partial"] is True
            assert result["iterations"] == 0
            # API should not have been called
            mock_client.messages.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_mid_iteration(self, mock_bot, mock_session):
        """Test cancellation during tool loop."""
        import asyncio

        from core.tools.self_critique import execute_self_critique

        # Create cancel event that will be set after first API call
        cancel_event = asyncio.Event()

        # First response: tool_use
        mock_tool_response = Mock()
        mock_tool_response.stop_reason = "tool_use"
        mock_tool_response.usage = create_mock_usage(100, 50)

        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "toolu_1"
        mock_tool_use.name = "execute_python"
        mock_tool_use.input = {"code": "pass"}
        mock_tool_use.model_dump = Mock(
            return_value={
                "type": "tool_use",
                "id": "toolu_1",
                "name": "execute_python",
                "input": {
                    "code": "pass"
                }
            })
        mock_tool_response.content = [mock_tool_use]

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.tools.registry.execute_tool") as mock_exec_tool:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("5.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()

            async def api_side_effect(*args, **kwargs):
                # Set cancel after first call
                cancel_event.set()
                return mock_tool_response

            mock_client.messages.create = AsyncMock(side_effect=api_side_effect)

            mock_exec_tool.return_value = {
                "output": "OK",
                "execution_time": 0.01
            }

            result = await execute_self_critique(user_request="Test request",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client,
                                                 cancel_event=cancel_event)

            # Should have stopped after first iteration
            assert result["verdict"] == "CANCELLED"
            assert result["partial"] is True
            # API called once, then cancelled on second iteration
            assert mock_client.messages.create.call_count == 1


# =============================================================================
# Cost Charging Tests
# =============================================================================


class TestCostCharging:
    """Tests for cost calculation and user charging."""

    @pytest.mark.asyncio
    async def test_user_charged_after_verification(self, mock_bot,
                                                   mock_session):
        """Test that user is charged after successful verification."""
        from core.tools.self_critique import execute_self_critique

        mock_response = create_mock_response(
            content_text=
            '{"verdict": "PASS", "alignment_score": 90, "issues": []}',
            input_tokens=5000,
            output_tokens=1000)

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.cost_tracker.calculate_claude_cost") as mock_calc:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("2.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)

            mock_calc.return_value = Decimal("0.05")

            result = await execute_self_critique(user_request="Test",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client)

            # Verify charge_user was called
            mock_factory.balance.charge_user.assert_called_once()
            call_args = mock_factory.balance.charge_user.call_args

            assert call_args.kwargs["user_id"] == 12345
            assert call_args.kwargs["amount"] == Decimal("0.05")
            assert "self_critique" in call_args.kwargs["description"]

    @pytest.mark.asyncio
    async def test_cost_includes_tool_costs(self, mock_bot, mock_session):
        """Test that tool costs are included in total charge."""
        from core.tools.self_critique import execute_self_critique

        # First response: tool use
        mock_response_1 = Mock()
        mock_response_1.stop_reason = "tool_use"
        mock_response_1.usage = create_mock_usage(1000, 200)

        mock_tool_use = Mock()
        mock_tool_use.type = "tool_use"
        mock_tool_use.id = "toolu_cost"
        mock_tool_use.name = "execute_python"
        mock_tool_use.input = {"code": "print(1)"}
        mock_tool_use.model_dump = Mock(
            return_value={
                "type": "tool_use",
                "id": "toolu_cost",
                "name": "execute_python",
                "input": {
                    "code": "print(1)"
                }
            })
        mock_response_1.content = [mock_tool_use]

        # Final response
        mock_response_2 = create_mock_response(
            content_text=
            '{"verdict": "PASS", "alignment_score": 85, "issues": []}',
            input_tokens=1500,
            output_tokens=300)

        with patch("core.tools.self_critique.get_model") as mock_get_model, \
             patch("services.factory.ServiceFactory") as mock_factory_class, \
             patch("core.tools.registry.execute_tool") as mock_exec_tool, \
             patch("core.cost_tracker.calculate_claude_cost") as mock_calc, \
             patch("core.tools.self_critique.calculate_e2b_cost") as mock_e2b:

            mock_config = Mock()
            mock_config.model_id = "claude-opus-4-5-20251101"
            mock_get_model.return_value = mock_config

            mock_factory = Mock()
            mock_factory.balance.get_balance = AsyncMock(
                return_value=Decimal("2.00"))
            mock_factory.balance.charge_user = AsyncMock()
            mock_factory_class.return_value = mock_factory

            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                side_effect=[mock_response_1, mock_response_2])

            # Mock execute_tool to return result with execution_time
            mock_exec_tool.return_value = {"output": "1", "execution_time": 2.0}
            mock_e2b.return_value = Decimal("0.0001")  # 2 seconds * $0.00005

            # API costs
            mock_calc.return_value = Decimal("0.04")

            result = await execute_self_critique(user_request="Test",
                                                 bot=mock_bot,
                                                 session=mock_session,
                                                 user_id=12345,
                                                 anthropic_client=mock_client)

            # Total cost should be API cost + E2B cost
            mock_factory.balance.charge_user.assert_called_once()
            charged_amount = mock_factory.balance.charge_user.call_args.kwargs[
                "amount"]

            # 0.04 (API) + 0.0001 (E2B) = 0.0401
            assert charged_amount == Decimal("0.0401")


# =============================================================================
# Registry Integration Tests
# =============================================================================


class TestRegistryIntegration:
    """Tests for integration with tool registry."""

    def test_self_critique_in_tool_definitions(self):
        """Test self_critique appears in TOOL_DEFINITIONS."""
        from core.tools.registry import TOOL_DEFINITIONS

        tool_names = [t.get("name") for t in TOOL_DEFINITIONS]
        assert "self_critique" in tool_names

    def test_self_critique_in_tool_executors(self):
        """Test self_critique has executor registered."""
        from core.tools.registry import TOOL_EXECUTORS

        assert "self_critique" in TOOL_EXECUTORS
        assert callable(TOOL_EXECUTORS["self_critique"])

    @pytest.mark.asyncio
    async def test_execute_tool_routes_to_self_critique(self, mock_bot,
                                                        mock_session):
        """Test that execute_tool routes to self_critique correctly."""
        from core.tools.registry import execute_tool
        from core.tools.registry import TOOLS

        # Need to patch the executor on the TOOL_CONFIG object since it's
        # assigned at import time
        original_executor = TOOLS["self_critique"].executor
        mock_exec = AsyncMock(return_value={"verdict": "PASS"})

        try:
            TOOLS["self_critique"].executor = mock_exec

            # Need to provide user_id for self_critique
            result = await execute_tool(tool_name="self_critique",
                                        tool_input={"user_request": "Test"},
                                        bot=mock_bot,
                                        session=mock_session,
                                        thread_id=1,
                                        user_id=12345)

            mock_exec.assert_called_once()
            assert result["verdict"] == "PASS"
        finally:
            TOOLS["self_critique"].executor = original_executor

    @pytest.mark.asyncio
    async def test_execute_tool_without_user_id_raises(self, mock_bot,
                                                       mock_session):
        """Test that execute_tool raises error without user_id for self_critique."""
        from core.tools.registry import execute_tool

        with pytest.raises(ValueError, match="user_id"):
            await execute_tool(
                tool_name="self_critique",
                tool_input={"user_request": "Test"},
                bot=mock_bot,
                session=mock_session,
                thread_id=1,
                user_id=None  # Missing user_id
            )


# =============================================================================
# System Prompt Tests
# =============================================================================


class TestToolDefinitionIntegration:
    """Tests for self_critique tool definition content.

    Note: self_critique instructions were moved from system prompt to tool
    definition to reduce system prompt size and avoid duplication.
    """

    def test_tool_definition_has_trigger_phrases(self):
        """Test tool definition includes trigger phrases for when to use."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        desc = SELF_CRITIQUE_TOOL["description"].lower()
        assert "when to use" in desc
        assert "verify" in desc or "перепроверь" in desc

    def test_tool_definition_mentions_iteration_workflow(self):
        """Test tool definition includes iteration workflow."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        desc = SELF_CRITIQUE_TOOL["description"]
        # Workflow elements
        assert "PASS" in desc
        assert "fix" in desc.lower()
        assert "iteration" in desc.lower() or "5" in desc

    def test_tool_definition_mentions_cost(self):
        """Test tool definition includes cost information."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        desc = SELF_CRITIQUE_TOOL["description"]
        assert "$0.50" in desc or "0.50" in desc

    def test_tool_definition_mentions_opus(self):
        """Test tool definition mentions Opus model."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        desc = SELF_CRITIQUE_TOOL["description"]
        assert "Opus" in desc

    def test_tool_definition_has_explicit_trigger_requirement(self):
        """Test tool definition requires explicit user request."""
        from core.tools.self_critique import SELF_CRITIQUE_TOOL

        desc = SELF_CRITIQUE_TOOL["description"].lower()
        assert "only" in desc and "user" in desc
