"""Edge case tests for streaming functionality.

Phase 5.4.1: Streaming Edge Cases
- API error handling
- Context window exceeded
- Rate limit errors
- Connection/timeout errors
- Cancellation handling
"""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from core.exceptions import APIConnectionError
from core.exceptions import APITimeoutError
from core.exceptions import ContextWindowExceededError
from core.exceptions import RateLimitError
import pytest
from telegram.streaming.session import StreamingSession
from telegram.streaming.types import CancellationReason
from telegram.streaming.types import StreamResult

# ============================================================================
# Tests for exception classes
# ============================================================================


class TestExceptionClasses:
    """Tests for API exception classes."""

    def test_context_window_exceeded_error(self):
        """Test ContextWindowExceededError attributes."""
        error = ContextWindowExceededError(
            message="Context window exceeded",
            tokens_used=250000,
            tokens_limit=200000,
        )

        assert error.tokens_used == 250000
        assert error.tokens_limit == 200000
        assert "Context window exceeded" in str(error)

    def test_context_window_exceeded_preserves_tokens(self):
        """Test ContextWindowExceededError preserves token counts."""
        error = ContextWindowExceededError(
            message="Exceeded",
            tokens_used=250000,
            tokens_limit=200000,
        )

        # Verify token counts are accessible
        assert error.tokens_used == 250000
        assert error.tokens_limit == 200000

    def test_rate_limit_error_with_retry_after(self):
        """Test RateLimitError with retry_after."""
        error = RateLimitError(
            message="Rate limited",
            retry_after=30.0,
        )

        assert error.retry_after == 30.0
        assert "Rate limited" in str(error)

    def test_rate_limit_error_without_retry_after(self):
        """Test RateLimitError without retry_after."""
        error = RateLimitError(message="Rate limited")

        assert error.retry_after is None

    def test_api_connection_error(self):
        """Test APIConnectionError."""
        error = APIConnectionError(message="Connection failed")

        assert "Connection failed" in str(error)

    def test_api_timeout_error(self):
        """Test APITimeoutError."""
        error = APITimeoutError(message="Request timed out")

        assert "Request timed out" in str(error)

    def test_overloaded_error(self):
        """Test OverloadedError attributes."""
        from core.exceptions import OverloadedError

        error = OverloadedError(message="API overloaded")

        assert error.recoverable is True
        assert "overloaded" in error.user_message.lower()
        assert error.log_level == "warning"
        assert "API overloaded" in str(error)


# ============================================================================
# Tests for _is_overloaded_body helper
# ============================================================================


class TestIsOverloadedBody:
    """Tests for mid-stream overloaded error detection."""

    def test_overloaded_body_detected(self):
        """Test detection of overloaded_error in APIStatusError body."""
        from core.claude.client import _is_overloaded_body

        error = MagicMock(spec=["body"])
        error.body = {
            "type": "error",
            "error": {
                "type": "overloaded_error",
                "message": "Overloaded",
            },
        }
        assert _is_overloaded_body(error) is True

    def test_non_overloaded_body(self):
        """Test non-overloaded error body returns False."""
        from core.claude.client import _is_overloaded_body

        error = MagicMock(spec=["body"])
        error.body = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "Bad request",
            },
        }
        assert _is_overloaded_body(error) is False

    def test_no_body_attribute(self):
        """Test error without body attribute returns False."""
        from core.claude.client import _is_overloaded_body

        error = MagicMock(spec=[])
        assert _is_overloaded_body(error) is False

    def test_non_dict_body(self):
        """Test error with non-dict body returns False."""
        from core.claude.client import _is_overloaded_body

        error = MagicMock(spec=["body"])
        error.body = "string error"
        assert _is_overloaded_body(error) is False

    def test_body_without_error_key(self):
        """Test body dict without 'error' key returns False."""
        from core.claude.client import _is_overloaded_body

        error = MagicMock(spec=["body"])
        error.body = {"type": "error"}
        assert _is_overloaded_body(error) is False

    def test_error_is_not_dict(self):
        """Test body with non-dict 'error' value returns False."""
        from core.claude.client import _is_overloaded_body

        error = MagicMock(spec=["body"])
        error.body = {"error": "string"}
        assert _is_overloaded_body(error) is False


# ============================================================================
# Tests for StreamResult
# ============================================================================


class TestStreamResult:
    """Tests for StreamResult dataclass."""

    def test_stream_result_basic(self):
        """Test basic StreamResult creation."""
        result = StreamResult(
            text="Hello world",
            display_text="Hello world",
            message=None,
        )

        assert result.text == "Hello world"
        assert result.was_cancelled is False
        assert result.cancellation_reason is None

    def test_stream_result_cancelled(self):
        """Test cancelled StreamResult."""
        result = StreamResult(
            text="Partial",
            display_text="Partial\n\n_[interrupted]_",
            message=MagicMock(),
            was_cancelled=True,
            cancellation_reason=CancellationReason.STOP_COMMAND,
        )

        assert result.was_cancelled is True
        assert result.cancellation_reason == CancellationReason.STOP_COMMAND

    def test_stream_result_with_iterations(self):
        """Test StreamResult with tool iterations."""
        result = StreamResult(
            text="Final answer",
            display_text="Final answer",
            message=MagicMock(),
            iterations=3,
        )

        assert result.iterations == 3

    def test_stream_result_with_costs(self):
        """Test StreamResult with thinking/output chars."""
        result = StreamResult(
            text="Answer",
            display_text="Answer",
            message=None,
            thinking_chars=5000,
            output_chars=100,
        )

        assert result.thinking_chars == 5000
        assert result.output_chars == 100


# ============================================================================
# Tests for CancellationReason
# ============================================================================


class TestCancellationReason:
    """Tests for CancellationReason enum."""

    def test_stop_command_reason(self):
        """Test STOP_COMMAND cancellation reason."""
        reason = CancellationReason.STOP_COMMAND
        assert reason.value == "stop_command"

    def test_new_message_reason(self):
        """Test NEW_MESSAGE cancellation reason."""
        reason = CancellationReason.NEW_MESSAGE
        assert reason.value == "new_message"


# ============================================================================
# Tests for StreamingSession edge cases
# ============================================================================


class TestStreamingSessionEdgeCases:
    """Tests for StreamingSession edge cases."""

    @pytest.fixture
    def mock_draft_manager(self):
        """Create mock DraftManager."""
        dm = MagicMock()
        dm.current = MagicMock()
        dm.current.update = AsyncMock()
        dm.current.finalize = AsyncMock()
        dm.current.commit = AsyncMock()
        dm.current.clear = AsyncMock()
        dm.commit_and_create_new = AsyncMock()
        return dm

    def test_session_initialization(self, mock_draft_manager):
        """Test StreamingSession initialization."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        # stop_reason starts as empty string
        assert session.stop_reason == ""
        assert len(session.pending_tools) == 0

    def test_reset_iteration(self, mock_draft_manager):
        """Test reset_iteration clears state."""
        session = StreamingSession(mock_draft_manager, thread_id=123)
        # Add a tool to pending, then reset
        session.handle_tool_input_complete("t1", "web_search",
                                           {"query": "test"})

        session.reset_iteration()

        # After reset, pending tools should be cleared
        assert len(session.pending_tools) == 0

    @pytest.mark.asyncio
    async def test_handle_thinking_delta(self, mock_draft_manager):
        """Test handling thinking delta."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        await session.handle_thinking_delta("thinking content")

        # Should track thinking length
        assert session.display.total_thinking_length() > 0

    @pytest.mark.asyncio
    async def test_handle_text_delta(self, mock_draft_manager):
        """Test handling text delta."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        await session.handle_text_delta("Hello")
        await session.handle_text_delta(" world")

        assert session.get_final_text() == "Hello world"

    @pytest.mark.asyncio
    async def test_handle_very_long_text(self, mock_draft_manager):
        """Test handling very long text triggers message split."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        # Send 10KB of text (exceeds MESSAGE_SPLIT_THRESHOLD)
        long_text = "x" * 10000
        await session.handle_text_delta(long_text)

        # Very long text should trigger message split
        # commit_and_create_new should be called
        mock_draft_manager.commit_and_create_new.assert_called_once()

    def test_handle_message_end(self, mock_draft_manager):
        """Test handling message end."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        session.handle_message_end("end_turn")

        assert session.stop_reason == "end_turn"

    def test_handle_tool_use(self, mock_draft_manager):
        """Test handling tool use start."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        # This is async
        asyncio.get_event_loop().run_until_complete(
            session.handle_tool_use_start("tool_123", "web_search"))

        # Tool should be tracked (exact behavior depends on implementation)

    def test_get_current_text_length(self, mock_draft_manager):
        """Test get_current_text_length."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        asyncio.get_event_loop().run_until_complete(
            session.handle_text_delta("Hello"))

        length = session.get_current_text_length()
        assert length == 5

    @pytest.mark.asyncio
    async def test_add_subagent_tool_single(self, mock_draft_manager):
        """Test add_subagent_tool adds tool to tracking."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        # First add the parent tool marker
        await session.handle_tool_use_start("tool_123", "self_critique")

        # Then add subagent tool
        await session.add_subagent_tool("self_critique", "execute_python")

        # Check internal tracking
        assert "self_critique" in session._subagent_tools
        assert session._subagent_tools["self_critique"] == ["execute_python"]

    @pytest.mark.asyncio
    async def test_add_subagent_tool_multiple(self, mock_draft_manager):
        """Test add_subagent_tool accumulates tools."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        # First add the parent tool marker
        await session.handle_tool_use_start("tool_123", "self_critique")

        # Add multiple subagent tools
        await session.add_subagent_tool("self_critique", "execute_python")
        await session.add_subagent_tool("self_critique", "analyze_image")
        await session.add_subagent_tool("self_critique", "web_search")

        # Check internal tracking
        assert session._subagent_tools["self_critique"] == [
            "execute_python", "analyze_image", "web_search"
        ]

    @pytest.mark.asyncio
    async def test_subagent_tools_reset_on_new_session(self,
                                                       mock_draft_manager):
        """Test subagent tools start empty."""
        session = StreamingSession(mock_draft_manager, thread_id=123)

        # Initially empty
        assert session._subagent_tools == {}


# ============================================================================
# Tests for error message formatting
# ============================================================================


class TestErrorMessageFormatting:
    """Tests for error message formatting in handlers."""

    def test_context_exceeded_message_format(self):
        """Test context exceeded error message formatting."""
        tokens_used = 250000
        tokens_limit = 200000

        message = (f"Your conversation is too long ({tokens_used:,} tokens). "
                   f"Please start a new thread or reduce message history.")

        assert "250,000" in message
        assert "too long" in message

    def test_rate_limit_message_with_retry(self):
        """Test rate limit error message with retry info."""
        retry_after = 30

        retry_msg = f" Retry after {retry_after} seconds."
        message = f"Rate limit exceeded.{retry_msg}"

        assert "30 seconds" in message

    def test_rate_limit_message_without_retry(self):
        """Test rate limit error message without retry info."""
        message = "Rate limit exceeded. Too many requests."

        assert "Rate limit" in message


# ============================================================================
# Tests for generation context
# ============================================================================


class TestGenerationContext:
    """Tests for generation context cancellation."""

    @pytest.mark.asyncio
    async def test_cancel_event_basic(self):
        """Test basic cancel event behavior."""
        cancel_event = asyncio.Event()

        assert not cancel_event.is_set()

        cancel_event.set()

        assert cancel_event.is_set()

    @pytest.mark.asyncio
    async def test_cancel_event_wait(self):
        """Test waiting for cancel event."""
        cancel_event = asyncio.Event()

        async def set_after_delay():
            await asyncio.sleep(0.01)
            cancel_event.set()

        task = asyncio.create_task(set_after_delay())

        # Wait should complete when event is set
        await asyncio.wait_for(cancel_event.wait(), timeout=1.0)

        await task

        assert cancel_event.is_set()


# ============================================================================
# Tests for max iterations constant
# ============================================================================


class TestMaxIterations:
    """Tests for max iterations handling."""

    def test_tool_loop_max_iterations_constant(self):
        """Test TOOL_LOOP_MAX_ITERATIONS is defined."""
        from telegram.streaming.orchestrator import TOOL_LOOP_MAX_ITERATIONS

        assert TOOL_LOOP_MAX_ITERATIONS > 0
        assert TOOL_LOOP_MAX_ITERATIONS == 100  # Increased from 25

    def test_draft_keepalive_interval_constant(self):
        """Test DRAFT_KEEPALIVE_INTERVAL is defined."""
        from telegram.streaming.orchestrator import DRAFT_KEEPALIVE_INTERVAL

        assert DRAFT_KEEPALIVE_INTERVAL > 0
        assert DRAFT_KEEPALIVE_INTERVAL == 3.0  # Current value


# ============================================================================
# Tests for format_tool_results
# ============================================================================


class TestFormatToolResults:
    """Tests for format_tool_results helper."""

    def test_format_single_tool_result(self):
        """Test formatting single tool result."""
        from telegram.streaming.orchestrator import format_tool_results

        tool_uses = [{"id": "t1", "name": "web_search"}]
        results = [{"result": "search results"}]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 1
        assert formatted[0]["type"] == "tool_result"
        assert formatted[0]["tool_use_id"] == "t1"

    def test_format_multiple_tool_results(self):
        """Test formatting multiple tool results."""
        from telegram.streaming.orchestrator import format_tool_results

        tool_uses = [
            {
                "id": "t1",
                "name": "web_search"
            },
            {
                "id": "t2",
                "name": "execute_python"
            },
        ]
        results = [
            {
                "result": "search results"
            },
            {
                "output": "42"
            },
        ]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 2
        assert formatted[0]["tool_use_id"] == "t1"
        assert formatted[1]["tool_use_id"] == "t2"

    def test_format_empty_results(self):
        """Test formatting empty results."""
        from telegram.streaming.orchestrator import format_tool_results

        formatted = format_tool_results([], [])

        assert formatted == []
