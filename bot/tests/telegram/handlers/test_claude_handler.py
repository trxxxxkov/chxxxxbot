"""Tests for Claude handler core functions.

Comprehensive tests for telegram/handlers/claude.py:
- init_claude_provider() - Provider initialization
- _send_with_retry() - Retry logic on flood control
- _process_message_batch() - Main entry point
- _process_batch_with_session() - Core processing logic
- Error handling for various exception types
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

from aiogram.exceptions import TelegramRetryAfter
import pytest
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import MessageMetadata
from telegram.pipeline.models import ProcessedMessage

# ============================================================================
# Helper fixtures
# ============================================================================


@asynccontextmanager
async def mock_session_context(session):
    """Helper to create async context manager for mock session."""
    yield session


@asynccontextmanager
async def mock_concurrency_context(user_id, thread_id):
    """Mock concurrency context that yields immediately."""
    yield 0  # queue position


@pytest.fixture
def mock_session():
    """Create mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def sample_metadata() -> MessageMetadata:
    """Create sample MessageMetadata."""
    return MessageMetadata(
        chat_id=789012,
        user_id=123456,
        message_id=12345,
        message_thread_id=None,
        chat_type="private",
        date=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_telegram_message():
    """Create mock Telegram message."""
    message = MagicMock()
    message.message_id = 12345
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.from_user.username = "testuser"
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.chat = MagicMock()
    message.chat.id = 789012
    message.chat.type = "private"
    message.text = "Hello"
    message.caption = None
    message.answer = AsyncMock(return_value=MagicMock(message_id=99999))
    message.date = MagicMock()
    message.date.timestamp.return_value = 1234567890.0
    message.date.isoformat.return_value = "2026-01-27T12:00:00"
    message.message_thread_id = None
    message.reply_to_message = None
    message.bot = MagicMock()
    return message


@pytest.fixture
def mock_thread():
    """Create mock Thread instance."""
    thread = Mock()
    thread.id = 42
    thread.chat_id = 789012
    thread.user_id = 123456
    thread.thread_id = None
    thread.model_id = "claude:sonnet"
    thread.needs_topic_naming = False
    return thread


@pytest.fixture
def mock_user():
    """Create mock User instance."""
    user = Mock()
    user.id = 123456
    user.model_id = "claude:sonnet"
    user.custom_prompt = None
    user.balance = Decimal("10.00")
    user.first_name = "Test"
    user.username = "testuser"
    return user


@pytest.fixture
def mock_claude_provider():
    """Create mock Claude provider."""
    provider = MagicMock()

    # Mock usage
    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50
    mock_usage.thinking_tokens = 0
    mock_usage.cache_read_tokens = 0
    mock_usage.cache_creation_tokens = 0
    mock_usage.web_search_requests = 0

    provider.get_usage = AsyncMock(return_value=mock_usage)
    provider.get_stop_reason = MagicMock(return_value="end_turn")
    provider.get_thinking_blocks_json = MagicMock(return_value=None)

    return provider


@pytest.fixture
def mock_stream_result():
    """Create mock StreamResult."""
    result = MagicMock()
    result.text = "Hello! I'm Claude."
    result.message = MagicMock(message_id=99999)
    result.message.date = MagicMock()
    result.message.date.timestamp.return_value = 1234567890.0
    result.message.date.isoformat.return_value = "2026-01-27T12:00:00"
    result.needs_continuation = False
    result.conversation = None
    result.was_cancelled = False
    result.thinking_chars = 0
    result.output_chars = 20
    return result


def make_processed_message(
    text: str,
    metadata: MessageMetadata,
    original_message: MagicMock,
) -> ProcessedMessage:
    """Helper to create ProcessedMessage."""
    return ProcessedMessage(
        text=text,
        metadata=metadata,
        original_message=original_message,
    )


# ============================================================================
# Tests for init_claude_provider
# ============================================================================


class TestInitClaudeProvider:
    """Tests for init_claude_provider function."""

    def test_init_creates_provider(self):
        """Should create ClaudeProvider and set global."""
        with patch(
                "telegram.handlers.claude.ClaudeProvider") as mock_provider_cls:
            mock_provider_cls.return_value = MagicMock()

            from telegram.handlers.claude import init_claude_provider

            init_claude_provider("test_api_key")

            mock_provider_cls.assert_called_once_with(api_key="test_api_key")

    def test_init_logs_initialization(self):
        """Should log provider initialization."""
        with patch(
                "telegram.handlers.claude.ClaudeProvider") as mock_provider_cls:
            mock_provider_cls.return_value = MagicMock()

            with patch("telegram.handlers.claude.logger") as mock_logger:
                from telegram.handlers.claude import init_claude_provider

                init_claude_provider("test_api_key")

                mock_logger.info.assert_called_with(
                    "claude_handler.provider_initialized")


# ============================================================================
# Tests for _send_with_retry
# ============================================================================


class TestSendWithRetry:
    """Tests for _send_with_retry function."""

    @pytest.mark.asyncio
    async def test_sends_message_successfully(self, mock_telegram_message):
        """Should send message on first attempt."""
        from telegram.handlers.claude import _send_with_retry

        result = await _send_with_retry(
            mock_telegram_message,
            "Test message",
            parse_mode="HTML",
        )

        mock_telegram_message.answer.assert_called_once_with(
            "Test message",
            parse_mode="HTML",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_retries_on_flood_control(self, mock_telegram_message):
        """Should retry on TelegramRetryAfter."""
        from telegram.handlers.claude import _send_with_retry

        # First call raises flood, second succeeds
        mock_telegram_message.answer.side_effect = [
            TelegramRetryAfter(
                retry_after=0.1,
                method="answer",
                message="Flood",
            ),
            MagicMock(message_id=99999),
        ]

        result = await _send_with_retry(
            mock_telegram_message,
            "Test message",
            max_retries=3,
        )

        assert mock_telegram_message.answer.call_count == 2
        assert result is not None

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self, mock_telegram_message):
        """Should raise TelegramRetryAfter after max retries."""
        from telegram.handlers.claude import _send_with_retry

        # All calls raise flood
        mock_telegram_message.answer.side_effect = TelegramRetryAfter(
            retry_after=0.01,
            method="answer",
            message="Flood",
        )

        with pytest.raises(TelegramRetryAfter):
            await _send_with_retry(
                mock_telegram_message,
                "Test message",
                max_retries=2,
            )

        assert mock_telegram_message.answer.call_count == 2

    @pytest.mark.asyncio
    async def test_respects_parse_mode(self, mock_telegram_message):
        """Should pass parse_mode to answer."""
        from telegram.handlers.claude import _send_with_retry

        await _send_with_retry(
            mock_telegram_message,
            "**bold**",
            parse_mode="MarkdownV2",
        )

        mock_telegram_message.answer.assert_called_with(
            "**bold**",
            parse_mode="MarkdownV2",
        )

    @pytest.mark.asyncio
    async def test_none_parse_mode(self, mock_telegram_message):
        """Should work with None parse_mode."""
        from telegram.handlers.claude import _send_with_retry

        await _send_with_retry(
            mock_telegram_message,
            "Plain text",
            parse_mode=None,
        )

        mock_telegram_message.answer.assert_called_with(
            "Plain text",
            parse_mode=None,
        )


# ============================================================================
# Tests for _process_message_batch
# ============================================================================


class TestProcessMessageBatch:
    """Tests for _process_message_batch function."""

    @pytest.mark.asyncio
    async def test_empty_batch_logs_error(self):
        """Should log error for empty batch (indicates bug in batching logic)."""
        with patch("telegram.handlers.claude.logger") as mock_logger:
            from telegram.handlers.claude import _process_message_batch

            await _process_message_batch(thread_id=42, messages=[])

            mock_logger.error.assert_called_with(
                "claude_handler.empty_batch",
                thread_id=42,
            )

    @pytest.mark.asyncio
    async def test_provider_not_initialized(
        self,
        mock_telegram_message,
        sample_metadata,
    ):
        """Should send error when provider not initialized."""
        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        with patch("telegram.handlers.claude.claude_provider", None):
            with patch("telegram.handlers.claude.logger"):
                from telegram.handlers.claude import _process_message_batch

                await _process_message_batch(thread_id=42, messages=[processed])

                mock_telegram_message.answer.assert_called_once()
                call_args = mock_telegram_message.answer.call_args[0][0]
                assert "not properly configured" in call_args

    @pytest.mark.asyncio
    async def test_concurrency_limit_exceeded(
        self,
        mock_telegram_message,
        sample_metadata,
        mock_claude_provider,
    ):
        """Should send error when concurrency limit exceeded."""
        from telegram.concurrency_limiter import ConcurrencyLimitExceeded

        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        @asynccontextmanager
        async def mock_concurrency_raises(user_id, thread_id):
            raise ConcurrencyLimitExceeded(
                user_id=123456,
                queue_position=3,
                wait_time=30.0,
            )
            yield  # pylint: disable=unreachable

        with patch("telegram.handlers.claude.claude_provider",
                   mock_claude_provider):
            with patch(
                    "telegram.handlers.claude.concurrency_context",
                    mock_concurrency_raises,
            ):
                with patch("telegram.handlers.claude.record_error"):
                    from telegram.handlers.claude import _process_message_batch

                    await _process_message_batch(thread_id=42,
                                                 messages=[processed])

                    mock_telegram_message.answer.assert_called_once()
                    call_args = mock_telegram_message.answer.call_args[0][0]
                    assert "Too many requests" in call_args


class TestProcessBatchWithSession:
    """Tests for _process_batch_with_session function."""

    @pytest.mark.asyncio
    async def test_thread_not_found(
        self,
        mock_session,
        mock_telegram_message,
        sample_metadata,
    ):
        """Should send error when thread not found."""
        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        mock_thread_repo = AsyncMock()
        mock_thread_repo.get_by_id = AsyncMock(return_value=None)

        with patch(
                "telegram.handlers.claude.get_session",
                return_value=mock_session_context(mock_session),
        ):
            with patch(
                    "telegram.handlers.claude.ThreadRepository",
                    return_value=mock_thread_repo,
            ):
                with patch("telegram.handlers.claude.logger"):
                    from telegram.handlers.claude import \
                        _process_batch_with_session

                    await _process_batch_with_session(
                        thread_id=42,
                        messages=[processed],
                        first_message=mock_telegram_message,
                    )

                    mock_telegram_message.answer.assert_called_once()
                    call_args = mock_telegram_message.answer.call_args[0][0]
                    assert "Thread not found" in call_args

    @pytest.mark.asyncio
    async def test_user_not_found(
        self,
        mock_session,
        mock_telegram_message,
        sample_metadata,
        mock_thread,
    ):
        """Should send error when user not found in DB and cache."""
        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        mock_thread_repo = AsyncMock()
        mock_thread_repo.get_by_id = AsyncMock(return_value=mock_thread)

        mock_msg_repo = AsyncMock()
        mock_msg_repo.create_message = AsyncMock()

        mock_user_repo = AsyncMock()
        mock_user_repo.get_by_id = AsyncMock(return_value=None)

        mock_services = MagicMock()
        mock_services.users = mock_user_repo

        patches = {
            "get_session":
                patch(
                    "telegram.handlers.claude.get_session",
                    return_value=mock_session_context(mock_session),
                ),
            "thread_repo":
                patch(
                    "telegram.handlers.claude.ThreadRepository",
                    return_value=mock_thread_repo,
                ),
            "msg_repo":
                patch(
                    "telegram.handlers.claude.MessageRepository",
                    return_value=mock_msg_repo,
                ),
            "services":
                patch(
                    "telegram.handlers.claude.ServiceFactory",
                    return_value=mock_services,
                ),
            "cache":
                patch(
                    "telegram.handlers.claude.get_cached_user",
                    AsyncMock(return_value=None),
                ),
            "invalidate":
                patch(
                    "telegram.handlers.claude.invalidate_messages",
                    AsyncMock(),
                ),
            "logger":
                patch("telegram.handlers.claude.logger"),
        }

        with patches["get_session"], patches["thread_repo"], patches[
                "msg_repo"]:
            with patches["services"], patches["cache"], patches["invalidate"]:
                with patches["logger"]:
                    from telegram.handlers.claude import \
                        _process_batch_with_session

                    await _process_batch_with_session(
                        thread_id=42,
                        messages=[processed],
                        first_message=mock_telegram_message,
                    )

                    mock_telegram_message.answer.assert_called()
                    call_args = mock_telegram_message.answer.call_args[0][0]
                    assert "User not found" in call_args


# ============================================================================
# Tests for error handling
# ============================================================================


class TestErrorHandling:
    """Tests for error handling in _process_batch_with_session."""

    def _setup_patches(
        self,
        mock_session,
        mock_thread,
        mock_user,
        context_error=None,
    ):
        """Setup common patches for error handling tests."""
        mock_thread_repo = AsyncMock()
        mock_thread_repo.get_by_id = AsyncMock(return_value=mock_thread)

        mock_msg_repo = AsyncMock()
        mock_msg_repo.create_message = AsyncMock()
        mock_msg_repo.get_thread_messages = AsyncMock(return_value=[])

        mock_user_file_repo = AsyncMock()

        mock_services = MagicMock()
        mock_services.users = AsyncMock()
        mock_services.users.get_by_id = AsyncMock(return_value=mock_user)

        mock_context_mgr = MagicMock()
        if context_error:
            mock_context_mgr.build_context = AsyncMock(
                side_effect=context_error)
        else:
            mock_context_mgr.build_context = AsyncMock(return_value=[])

        mock_formatter = MagicMock()
        mock_formatter.format_conversation_with_files = AsyncMock(
            return_value=[])

        return {
            "get_session":
                patch(
                    "telegram.handlers.claude.get_session",
                    return_value=mock_session_context(mock_session),
                ),
            "thread_repo":
                patch(
                    "telegram.handlers.claude.ThreadRepository",
                    return_value=mock_thread_repo,
                ),
            "msg_repo":
                patch(
                    "telegram.handlers.claude.MessageRepository",
                    return_value=mock_msg_repo,
                ),
            "file_repo":
                patch(
                    "telegram.handlers.claude.UserFileRepository",
                    return_value=mock_user_file_repo,
                ),
            "services":
                patch(
                    "telegram.handlers.claude.ServiceFactory",
                    return_value=mock_services,
                ),
            "cache_user":
                patch(
                    "telegram.handlers.claude.get_cached_user",
                    AsyncMock(return_value=None),
                ),
            "cache_set":
                patch(
                    "telegram.handlers.claude.cache_user",
                    AsyncMock(),
                ),
            "invalidate":
                patch(
                    "telegram.handlers.claude.invalidate_messages",
                    AsyncMock(),
                ),
            "cache_msgs":
                patch(
                    "telegram.handlers.claude.cache_messages",
                    AsyncMock(),
                ),
            "files":
                patch(
                    "telegram.handlers.claude.get_available_files",
                    AsyncMock(return_value=[]),
                ),
            "pending":
                patch(
                    "telegram.handlers.claude.get_pending_files_for_thread",
                    AsyncMock(return_value=[]),
                ),
            "context":
                patch(
                    "telegram.handlers.claude.ContextManager",
                    return_value=mock_context_mgr,
                ),
            "formatter":
                patch(
                    "telegram.handlers.claude.ContextFormatter",
                    return_value=mock_formatter,
                ),
            "record_error":
                patch("telegram.handlers.claude.record_error"),
            "record_request":
                patch("telegram.handlers.claude.record_claude_request"),
            "logger":
                patch("telegram.handlers.claude.logger"),
        }

    @pytest.mark.asyncio
    async def test_context_window_exceeded(
        self,
        mock_session,
        mock_telegram_message,
        sample_metadata,
        mock_thread,
        mock_user,
    ):
        """Should handle ContextWindowExceededError."""
        from core.exceptions import ContextWindowExceededError

        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        patches = self._setup_patches(
            mock_session,
            mock_thread,
            mock_user,
            context_error=ContextWindowExceededError(
                message="Context window exceeded",
                tokens_used=250000,
                tokens_limit=200000,
            ),
        )

        # Apply patches in batches to avoid nesting limit
        with patches["get_session"], patches["thread_repo"], patches[
                "msg_repo"]:
            with patches["file_repo"], patches["services"], patches[
                    "cache_user"]:
                with patches["cache_set"], patches["invalidate"], patches[
                        "cache_msgs"]:
                    with patches["files"], patches["pending"], patches[
                            "context"]:
                        with patches["formatter"], patches[
                                "record_error"], patches["logger"]:
                            from telegram.handlers.claude import \
                                _process_batch_with_session

                            await _process_batch_with_session(
                                thread_id=42,
                                messages=[processed],
                                first_message=mock_telegram_message,
                            )

        mock_telegram_message.answer.assert_called()
        call_args = mock_telegram_message.answer.call_args[0][0]
        assert "Context window exceeded" in call_args
        assert "250,000" in call_args

    @pytest.mark.asyncio
    async def test_rate_limit_error(
        self,
        mock_session,
        mock_telegram_message,
        sample_metadata,
        mock_thread,
        mock_user,
    ):
        """Should handle RateLimitError."""
        from core.exceptions import RateLimitError

        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        patches = self._setup_patches(
            mock_session,
            mock_thread,
            mock_user,
            context_error=RateLimitError(
                message="Rate limited",
                retry_after=30,
            ),
        )

        with patches["get_session"], patches["thread_repo"], patches[
                "msg_repo"]:
            with patches["file_repo"], patches["services"], patches[
                    "cache_user"]:
                with patches["cache_set"], patches["invalidate"], patches[
                        "cache_msgs"]:
                    with patches["files"], patches["pending"], patches[
                            "context"]:
                        with patches["formatter"], patches[
                                "record_error"], patches["record_request"]:
                            with patches["logger"]:
                                from telegram.handlers.claude import \
                                    _process_batch_with_session

                                await _process_batch_with_session(
                                    thread_id=42,
                                    messages=[processed],
                                    first_message=mock_telegram_message,
                                )

        mock_telegram_message.answer.assert_called()
        call_args = mock_telegram_message.answer.call_args[0][0]
        assert "Rate limit exceeded" in call_args
        assert "30 seconds" in call_args

    @pytest.mark.asyncio
    async def test_api_connection_error(
        self,
        mock_session,
        mock_telegram_message,
        sample_metadata,
        mock_thread,
        mock_user,
    ):
        """Should handle APIConnectionError."""
        from core.exceptions import APIConnectionError

        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        patches = self._setup_patches(
            mock_session,
            mock_thread,
            mock_user,
            context_error=APIConnectionError("Connection failed"),
        )

        with patches["get_session"], patches["thread_repo"], patches[
                "msg_repo"]:
            with patches["file_repo"], patches["services"], patches[
                    "cache_user"]:
                with patches["cache_set"], patches["invalidate"], patches[
                        "cache_msgs"]:
                    with patches["files"], patches["pending"], patches[
                            "context"]:
                        with patches["formatter"], patches[
                                "record_error"], patches["record_request"]:
                            with patches["logger"]:
                                from telegram.handlers.claude import \
                                    _process_batch_with_session

                                await _process_batch_with_session(
                                    thread_id=42,
                                    messages=[processed],
                                    first_message=mock_telegram_message,
                                )

        mock_telegram_message.answer.assert_called()
        call_args = mock_telegram_message.answer.call_args[0][0]
        assert "Connection error" in call_args

    @pytest.mark.asyncio
    async def test_api_timeout_error(
        self,
        mock_session,
        mock_telegram_message,
        sample_metadata,
        mock_thread,
        mock_user,
    ):
        """Should handle APITimeoutError."""
        from core.exceptions import APITimeoutError

        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        patches = self._setup_patches(
            mock_session,
            mock_thread,
            mock_user,
            context_error=APITimeoutError("Request timed out"),
        )

        with patches["get_session"], patches["thread_repo"], patches[
                "msg_repo"]:
            with patches["file_repo"], patches["services"], patches[
                    "cache_user"]:
                with patches["cache_set"], patches["invalidate"], patches[
                        "cache_msgs"]:
                    with patches["files"], patches["pending"], patches[
                            "context"]:
                        with patches["formatter"], patches[
                                "record_error"], patches["record_request"]:
                            with patches["logger"]:
                                from telegram.handlers.claude import \
                                    _process_batch_with_session

                                await _process_batch_with_session(
                                    thread_id=42,
                                    messages=[processed],
                                    first_message=mock_telegram_message,
                                )

        mock_telegram_message.answer.assert_called()
        call_args = mock_telegram_message.answer.call_args[0][0]
        assert "timed out" in call_args

    @pytest.mark.asyncio
    async def test_unexpected_error(
        self,
        mock_session,
        mock_telegram_message,
        sample_metadata,
        mock_thread,
        mock_user,
    ):
        """Should handle unexpected errors gracefully."""
        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        patches = self._setup_patches(
            mock_session,
            mock_thread,
            mock_user,
            context_error=RuntimeError("Unexpected!"),
        )

        with patches["get_session"], patches["thread_repo"], patches[
                "msg_repo"]:
            with patches["file_repo"], patches["services"], patches[
                    "cache_user"]:
                with patches["cache_set"], patches["invalidate"], patches[
                        "cache_msgs"]:
                    with patches["files"], patches["pending"], patches[
                            "context"]:
                        with patches["formatter"], patches[
                                "record_error"], patches["logger"]:
                            from telegram.handlers.claude import \
                                _process_batch_with_session

                            await _process_batch_with_session(
                                thread_id=42,
                                messages=[processed],
                                first_message=mock_telegram_message,
                            )

        mock_telegram_message.answer.assert_called()
        call_args = mock_telegram_message.answer.call_args[0][0]
        assert "Unexpected error" in call_args


# ============================================================================
# Tests for batch metrics
# ============================================================================


class TestBatchMetrics:
    """Tests for batch processing metrics."""

    @pytest.mark.asyncio
    async def test_records_batch_metrics_for_multiple_messages(
        self,
        mock_telegram_message,
        sample_metadata,
        mock_claude_provider,
    ):
        """Should record batch metrics when processing multiple messages."""
        processed1 = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )
        processed2 = make_processed_message(
            text="World",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        mock_record_batched = MagicMock()

        with patch("telegram.handlers.claude.claude_provider",
                   mock_claude_provider):
            with patch(
                    "telegram.handlers.claude.concurrency_context",
                    mock_concurrency_context,
            ):
                with patch(
                        "telegram.handlers.claude._process_batch_with_session",
                        AsyncMock(),
                ):
                    with patch(
                            "telegram.handlers.claude.record_messages_batched",
                            mock_record_batched,
                    ):
                        with patch("telegram.handlers.claude.logger"):
                            from telegram.handlers.claude import \
                                _process_message_batch

                            await _process_message_batch(
                                thread_id=42,
                                messages=[processed1, processed2],
                            )

                            mock_record_batched.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_no_batch_metrics_for_single_message(
        self,
        mock_telegram_message,
        sample_metadata,
        mock_claude_provider,
    ):
        """Should not record batch metrics for single message."""
        processed = make_processed_message(
            text="Hello",
            metadata=sample_metadata,
            original_message=mock_telegram_message,
        )

        mock_record_batched = MagicMock()

        with patch("telegram.handlers.claude.claude_provider",
                   mock_claude_provider):
            with patch(
                    "telegram.handlers.claude.concurrency_context",
                    mock_concurrency_context,
            ):
                with patch(
                        "telegram.handlers.claude._process_batch_with_session",
                        AsyncMock(),
                ):
                    with patch(
                            "telegram.handlers.claude.record_messages_batched",
                            mock_record_batched,
                    ):
                        with patch("telegram.handlers.claude.logger"):
                            from telegram.handlers.claude import \
                                _process_message_batch

                            await _process_message_batch(
                                thread_id=42,
                                messages=[processed],
                            )

                            mock_record_batched.assert_not_called()
