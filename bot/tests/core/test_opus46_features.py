"""Tests for Claude Opus 4.6 features.

Covers adaptive thinking, effort via output_config, server-side compaction,
compaction event handling, and cost calculation with iterations.

NO __init__.py - use direct import:
    pytest tests/core/test_opus46_features.py
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

from config import ModelConfig
from core.models import LLMRequest
from core.models import Message
import pytest

# =============================================================================
# Fixtures
# =============================================================================


def _opus_config() -> ModelConfig:
    """Create Opus 4.6 model config."""
    return ModelConfig(
        provider="claude",
        model_id="claude-opus-4-6",
        alias="opus",
        display_name="Claude Opus 4.6",
        context_window=200_000,
        max_output=128_000,
        pricing_input=5.0,
        pricing_output=25.0,
        pricing_cache_write_5m=6.25,
        pricing_cache_write_1h=10.0,
        pricing_cache_read=0.50,
        latency_tier="moderate",
        capabilities={
            "extended_thinkinging": True,
            "interleaved_thinking": True,
            "adaptive_thinking": True,
            "effort": True,
            "effort_max": True,
            "compaction": True,
            "context_awareness": True,
            "vision": True,
            "streaming": True,
            "prompt_caching": True,
        },
    )


def _sonnet_config() -> ModelConfig:
    """Create Sonnet 4.5 model config (no adaptive/compaction)."""
    return ModelConfig(
        provider="claude",
        model_id="claude-sonnet-4-5-20250929",
        alias="sonnet",
        display_name="Claude Sonnet 4.5",
        context_window=200_000,
        max_output=64_000,
        pricing_input=3.0,
        pricing_output=15.0,
        pricing_cache_write_5m=3.75,
        pricing_cache_write_1h=6.0,
        pricing_cache_read=0.30,
        latency_tier="fast",
        capabilities={
            "extended_thinkinging": True,
            "interleaved_thinking": True,
            "effort": False,
            "context_awareness": True,
            "vision": True,
            "streaming": True,
            "prompt_caching": True,
        },
    )


def _make_request(**kwargs) -> LLMRequest:
    """Create a minimal LLMRequest."""
    defaults = {
        "messages": [Message(role="user", content="Hello")],
        "model": "claude:opus",
        "max_tokens": 4096,
    }
    defaults.update(kwargs)
    return LLMRequest(**defaults)


# =============================================================================
# Adaptive Thinking Tests
# =============================================================================


class TestAdaptiveThinking:
    """Tests for adaptive thinking (Opus 4.6)."""

    @pytest.mark.asyncio
    async def test_get_message_uses_adaptive_for_opus(self):
        """Opus 4.6 should use thinking.type=adaptive in get_message."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        mock_response = Mock()
        mock_response.content = [Mock(type="text", text="Hello")]
        mock_response.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_response.stop_reason = "end_turn"
        provider.client.messages.create = AsyncMock(return_value=mock_response)

        with patch("core.claude.client.get_model", return_value=_opus_config()):
            request = _make_request()
            await provider.get_message(request)

        call_args = provider.client.messages.create.call_args[1]
        assert call_args["thinking"] == {"type": "adaptive"}

    @pytest.mark.asyncio
    async def test_get_message_uses_manual_for_sonnet(self):
        """Sonnet should use manual thinking only with explicit budget."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        mock_response = Mock()
        mock_response.content = [Mock(type="text", text="Hello")]
        mock_response.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_response.stop_reason = "end_turn"
        provider.client.messages.create = AsyncMock(return_value=mock_response)

        with patch("core.claude.client.get_model",
                   return_value=_sonnet_config()):
            request = _make_request(model="claude:sonnet",
                                    thinking_budget=16000)
            await provider.get_message(request)

        call_args = provider.client.messages.create.call_args[1]
        assert call_args["thinking"] == {
            "type": "enabled",
            "budget_tokens": 16000
        }

    @pytest.mark.asyncio
    async def test_get_message_no_thinking_for_sonnet_without_budget(self):
        """Sonnet without budget should not have thinking params."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        mock_response = Mock()
        mock_response.content = [Mock(type="text", text="Hello")]
        mock_response.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_response.stop_reason = "end_turn"
        provider.client.messages.create = AsyncMock(return_value=mock_response)

        with patch("core.claude.client.get_model",
                   return_value=_sonnet_config()):
            request = _make_request(model="claude:sonnet")
            await provider.get_message(request)

        call_args = provider.client.messages.create.call_args[1]
        assert "thinking" not in call_args


# =============================================================================
# Effort via output_config Tests
# =============================================================================


class TestEffortOutputConfig:
    """Tests for effort parameter via output_config (GA)."""

    @pytest.mark.asyncio
    async def test_opus_uses_output_config_effort(self):
        """Opus should use output_config.effort instead of top-level effort."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        mock_response = Mock()
        mock_response.content = [Mock(type="text", text="Hello")]
        mock_response.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_response.stop_reason = "end_turn"
        provider.client.messages.create = AsyncMock(return_value=mock_response)

        with patch("core.claude.client.get_model", return_value=_opus_config()):
            request = _make_request()
            await provider.get_message(request)

        call_args = provider.client.messages.create.call_args[1]
        assert call_args["output_config"] == {"effort": "high"}
        assert "effort" not in call_args or call_args.get(
            "effort") is None  # No top-level effort

    @pytest.mark.asyncio
    async def test_sonnet_no_effort(self):
        """Sonnet should not have effort param (effort capability is False)."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        mock_response = Mock()
        mock_response.content = [Mock(type="text", text="Hello")]
        mock_response.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_response.stop_reason = "end_turn"
        provider.client.messages.create = AsyncMock(return_value=mock_response)

        with patch("core.claude.client.get_model",
                   return_value=_sonnet_config()):
            request = _make_request(model="claude:sonnet")
            await provider.get_message(request)

        call_args = provider.client.messages.create.call_args[1]
        assert "output_config" not in call_args


# =============================================================================
# Server-Side Compaction Tests
# =============================================================================


class TestCompactionParams:
    """Tests for server-side compaction params."""

    @pytest.mark.asyncio
    async def test_opus_includes_context_management(self):
        """Opus 4.6 should include context_management for compaction."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        mock_response = Mock()
        mock_response.content = [Mock(type="text", text="Hello")]
        mock_response.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_response.stop_reason = "end_turn"
        provider.client.messages.create = AsyncMock(return_value=mock_response)

        with patch("core.claude.client.get_model", return_value=_opus_config()):
            request = _make_request()
            await provider.get_message(request)

        call_args = provider.client.messages.create.call_args[1]
        assert "context_management" in call_args
        edits = call_args["context_management"]["edits"]
        assert len(edits) == 1
        assert edits[0]["type"] == "compact_20260112"
        assert edits[0]["trigger"]["type"] == "input_tokens"
        assert edits[0]["trigger"]["value"] == 100_000

    @pytest.mark.asyncio
    async def test_sonnet_no_context_management(self):
        """Sonnet should not include context_management."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        mock_response = Mock()
        mock_response.content = [Mock(type="text", text="Hello")]
        mock_response.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_response.stop_reason = "end_turn"
        provider.client.messages.create = AsyncMock(return_value=mock_response)

        with patch("core.claude.client.get_model",
                   return_value=_sonnet_config()):
            request = _make_request(model="claude:sonnet")
            await provider.get_message(request)

        call_args = provider.client.messages.create.call_args[1]
        assert "context_management" not in call_args


# =============================================================================
# Context Formatter Compaction Tests
# =============================================================================


class TestFormatterCompaction:
    """Tests for compaction in context formatter."""

    def test_assistant_message_with_compaction(self):
        """Assistant message with compaction_summary should return blocks."""
        from telegram.context.formatter import ContextFormatter

        formatter = ContextFormatter(chat_type="private")
        msg = MagicMock()
        msg.from_user_id = None  # assistant
        msg.text_content = "Here is my response."
        msg.caption = None
        msg.sender_display = None
        msg.forward_origin = None
        msg.reply_snippet = None
        msg.reply_sender_display = None
        msg.quote_data = None
        msg.edit_count = 0
        msg.compaction_summary = "Summary of prior conversation context."

        result = formatter.format_message(msg)

        assert result.role == "assistant"
        assert isinstance(result.content, list)
        assert len(result.content) == 2
        assert result.content[0] == {
            "type": "compaction",
            "content": "Summary of prior conversation context.",
        }
        assert result.content[1] == {
            "type": "text",
            "text": "Here is my response.",
        }

    def test_assistant_message_without_compaction(self):
        """Assistant message without compaction should return plain text."""
        from telegram.context.formatter import ContextFormatter

        formatter = ContextFormatter(chat_type="private")
        msg = MagicMock()
        msg.from_user_id = None
        msg.text_content = "Here is my response."
        msg.caption = None
        msg.sender_display = None
        msg.forward_origin = None
        msg.reply_snippet = None
        msg.reply_sender_display = None
        msg.quote_data = None
        msg.edit_count = 0
        msg.compaction_summary = None

        result = formatter.format_message(msg)

        assert result.role == "assistant"
        assert result.content == "Here is my response."

    def test_user_message_ignores_compaction(self):
        """User messages should never get compaction blocks."""
        from telegram.context.formatter import ContextFormatter

        formatter = ContextFormatter(chat_type="private")
        msg = MagicMock()
        msg.from_user_id = 123
        msg.text_content = "Hello"
        msg.caption = None
        msg.sender_display = None
        msg.forward_origin = None
        msg.reply_snippet = None
        msg.reply_sender_display = None
        msg.quote_data = None
        msg.edit_count = 0
        msg.compaction_summary = "This should be ignored"

        result = formatter.format_message(msg)

        assert result.role == "user"
        # User messages never get compaction blocks
        assert result.content == "Hello"


# =============================================================================
# Cost Calculation with Iterations Tests
# =============================================================================


class TestCostWithIterations:
    """Tests for calculate_claude_cost_with_iterations."""

    def test_with_iterations(self):
        """Should sum tokens across all iterations."""
        from core.pricing import calculate_claude_cost_with_iterations

        # Mock iterations (two compaction rounds)
        iter1 = Mock(
            input_tokens=50000,
            output_tokens=5000,
            cache_read_input_tokens=1000,
            cache_creation_input_tokens=2000,
            thinking_tokens=3000,
        )
        iter2 = Mock(
            input_tokens=30000,
            output_tokens=4000,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=1000,
            thinking_tokens=2000,
        )

        usage = Mock()
        usage.iterations = [iter1, iter2]
        usage.input_tokens = 80000  # Should be ignored in favor of iterations
        usage.output_tokens = 9000

        result = calculate_claude_cost_with_iterations(
            usage=usage,
            model_id="claude-opus-4-6",
        )

        # Should use iteration totals: 80K in, 9K out, 1.5K cache_read,
        # 3K cache_create, 5K thinking
        assert result > Decimal("0")

    def test_without_iterations(self):
        """Should use standard usage fields when no iterations."""
        from core.pricing import calculate_claude_cost_with_iterations

        usage = Mock(spec=[])
        usage.input_tokens = 10000
        usage.output_tokens = 2000
        usage.cache_read_input_tokens = 500
        usage.cache_creation_input_tokens = 200
        usage.thinking_tokens = 100

        result = calculate_claude_cost_with_iterations(
            usage=usage,
            model_id="claude-opus-4-6",
        )

        assert result > Decimal("0")

    def test_empty_iterations_list(self):
        """Empty iterations list should use standard fields."""
        from core.pricing import calculate_claude_cost_with_iterations

        usage = Mock()
        usage.iterations = []  # Empty, falsy
        usage.input_tokens = 10000
        usage.output_tokens = 2000
        usage.cache_read_input_tokens = 500
        usage.cache_creation_input_tokens = 200
        usage.thinking_tokens = 100

        result = calculate_claude_cost_with_iterations(
            usage=usage,
            model_id="claude-opus-4-6",
        )

        assert result > Decimal("0")


# =============================================================================
# Extended Thinking Tool Adaptive Tests
# =============================================================================


class TestExtendedThinkingAdaptive:
    """Tests for adaptive thinking in extended_thinking tool."""

    @pytest.mark.asyncio
    async def test_adaptive_thinking_for_opus(self):
        """Extended thinking should use adaptive for Opus 4.6."""
        from core.tools.extended_thinking import \
            execute_extended_thinking_stream

        mock_client = AsyncMock()

        # Mock the stream context manager
        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        # Mock the async iterator (no events)
        mock_stream.__aiter__ = Mock(return_value=iter([]))

        # Mock get_final_message
        mock_final = Mock()
        mock_final.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            thinking_tokens=200,
        )
        mock_stream.get_final_message = AsyncMock(return_value=mock_final)

        mock_client.messages.stream = Mock(return_value=mock_stream)

        with patch("core.tools.extended_thinking.get_model",
                   return_value=_opus_config()):
            events = []
            async for event in execute_extended_thinking_stream(
                    problem="Test problem",
                    model_id="claude:opus",
                    anthropic_client=mock_client,
            ):
                events.append(event)

        # Verify API was called with adaptive thinking
        call_args = mock_client.messages.stream.call_args[1]
        assert call_args["thinking"] == {"type": "adaptive"}
        assert call_args["output_config"] == {"effort": "max"}

    @pytest.mark.asyncio
    async def test_manual_thinking_for_sonnet(self):
        """Extended thinking should use manual budget for Sonnet."""
        from core.tools.extended_thinking import \
            execute_extended_thinking_stream
        from core.tools.extended_thinking import THINKING_BUDGET_TOKENS

        mock_client = AsyncMock()

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.__aiter__ = Mock(return_value=iter([]))

        mock_final = Mock()
        mock_final.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            thinking_tokens=200,
        )
        mock_stream.get_final_message = AsyncMock(return_value=mock_final)

        mock_client.messages.stream = Mock(return_value=mock_stream)

        with patch("core.tools.extended_thinking.get_model",
                   return_value=_sonnet_config()):
            events = []
            async for event in execute_extended_thinking_stream(
                    problem="Test problem",
                    model_id="claude:sonnet",
                    anthropic_client=mock_client,
            ):
                events.append(event)

        call_args = mock_client.messages.stream.call_args[1]
        assert call_args["thinking"] == {
            "type": "enabled",
            "budget_tokens": THINKING_BUDGET_TOKENS,
        }
        assert "output_config" not in call_args


# =============================================================================
# Subagent Adaptive Thinking Tests
# =============================================================================


class TestSubagentAdaptiveThinking:
    """Tests for adaptive thinking in subagent _call_api."""

    @pytest.mark.asyncio
    async def test_adaptive_for_opus_model(self):
        """Subagent should use adaptive thinking for Opus 4.6."""
        from core.subagent.base import BaseSubagent
        from core.subagent.base import SubagentConfig

        class TestSubagent(BaseSubagent):

            async def _execute_tool(self, tool_name, tool_input, tool_use_id):
                return {"result": "ok"}

            def _parse_result(self, response_text):
                return {"verdict": "PASS"}

        config = SubagentConfig(
            model_id="claude-opus-4-6",
            system_prompt="Test",
            tools=[],
        )
        client = AsyncMock()
        mock_response = Mock()
        mock_response.stop_reason = "end_turn"
        client.messages.create = AsyncMock(return_value=mock_response)

        subagent = TestSubagent(config, client, Mock(), Mock(), user_id=123)

        with patch("config.get_model_by_provider_id",
                   return_value=_opus_config()):
            await subagent._call_api([{  # pylint: disable=protected-access
                "role": "user",
                "content": "test"
            }])

        call_args = client.messages.create.call_args[1]
        assert call_args["thinking"] == {"type": "adaptive"}
        assert call_args["output_config"] == {"effort": "high"}

    @pytest.mark.asyncio
    async def test_manual_for_unknown_model(self):
        """Subagent should fallback to manual thinking for unknown models."""
        from core.subagent.base import BaseSubagent
        from core.subagent.base import SubagentConfig

        class TestSubagent(BaseSubagent):

            async def _execute_tool(self, tool_name, tool_input, tool_use_id):
                return {"result": "ok"}

            def _parse_result(self, response_text):
                return {"verdict": "PASS"}

        config = SubagentConfig(
            model_id="test-unknown",
            system_prompt="Test",
            tools=[],
        )
        client = AsyncMock()
        mock_response = Mock()
        mock_response.stop_reason = "end_turn"
        client.messages.create = AsyncMock(return_value=mock_response)

        subagent = TestSubagent(config, client, Mock(), Mock(), user_id=123)

        with patch("config.get_model_by_provider_id",
                   side_effect=ValueError("not found")):
            await subagent._call_api([{  # pylint: disable=protected-access
                "role": "user",
                "content": "test"
            }])

        call_args = client.messages.create.call_args[1]
        assert call_args["thinking"]["type"] == "enabled"
        assert "budget_tokens" in call_args["thinking"]
        assert "output_config" not in call_args


# =============================================================================
# Model Registry Tests
# =============================================================================


class TestModelRegistryOpus46:
    """Tests for Opus 4.6 model configuration."""

    def test_opus_model_id(self):
        """Opus should use claude-opus-4-6 model ID."""
        from config import get_model
        model = get_model("claude:opus")
        assert model.model_id == "claude-opus-4-6"

    def test_opus_display_name(self):
        """Opus should display as 'Claude Opus 4.6'."""
        from config import get_model
        model = get_model("claude:opus")
        assert model.display_name == "Claude Opus 4.6"

    def test_opus_max_output(self):
        """Opus should support 128K max output."""
        from config import get_model
        model = get_model("claude:opus")
        assert model.max_output == 128_000

    def test_opus_has_adaptive_thinking(self):
        """Opus should support adaptive thinking."""
        from config import get_model
        model = get_model("claude:opus")
        assert model.has_capability("adaptive_thinking")

    def test_opus_has_compaction(self):
        """Opus should support compaction."""
        from config import get_model
        model = get_model("claude:opus")
        assert model.has_capability("compaction")

    def test_opus_has_effort_max(self):
        """Opus should support effort_max."""
        from config import get_model
        model = get_model("claude:opus")
        assert model.has_capability("effort_max")

    def test_sonnet_no_adaptive(self):
        """Sonnet should NOT support adaptive thinking."""
        from config import get_model
        model = get_model("claude:sonnet")
        assert not model.has_capability("adaptive_thinking")

    def test_sonnet_no_compaction(self):
        """Sonnet should NOT support compaction."""
        from config import get_model
        model = get_model("claude:sonnet")
        assert not model.has_capability("compaction")

    def test_haiku_no_adaptive(self):
        """Haiku should NOT support adaptive thinking."""
        from config import get_model
        model = get_model("claude:haiku")
        assert not model.has_capability("adaptive_thinking")


# =============================================================================
# Compaction Event Handling Tests
# =============================================================================


class TestCompactionEventHandling:
    """Tests for compaction event handling in stream_events."""

    @pytest.mark.asyncio
    async def test_compaction_stored_after_stream(self):
        """Compaction content should be stored in last_compaction."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        # Create mock events simulating compaction
        compaction_start = Mock()
        compaction_start.type = "content_block_start"
        compaction_start.content_block = Mock(type="compaction")

        compaction_delta = Mock()
        compaction_delta.type = "content_block_delta"
        compaction_delta.delta = Mock()
        compaction_delta.delta.type = "compaction_delta"
        compaction_delta.delta.content = "Summary of prior context"
        # Make sure hasattr checks for text/thinking/partial_json are False
        del compaction_delta.delta.text
        del compaction_delta.delta.thinking
        del compaction_delta.delta.partial_json

        compaction_stop = Mock()
        compaction_stop.type = "content_block_stop"

        text_start = Mock()
        text_start.type = "content_block_start"
        text_start.content_block = Mock(type="text")

        text_delta = Mock()
        text_delta.type = "content_block_delta"
        text_delta.delta = Mock()
        text_delta.delta.text = "Hello"
        del text_delta.delta.thinking
        del text_delta.delta.partial_json

        text_stop = Mock()
        text_stop.type = "content_block_stop"

        message_delta = Mock()
        message_delta.type = "message_delta"
        message_delta.delta = Mock(stop_reason="end_turn")

        events = [
            compaction_start, compaction_delta, compaction_stop, text_start,
            text_delta, text_stop, message_delta
        ]

        # Create mock stream
        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        async def mock_iter():
            for e in events:
                yield e

        mock_stream.__aiter__ = lambda self: mock_iter()

        mock_final = Mock()
        mock_final.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_final.stop_reason = "end_turn"
        mock_stream.get_final_message = AsyncMock(return_value=mock_final)

        provider.client.messages.stream = Mock(return_value=mock_stream)

        with patch("core.claude.client.get_model", return_value=_opus_config()):
            request = _make_request()
            stream_events = []
            async for event in provider.stream_events(request):
                stream_events.append(event)

        assert provider.last_compaction == "Summary of prior context"

    @pytest.mark.asyncio
    async def test_no_compaction_when_not_triggered(self):
        """last_compaction should be None when no compaction event fires."""
        from core.claude.client import ClaudeProvider

        provider = ClaudeProvider.__new__(ClaudeProvider)
        provider.client = AsyncMock()
        provider.last_usage = None
        provider.last_message = None
        provider.last_thinking = None
        provider.last_compaction = None

        # Simple text-only stream (no compaction)
        text_start = Mock()
        text_start.type = "content_block_start"
        text_start.content_block = Mock(type="text")

        text_delta = Mock()
        text_delta.type = "content_block_delta"
        text_delta.delta = Mock()
        text_delta.delta.text = "Hello"
        del text_delta.delta.thinking
        del text_delta.delta.partial_json

        text_stop = Mock()
        text_stop.type = "content_block_stop"

        message_delta = Mock()
        message_delta.type = "message_delta"
        message_delta.delta = Mock(stop_reason="end_turn")

        events = [text_start, text_delta, text_stop, message_delta]

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        async def mock_iter():
            for e in events:
                yield e

        mock_stream.__aiter__ = lambda self: mock_iter()

        mock_final = Mock()
        mock_final.usage = Mock(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
            server_tool_use=None,
        )
        mock_final.stop_reason = "end_turn"
        mock_stream.get_final_message = AsyncMock(return_value=mock_final)

        provider.client.messages.stream = Mock(return_value=mock_stream)

        with patch("core.claude.client.get_model", return_value=_opus_config()):
            request = _make_request()
            async for _ in provider.stream_events(request):
                pass

        assert provider.last_compaction is None


# =============================================================================
# LLMRequest Max Tokens Validation Tests
# =============================================================================


class TestLLMRequestMaxTokens:
    """Tests for LLMRequest max_tokens upper bound."""

    def test_128k_max_tokens_allowed(self):
        """128K max_tokens should be valid for Opus 4.6."""
        request = _make_request(max_tokens=128000)
        assert request.max_tokens == 128000

    def test_over_128k_rejected(self):
        """Over 128K max_tokens should be rejected."""
        with pytest.raises(Exception):
            _make_request(max_tokens=128001)
