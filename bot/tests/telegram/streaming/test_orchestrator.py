"""Tests for streaming orchestrator module.

Comprehensive tests for StreamingOrchestrator which coordinates:
- Streaming from Claude API
- Tool execution
- File processing
- Cost tracking
- Cancellation handling
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.streaming.orchestrator import format_tool_results
from telegram.streaming.orchestrator import get_tool_system_message
from telegram.streaming.orchestrator import StreamingOrchestrator
from telegram.streaming.orchestrator import TOOL_LOOP_MAX_ITERATIONS
from telegram.streaming.tool_executor import BatchExecutionResult
from telegram.streaming.tool_executor import ToolExecutionResult
from telegram.streaming.types import CancellationReason
from telegram.streaming.types import StreamResult
from telegram.streaming.types import ToolCall

# ============================================================================
# Helper classes for mocking
# ============================================================================


@dataclass
class MockStreamEvent:  # pylint: disable=too-many-instance-attributes
    """Mock stream event from Claude API."""

    type: str
    content: str = ""
    tool_id: str | None = None
    tool_name: str | None = None
    tool_input: dict | None = None
    stop_reason: str | None = None
    final_message: Any = None
    is_server_tool: bool = False


@dataclass
class MockMessage:
    """Mock message for captured_message."""

    content: list


@dataclass
class MockContentBlock:
    """Mock content block with model_dump method."""

    type: str
    text: str = ""

    def model_dump(self) -> dict:
        """Return dict representation."""
        return {"type": self.type, "text": self.text}


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_request():
    """Create mock LLMRequest."""
    request = MagicMock()
    request.messages = [
        MagicMock(role="user", content="Hello"),
    ]
    request.system_prompt = "You are a helpful assistant"
    request.model = "claude-3-sonnet"
    request.max_tokens = 4096
    request.temperature = 1.0
    request.tools = []
    return request


@pytest.fixture
def mock_telegram_message():
    """Create mock Telegram message."""
    message = MagicMock()
    message.bot = MagicMock()
    message.message_id = 123
    message.message_thread_id = None
    return message


@pytest.fixture
def mock_session():
    """Create mock database session."""
    return MagicMock()


@pytest.fixture
def mock_user_file_repo():
    """Create mock UserFileRepository."""
    return MagicMock()


@pytest.fixture
def mock_draft_manager():
    """Create mock DraftManager context manager."""
    dm = MagicMock()
    dm.current = MagicMock()
    dm.current.finalize = AsyncMock(return_value=MagicMock())
    dm.current.update = AsyncMock()
    dm.current.clear = AsyncMock()
    dm.commit_and_create_new = AsyncMock()
    return dm


@pytest.fixture
def mock_cancel_event():
    """Create mock cancellation event."""
    event = MagicMock()
    event.is_set = MagicMock(return_value=False)
    return event


@pytest.fixture
def mock_action_manager():
    """Create mock ActionManager."""
    manager = MagicMock()
    manager.push_scope = AsyncMock(return_value="scope_123")
    manager.pop_scope = AsyncMock()
    return manager


@pytest.fixture
def mock_claude_provider():
    """Create mock Claude provider."""
    provider = MagicMock()
    provider.stream_events = MagicMock()
    return provider


# ============================================================================
# Tests for format_tool_results
# ============================================================================


class TestFormatToolResults:
    """Tests for format_tool_results helper function."""

    def test_single_tool_result(self):
        """Should format single tool result correctly."""
        tool_uses = [{"id": "tool_123", "name": "generate_image"}]
        results = [{"url": "https://example.com/image.png"}]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 1
        assert formatted[0]["type"] == "tool_result"
        assert formatted[0]["tool_use_id"] == "tool_123"
        assert "url" in formatted[0]["content"]

    def test_multiple_tool_results(self):
        """Should format multiple tool results in order."""
        tool_uses = [
            {
                "id": "tool_1",
                "name": "web_search"
            },
            {
                "id": "tool_2",
                "name": "execute_python"
            },
            {
                "id": "tool_3",
                "name": "generate_image"
            },
        ]
        results = [
            {
                "results": ["search result 1"]
            },
            {
                "output": "Hello, World!"
            },
            {
                "url": "https://example.com/image.png"
            },
        ]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 3
        assert formatted[0]["tool_use_id"] == "tool_1"
        assert formatted[1]["tool_use_id"] == "tool_2"
        assert formatted[2]["tool_use_id"] == "tool_3"

    def test_empty_result(self):
        """Should handle empty result dict."""
        tool_uses = [{"id": "tool_123", "name": "test_tool"}]
        results = [{}]

        formatted = format_tool_results(tool_uses, results)

        assert formatted[0]["content"] == "{}"

    def test_result_converted_to_string(self):
        """Should convert result dict to string."""
        tool_uses = [{"id": "tool_123", "name": "test_tool"}]
        results = [{"key": "value", "number": 42}]

        formatted = format_tool_results(tool_uses, results)

        assert isinstance(formatted[0]["content"], str)


# ============================================================================
# Tests for get_tool_system_message
# ============================================================================


class TestGetToolSystemMessage:
    """Tests for get_tool_system_message helper function."""

    def test_returns_none_for_unknown_tool(self):
        """Should return None for tools without system messages."""
        with patch(
                "core.tools.registry.get_tool_system_message",
                return_value=None,
        ):
            result = get_tool_system_message(
                "unknown_tool",
                {"input": "value"},
                {"output": "result"},
            )
            assert result is None

    def test_returns_message_for_tool_with_system_message(self):
        """Should return system message when tool provides one."""
        expected_msg = "[✅ 2 files delivered]"
        with patch(
                "core.tools.registry.get_tool_system_message",
                return_value=expected_msg,
        ):
            result = get_tool_system_message(
                "deliver_file",
                {"file_ids": ["f1", "f2"]},
                {"delivered": 2},
            )
            assert result == expected_msg


# ============================================================================
# Tests for StreamingOrchestrator
# ============================================================================


class TestStreamingOrchestratorInit:
    """Tests for StreamingOrchestrator initialization."""

    def test_init_with_required_params(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
    ):
        """Should initialize with required parameters."""
        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
        )

        assert orchestrator._request == mock_llm_request
        assert orchestrator._first_message == mock_telegram_message
        assert orchestrator._thread_id == 1
        assert orchestrator._chat_id == 123
        assert orchestrator._user_id == 456
        assert orchestrator._telegram_thread_id is None

    def test_init_with_optional_params(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
    ):
        """Should initialize with optional parameters."""
        continuation = [{"role": "user", "content": "continue"}]

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            telegram_thread_id=789,
            continuation_conversation=continuation,
            claude_provider=mock_claude_provider,
        )

        assert orchestrator._telegram_thread_id == 789
        assert orchestrator._continuation_conversation == continuation
        assert orchestrator._claude_provider == mock_claude_provider


class TestStreamingOrchestratorStream:
    """Tests for StreamingOrchestrator.stream() method."""

    @pytest.mark.asyncio
    async def test_stream_simple_end_turn(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should handle simple stream with end_turn."""
        # Setup mock events
        events = [
            MockStreamEvent(type="text_delta", content="Hello, "),
            MockStreamEvent(type="text_delta", content="world!"),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="message_end", stop_reason="end_turn"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        async def mock_stream_events(request):
            for event in events:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
        ):
            # Setup context managers
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            result = await orchestrator.stream()

        assert isinstance(result, StreamResult)
        assert "Hello, world!" in result.text
        assert result.was_cancelled is False
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_stream_with_cancellation(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_action_manager,
    ):
        """Should handle user cancellation via /stop command."""
        # Setup mock events - many events to ensure cancellation can trigger
        events = [
            MockStreamEvent(type="text_delta", content="Starting to "),
            MockStreamEvent(type="text_delta", content="respond "),
            MockStreamEvent(type="text_delta", content="with "),
            MockStreamEvent(type="text_delta", content="more "),
            MockStreamEvent(type="text_delta", content="content..."),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="message_end", stop_reason="end_turn"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        # Track which event we're on
        event_index = 0
        cancel_triggered = False

        async def mock_stream_events(request):
            nonlocal event_index, cancel_triggered
            for event in events:
                event_index += 1
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        # Create cancel event that triggers after 3rd event check
        cancel_event = MagicMock()
        check_count = 0

        def is_set_side_effect():
            nonlocal check_count
            check_count += 1
            # Trigger cancellation after a few checks (events)
            return check_count > 3

        cancel_event.is_set = MagicMock(side_effect=is_set_side_effect)

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            result = await orchestrator.stream()

        assert result.was_cancelled is True
        assert result.cancellation_reason == CancellationReason.STOP_COMMAND
        assert "_\\[interrupted\\]_" in result.display_text

    @pytest.mark.asyncio
    async def test_stream_with_thinking(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should handle thinking blocks in stream."""
        events = [
            MockStreamEvent(type="thinking_delta", content="Let me think..."),
            MockStreamEvent(type="thinking_delta", content=" about this."),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="text_delta", content="The answer is 42."),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="message_end", stop_reason="end_turn"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        async def mock_stream_events(request):
            for event in events:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            result = await orchestrator.stream()

        assert "42" in result.text
        assert result.was_cancelled is False

    @pytest.mark.asyncio
    async def test_stream_with_tool_execution(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should handle tool execution and continuation."""
        # First iteration: tool call
        first_events = [
            MockStreamEvent(type="text_delta", content="I'll search for that."),
            MockStreamEvent(
                type="tool_use",
                tool_id="tool_123",
                tool_name="web_search",
            ),
            MockStreamEvent(
                type="block_end",
                tool_id="tool_123",
                tool_name="web_search",
                tool_input={"query": "test query"},
            ),
            MockStreamEvent(type="message_end", stop_reason="tool_use"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(
                    content=[MockContentBlock(type="text", text="I'll search")
                            ]),
            ),
        ]

        # Second iteration: final response
        second_events = [
            MockStreamEvent(type="text_delta", content="Based on the search, "),
            MockStreamEvent(type="text_delta", content="the answer is X."),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="message_end", stop_reason="end_turn"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        iteration = 0

        async def mock_stream_events(request):
            nonlocal iteration
            events = first_events if iteration == 0 else second_events
            iteration += 1
            for event in events:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        # Mock tool executor
        mock_tool_result = ToolExecutionResult(
            tool=ToolCall(tool_id="tool_123",
                          name="web_search",
                          input={"query": "test"}),
            result={"results": ["Search result 1"]},
            raw_result={"results": ["Search result 1"]},
            is_error=False,
            duration=0.5,
            cost_usd=Decimal("0.001"),
        )
        mock_batch_result = BatchExecutionResult(
            results=[mock_tool_result],
            force_turn_break=False,
        )

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
                patch.object(
                    orchestrator,
                    "_get_tool_executor",
                ) as mock_get_executor,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            mock_executor = MagicMock()
            mock_executor.execute_batch = AsyncMock(
                return_value=mock_batch_result)
            mock_get_executor.return_value = mock_executor

            result = await orchestrator.stream()

        assert result.was_cancelled is False
        assert result.iterations == 2
        assert "answer is X" in result.text

    @pytest.mark.asyncio
    async def test_stream_with_force_turn_break(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should handle tool requesting turn break."""
        events = [
            MockStreamEvent(type="text_delta", content="Delivering files..."),
            MockStreamEvent(
                type="tool_use",
                tool_id="tool_123",
                tool_name="deliver_file",
            ),
            MockStreamEvent(
                type="block_end",
                tool_id="tool_123",
                tool_name="deliver_file",
                tool_input={"file_ids": ["f1"]},
            ),
            MockStreamEvent(type="message_end", stop_reason="tool_use"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(
                    content=[MockContentBlock(type="text", text="Delivering")]),
            ),
        ]

        async def mock_stream_events(request):
            for event in events:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        # Mock tool executor with turn break
        mock_tool_result = ToolExecutionResult(
            tool=ToolCall(
                tool_id="tool_123",
                name="deliver_file",
                input={"file_ids": ["f1"]},
            ),
            result={"delivered": 1},
            raw_result={
                "delivered": 1,
                "_force_turn_break": True
            },
            is_error=False,
            force_turn_break=True,
        )
        mock_batch_result = BatchExecutionResult(
            results=[mock_tool_result],
            force_turn_break=True,
            turn_break_tool="deliver_file",
        )

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
                patch.object(
                    orchestrator,
                    "_get_tool_executor",
                ) as mock_get_executor,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            mock_executor = MagicMock()
            mock_executor.execute_batch = AsyncMock(
                return_value=mock_batch_result)
            mock_get_executor.return_value = mock_executor

            result = await orchestrator.stream()

        assert result.needs_continuation is True
        assert result.conversation is not None
        assert result.was_cancelled is False

    @pytest.mark.asyncio
    async def test_stream_pause_turn(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should handle pause_turn stop reason same as end_turn."""
        events = [
            MockStreamEvent(type="text_delta", content="Partial response."),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="message_end", stop_reason="pause_turn"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        async def mock_stream_events(request):
            for event in events:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            result = await orchestrator.stream()

        assert result.was_cancelled is False
        assert "Partial response" in result.text

    @pytest.mark.asyncio
    async def test_stream_unexpected_stop_reason(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should handle unexpected stop reason gracefully."""
        events = [
            MockStreamEvent(type="text_delta", content="Some text."),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="message_end", stop_reason="max_tokens"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        async def mock_stream_events(request):
            for event in events:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            result = await orchestrator.stream()

        # Should still return text, possibly with warning
        assert result.text is not None

    @pytest.mark.asyncio
    async def test_stream_with_continuation_conversation(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should use continuation conversation when provided."""
        events = [
            MockStreamEvent(type="text_delta", content="Continuing..."),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="message_end", stop_reason="end_turn"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        async def mock_stream_events(request):
            for event in events:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        continuation = [
            {
                "role": "user",
                "content": "Previous message"
            },
            {
                "role": "assistant",
                "content": "Previous response"
            },
            {
                "role":
                    "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "result"
                }]
            },
        ]

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            continuation_conversation=continuation,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            result = await orchestrator.stream()

        assert "Continuing" in result.text

    @pytest.mark.asyncio
    async def test_stream_multiple_tools_parallel(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should handle multiple parallel tool calls."""
        events = [
            MockStreamEvent(type="text_delta", content="Running tools..."),
            MockStreamEvent(
                type="tool_use",
                tool_id="tool_1",
                tool_name="web_search",
            ),
            MockStreamEvent(
                type="block_end",
                tool_id="tool_1",
                tool_name="web_search",
                tool_input={"query": "query 1"},
            ),
            MockStreamEvent(
                type="tool_use",
                tool_id="tool_2",
                tool_name="execute_python",
            ),
            MockStreamEvent(
                type="block_end",
                tool_id="tool_2",
                tool_name="execute_python",
                tool_input={"code": "print('hello')"},
            ),
            MockStreamEvent(type="message_end", stop_reason="tool_use"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(
                    content=[MockContentBlock(type="text", text="Running")]),
            ),
        ]

        second_events = [
            MockStreamEvent(type="text_delta", content="Done with tools!"),
            MockStreamEvent(type="block_end"),
            MockStreamEvent(type="message_end", stop_reason="end_turn"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        iteration = 0

        async def mock_stream_events(request):
            nonlocal iteration
            events_to_use = events if iteration == 0 else second_events
            iteration += 1
            for event in events_to_use:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        # Mock batch result with 2 tools
        mock_batch_result = BatchExecutionResult(
            results=[
                ToolExecutionResult(
                    tool=ToolCall(tool_id="tool_1", name="web_search",
                                  input={}),
                    result={"results": ["r1"]},
                    raw_result={},
                    is_error=False,
                ),
                ToolExecutionResult(
                    tool=ToolCall(tool_id="tool_2",
                                  name="execute_python",
                                  input={}),
                    result={"output": "hello"},
                    raw_result={},
                    is_error=False,
                ),
            ],
            force_turn_break=False,
        )

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
                patch.object(
                    orchestrator,
                    "_get_tool_executor",
                ) as mock_get_executor,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            mock_executor = MagicMock()
            mock_executor.execute_batch = AsyncMock(
                return_value=mock_batch_result)
            mock_get_executor.return_value = mock_executor

            result = await orchestrator.stream()

        assert result.iterations == 2
        assert "Done with tools" in result.text

    @pytest.mark.asyncio
    async def test_stream_empty_response(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should handle stream with no text content."""
        events = [
            MockStreamEvent(type="message_end", stop_reason="end_turn"),
            MockStreamEvent(
                type="stream_complete",
                final_message=MockMessage(content=[]),
            ),
        ]

        async def mock_stream_events(request):
            for event in events:
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            result = await orchestrator.stream()

        # Should still return a result
        assert isinstance(result, StreamResult)
        assert result.was_cancelled is False


class TestStreamingOrchestratorMaxIterations:
    """Tests for max iterations handling."""

    @pytest.mark.asyncio
    async def test_max_iterations_exceeded(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
        mock_draft_manager,
        mock_cancel_event,
        mock_action_manager,
    ):
        """Should return error when max iterations exceeded."""

        # Create events that always request tool use
        def make_tool_events():
            return [
                MockStreamEvent(type="text_delta", content="Calling tool..."),
                MockStreamEvent(
                    type="tool_use",
                    tool_id="tool_x",
                    tool_name="web_search",
                ),
                MockStreamEvent(
                    type="block_end",
                    tool_id="tool_x",
                    tool_name="web_search",
                    tool_input={"query": "test"},
                ),
                MockStreamEvent(type="message_end", stop_reason="tool_use"),
                MockStreamEvent(
                    type="stream_complete",
                    final_message=MockMessage(
                        content=[MockContentBlock(type="text", text="Calling")
                                ]),
                ),
            ]

        async def mock_stream_events(request):
            for event in make_tool_events():
                yield event

        mock_claude_provider.stream_events = mock_stream_events

        mock_batch_result = BatchExecutionResult(
            results=[
                ToolExecutionResult(
                    tool=ToolCall(tool_id="tool_x", name="web_search",
                                  input={}),
                    result={"results": []},
                    raw_result={},
                    is_error=False,
                ),
            ],
            force_turn_break=False,
        )

        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        with (
                patch("telegram.streaming.orchestrator.generation_context") as
                mock_gen_ctx,
                patch(
                    "telegram.streaming.orchestrator.DraftManager",
                    return_value=mock_draft_manager,
                ),
                patch("telegram.streaming.orchestrator.ChatActionManager") as
                mock_action_cls,
                patch.object(
                    orchestrator,
                    "_get_tool_executor",
                ) as mock_get_executor,
                patch(
                    "telegram.streaming.orchestrator.TOOL_LOOP_MAX_ITERATIONS",
                    3,  # Lower limit for faster test
                ),
        ):
            mock_gen_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_cancel_event)
            mock_gen_ctx.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_draft_manager.__aenter__ = AsyncMock(
                return_value=mock_draft_manager)
            mock_draft_manager.__aexit__ = AsyncMock(return_value=None)
            mock_action_cls.get.return_value = mock_action_manager

            mock_executor = MagicMock()
            mock_executor.execute_batch = AsyncMock(
                return_value=mock_batch_result)
            mock_get_executor.return_value = mock_executor

            result = await orchestrator.stream()

        assert result.was_cancelled is True
        assert result.cancellation_reason == CancellationReason.MAX_ITERATIONS
        assert "maximum iterations" in result.text.lower()


class TestStreamingOrchestratorToolExecutor:
    """Tests for tool executor integration."""

    def test_get_tool_executor_creates_instance(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
    ):
        """Should create ToolExecutor instance lazily."""
        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
        )

        assert orchestrator._tool_executor is None

        with patch("telegram.streaming.orchestrator.ToolExecutor"
                  ) as mock_executor_cls:
            mock_executor_cls.return_value = MagicMock()
            executor = orchestrator._get_tool_executor()

        assert executor is not None
        mock_executor_cls.assert_called_once()

    def test_get_tool_executor_returns_same_instance(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
    ):
        """Should return same ToolExecutor instance on subsequent calls."""
        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
        )

        with patch("telegram.streaming.orchestrator.ToolExecutor"
                  ) as mock_executor_cls:
            mock_executor_cls.return_value = MagicMock()
            executor1 = orchestrator._get_tool_executor()
            executor2 = orchestrator._get_tool_executor()

        assert executor1 is executor2
        mock_executor_cls.assert_called_once()  # Only created once


class TestStreamingOrchestratorClaudeProvider:
    """Tests for Claude provider handling."""

    def test_get_claude_provider_uses_injected(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
        mock_claude_provider,
    ):
        """Should use injected Claude provider."""
        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
            claude_provider=mock_claude_provider,
        )

        provider = orchestrator._get_claude_provider()
        assert provider is mock_claude_provider

    def test_get_claude_provider_uses_singleton_when_not_injected(
        self,
        mock_llm_request,
        mock_telegram_message,
        mock_session,
        mock_user_file_repo,
    ):
        """Should use singleton when no provider injected."""
        orchestrator = StreamingOrchestrator(
            request=mock_llm_request,
            first_message=mock_telegram_message,
            thread_id=1,
            session=mock_session,
            user_file_repo=mock_user_file_repo,
            chat_id=123,
            user_id=456,
        )

        # claude_provider is imported inside the method from telegram.handlers.claude
        with patch(
                "telegram.handlers.claude.claude_provider") as mock_singleton:
            provider = orchestrator._get_claude_provider()

        assert provider is mock_singleton


class TestConstants:
    """Tests for module constants."""

    def test_tool_loop_max_iterations(self):
        """Should have reasonable max iterations limit."""
        assert TOOL_LOOP_MAX_ITERATIONS == 25
        assert TOOL_LOOP_MAX_ITERATIONS > 0
