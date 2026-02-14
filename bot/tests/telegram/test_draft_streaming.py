"""Tests for DraftStreamer class.

Tests cover:
- Throttling behavior with force parameter
- pending_text handling
- finalize() with edit_message_text for smooth transitions
- keepalive() behavior
"""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
import pytest
from telegram.draft_streaming import _truncate_for_telegram
from telegram.draft_streaming import DraftStreamer
from telegram.draft_streaming import MIN_UPDATE_INTERVAL
from telegram.draft_streaming import TELEGRAM_MESSAGE_LIMIT


@pytest.fixture
def mock_bot():
    """Create a mock Bot instance."""
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=123))
    bot.edit_message_text = AsyncMock(return_value=None)
    return bot


@pytest.fixture
def streamer(mock_bot):
    """Create a DraftStreamer instance."""
    return DraftStreamer(bot=mock_bot, chat_id=100, topic_id=200)


class TestDraftStreamerUpdate:
    """Tests for update() method."""

    @pytest.mark.asyncio
    async def test_update_force_uses_passed_text(self, streamer, mock_bot):
        """When force=True, passed text should be used, not pending_text."""
        # First update to set last_text
        await streamer.update("initial text")

        # Simulate throttled update (sets pending_text)
        streamer._pending_text = "old pending text"

        # Force update with new text
        await streamer.update("final text", force=True)

        # Verify last_text is the forced text, not pending
        assert streamer.last_text == "final text"
        assert streamer._pending_text is None

    @pytest.mark.asyncio
    async def test_update_without_force_uses_pending_text(
            self, streamer, mock_bot):
        """Without force, pending_text should be sent if available."""
        # Set up pending text
        streamer._pending_text = "pending content"
        streamer._last_update_time = 0  # Allow update

        # Update without force
        await streamer.update("new content")

        # Should have sent pending_text
        assert streamer.last_text == "pending content"

    @pytest.mark.asyncio
    async def test_update_throttling_stores_pending(self, streamer, mock_bot):
        """Update should store pending_text when throttled."""
        # First update
        await streamer.update("first")

        # Immediate second update should be throttled
        await streamer.update("second")

        # pending_text should be set
        assert streamer._pending_text == "second"

    @pytest.mark.asyncio
    async def test_update_skips_unchanged_text(self, streamer, mock_bot):
        """Update should skip if text is unchanged."""
        await streamer.update("same text")
        initial_count = streamer._update_count

        result = await streamer.update("same text")

        # Should return True but not increment count
        assert result is True
        assert streamer._update_count == initial_count

    @pytest.mark.asyncio
    async def test_update_truncates_long_text(self, streamer, mock_bot):
        """Text longer than 4096 chars should be truncated with ellipsis."""
        long_text = "x" * 5000
        await streamer.update(long_text, force=True)

        assert len(streamer.last_text) <= 4096
        assert streamer.last_text.endswith("…")


class TestDraftStreamerFinalize:
    """Tests for finalize() method."""

    @pytest.mark.asyncio
    async def test_finalize_with_different_text_updates_draft_first(
            self, streamer, mock_bot):
        """finalize() should update draft before sending when text differs."""
        # Set up streamer with some text
        streamer.last_text = "text with thinking"

        # Finalize with different text
        await streamer.finalize(final_text="clean text")

        # Should have called SendMessageDraft (update) and send_message
        # No edit needed - final text sent directly
        assert mock_bot.call_count >= 1  # SendMessageDraft update
        mock_bot.send_message.assert_called_once_with(
            chat_id=100,
            text="clean text",
            message_thread_id=200,
            parse_mode="MarkdownV2",  # Default parse mode
        )
        mock_bot.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_with_same_text_no_edit(self, streamer, mock_bot):
        """finalize() should not edit when final_text matches."""
        streamer.last_text = "same text"

        await streamer.finalize(final_text="same text")

        mock_bot.send_message.assert_called_once()
        mock_bot.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_without_final_text(self, streamer, mock_bot):
        """finalize() without final_text should not edit."""
        streamer.last_text = "original text"

        await streamer.finalize()

        mock_bot.send_message.assert_called_once()
        mock_bot.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_finalize_returns_message_with_final_text(
            self, streamer, mock_bot):
        """finalize() should return message with final text directly."""
        streamer.last_text = "text with thinking"

        message = await streamer.finalize(final_text="clean text")

        # Should return the message with final text (no edit needed)
        assert message.message_id == 123
        mock_bot.send_message.assert_called_once_with(
            chat_id=100,
            text="clean text",
            message_thread_id=200,
            parse_mode="MarkdownV2",  # Default parse mode
        )

    @pytest.mark.asyncio
    async def test_finalize_flushes_pending_first(self, streamer, mock_bot):
        """finalize() should flush pending text before sending."""
        streamer._pending_text = "pending"
        streamer._last_update_time = 0

        await streamer.finalize()

        # pending_text should have been flushed
        assert streamer._pending_text is None


class TestDraftStreamerKeepalive:
    """Tests for keepalive() method."""

    @pytest.mark.asyncio
    async def test_keepalive_skips_when_no_last_text(self, streamer, mock_bot):
        """keepalive() should skip when last_text is empty."""
        streamer.last_text = ""

        result = await streamer.keepalive()

        assert result is True
        # Bot should not have been called (no SendMessageDraft)
        # We verify this by checking the update count didn't change
        assert streamer._update_count == 0

    @pytest.mark.asyncio
    async def test_keepalive_sends_last_text(self, streamer, mock_bot):
        """keepalive() should resend last_text."""
        streamer.last_text = "current content"

        result = await streamer.keepalive()

        assert result is True
        # Bot was called
        mock_bot.assert_called()

    @pytest.mark.asyncio
    async def test_keepalive_returns_true_on_success(self, streamer, mock_bot):
        """keepalive() should return True on success."""
        streamer.last_text = "content"

        result = await streamer.keepalive()

        assert result is True


class TestDraftStreamerIntegration:
    """Integration tests for DraftStreamer."""

    @pytest.mark.asyncio
    async def test_streaming_workflow(self, streamer, mock_bot):
        """Test typical streaming workflow."""
        # Stream multiple updates
        await streamer.update("Starting...")
        await asyncio.sleep(MIN_UPDATE_INTERVAL + 0.01)
        await streamer.update("Processing...")
        await asyncio.sleep(MIN_UPDATE_INTERVAL + 0.01)
        await streamer.update("Done!")

        # Finalize
        message = await streamer.finalize()

        assert message is not None
        assert streamer._update_count >= 1

    @pytest.mark.asyncio
    async def test_force_update_bypasses_throttle(self, streamer, mock_bot):
        """Force update should bypass throttling."""
        await streamer.update("first")

        # Immediate force update
        await streamer.update("forced", force=True)

        assert streamer.last_text == "forced"

    @pytest.mark.asyncio
    async def test_pending_text_cleared_on_force(self, streamer, mock_bot):
        """force=True should clear pending_text."""
        await streamer.update("first")
        streamer._pending_text = "pending"

        await streamer.update("forced", force=True)

        assert streamer._pending_text is None
        assert streamer.last_text == "forced"


class TestDraftStreamerKeepaliveTask:
    """Tests for automatic keepalive task management.

    Ensures keepalive task is properly started and stopped to prevent
    resource leaks when exceptions occur during streaming.
    """

    @pytest.mark.asyncio
    async def test_start_keepalive_creates_task(self, streamer, mock_bot):
        """start_keepalive() should create a background task."""
        assert streamer._keepalive_task is None

        streamer.start_keepalive(interval=1.0)

        assert streamer._keepalive_task is not None
        assert not streamer._keepalive_task.done()

        # Clean up
        await streamer.stop_keepalive()

    @pytest.mark.asyncio
    async def test_start_keepalive_is_idempotent(self, streamer, mock_bot):
        """Calling start_keepalive() twice should not create duplicate tasks."""
        streamer.start_keepalive(interval=1.0)
        first_task = streamer._keepalive_task

        streamer.start_keepalive(interval=1.0)
        second_task = streamer._keepalive_task

        assert first_task is second_task

        # Clean up
        await streamer.stop_keepalive()

    @pytest.mark.asyncio
    async def test_stop_keepalive_cancels_task(self, streamer, mock_bot):
        """stop_keepalive() should cancel the running task."""
        streamer.start_keepalive(interval=1.0)
        task = streamer._keepalive_task

        await streamer.stop_keepalive()

        assert streamer._keepalive_task is None
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_stop_keepalive_is_idempotent(self, streamer, mock_bot):
        """stop_keepalive() should be safe to call multiple times."""
        streamer.start_keepalive(interval=1.0)

        await streamer.stop_keepalive()
        await streamer.stop_keepalive()  # Should not raise

        assert streamer._keepalive_task is None

    @pytest.mark.asyncio
    async def test_finalize_stops_keepalive(self, streamer, mock_bot):
        """finalize() should automatically stop the keepalive task."""
        streamer.start_keepalive(interval=1.0)
        task = streamer._keepalive_task

        await streamer.finalize()

        assert streamer._keepalive_task is None
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_clear_stops_keepalive_with_content(self, streamer, mock_bot):
        """clear() should stop keepalive task when there is content."""
        streamer.last_text = "some content"
        streamer.start_keepalive(interval=1.0)
        task = streamer._keepalive_task

        await streamer.clear()

        assert streamer._keepalive_task is None
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_clear_stops_keepalive_without_content(
            self, streamer, mock_bot):
        """clear() should stop keepalive task even when no content was sent."""
        streamer.start_keepalive(interval=1.0)
        task = streamer._keepalive_task

        await streamer.clear()

        assert streamer._keepalive_task is None
        assert task.cancelled() or task.done()


class TestDraftManager:
    """Tests for DraftManager context manager."""

    @pytest.fixture
    def draft_manager(self, mock_bot):
        """Create a DraftManager instance."""
        from telegram.draft_streaming import DraftManager
        return DraftManager(bot=mock_bot, chat_id=100, topic_id=200)

    @pytest.mark.asyncio
    async def test_context_manager_creates_streamer(self, draft_manager,
                                                    mock_bot):
        """DraftManager should create a streamer when accessed."""
        async with draft_manager as dm:
            streamer = dm.current
            assert streamer is not None
            assert streamer.chat_id == 100
            assert streamer.topic_id == 200

    @pytest.mark.asyncio
    async def test_context_manager_starts_keepalive(self, draft_manager,
                                                    mock_bot):
        """DraftManager should start keepalive when streamer is accessed."""
        async with draft_manager as dm:
            streamer = dm.current
            assert streamer._keepalive_task is not None

    @pytest.mark.asyncio
    async def test_context_manager_cleans_up_on_normal_exit(
            self, draft_manager, mock_bot):
        """DraftManager should cleanup on normal exit."""
        async with draft_manager as dm:
            streamer = dm.current
            streamer.last_text = "some content"
            task = streamer._keepalive_task

        # After exit, task should be stopped
        assert task.cancelled() or task.done()
        assert dm._current is None

    @pytest.mark.asyncio
    async def test_context_manager_cleans_up_on_exception(
            self, draft_manager, mock_bot):
        """DraftManager should cleanup even when exception occurs."""
        try:
            async with draft_manager as dm:
                streamer = dm.current
                streamer.last_text = "some content"
                task = streamer._keepalive_task
                raise ValueError("Test error")
        except ValueError:
            pass

        # After exception, task should still be stopped
        assert task.cancelled() or task.done()
        assert dm._current is None

    @pytest.mark.asyncio
    async def test_commit_and_create_new(self, draft_manager, mock_bot):
        """commit_and_create_new should finalize current and create new."""
        async with draft_manager as dm:
            first_streamer = dm.current
            first_draft_id = first_streamer.draft_id

            await dm.commit_and_create_new()

            second_streamer = dm.current
            assert second_streamer is not first_streamer
            assert second_streamer.draft_id != first_draft_id

    @pytest.mark.asyncio
    async def test_commit_and_create_new_with_final_text(
            self, draft_manager, mock_bot):
        """commit_and_create_new should use final_text when provided."""
        async with draft_manager as dm:
            streamer = dm.current
            await streamer.update("initial text")

            await dm.commit_and_create_new(final_text="final text")

            # send_message should have been called for finalize
            mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_current_is_lazy(self, draft_manager, mock_bot):
        """current property should only create streamer when accessed."""
        async with draft_manager as dm:
            # Before accessing current, _current should be None
            assert dm._current is None

            # Access current
            _ = dm.current

            # Now _current should be set
            assert dm._current is not None

    @pytest.mark.asyncio
    async def test_current_returns_same_instance(self, draft_manager, mock_bot):
        """current should return the same instance on multiple accesses."""
        async with draft_manager as dm:
            first = dm.current
            second = dm.current
            assert first is second


class TestDraftStreamerErrorHandling:
    """Tests for error handling in update() method."""

    @pytest.mark.asyncio
    async def test_update_handles_text_must_be_non_empty(
            self, streamer, mock_bot):
        """Update should return True on 'text must be non-empty' error.

        This is an expected edge case during streaming when first chunk
        produces MarkdownV2 that Telegram considers visually empty.
        """
        from aiogram.exceptions import TelegramBadRequest

        # Mock bot to raise "text must be non-empty" error
        mock_bot.side_effect = TelegramBadRequest(
            method=MagicMock(), message="Bad Request: text must be non-empty")

        result = await streamer.update("**>||", force=True)

        # Should return True (graceful skip), not False
        assert result is True

    @pytest.mark.asyncio
    async def test_update_handles_parse_error_with_fallback(
            self, streamer, mock_bot):
        """Update should retry with parse_mode=None on parse error."""
        from aiogram.exceptions import TelegramBadRequest

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TelegramBadRequest(
                    method=MagicMock(),
                    message="Bad Request: can't parse entities")
            return None

        mock_bot.side_effect = side_effect

        result = await streamer.update("test",
                                       parse_mode="MarkdownV2",
                                       force=True)

        # Should succeed on retry
        assert result is True
        assert call_count == 2  # First call failed, second succeeded


class TestTruncateForTelegram:
    """Tests for _truncate_for_telegram helper function."""

    def test_short_text_unchanged(self):
        """Text within limit should be returned unchanged."""
        text = "Short text"
        assert _truncate_for_telegram(text) == text

    def test_exactly_at_limit_unchanged(self):
        """Text exactly at 4096 should be returned unchanged."""
        text = "x" * TELEGRAM_MESSAGE_LIMIT
        assert _truncate_for_telegram(text) == text

    def test_plain_text_truncated(self):
        """Plain text over limit should be truncated with ellipsis."""
        text = "x" * 5000
        result = _truncate_for_telegram(text, None)
        assert len(result) == TELEGRAM_MESSAGE_LIMIT
        assert result.endswith("…")

    def test_markdown_v2_truncated(self):
        """MarkdownV2 text should be truncated with room for formatting fix."""
        text = "x" * 5000
        result = _truncate_for_telegram(text, "MarkdownV2")
        assert len(result) <= TELEGRAM_MESSAGE_LIMIT

    def test_markdown_v2_fixes_broken_formatting(self):
        """MarkdownV2 truncation should close unclosed formatting."""
        # Text with unclosed bold that gets cut
        text = "*bold text " + "x" * 5000
        result = _truncate_for_telegram(text, "MarkdownV2")
        assert len(result) <= TELEGRAM_MESSAGE_LIMIT
        # Bold should be closed
        bold_count = result.count("*")
        assert bold_count % 2 == 0

    def test_markdown_v2_with_special_chars(self):
        """MarkdownV2 with escaped special chars should fit in limit."""
        # Each \= is 2 chars — text with many special chars
        text = "a\\=b\\+c\\-d\\." * 1000
        result = _truncate_for_telegram(text, "MarkdownV2")
        assert len(result) <= TELEGRAM_MESSAGE_LIMIT

    def test_safety_check_after_fix(self):
        """If fix_truncated_md2 makes text longer, re-truncate."""
        # Create text that when truncated at 4076 + fix might exceed 4096
        # Use unclosed code block to trigger fix_truncated_md2 adding ```
        text = "```python\n" + "x" * 5000
        result = _truncate_for_telegram(text, "MarkdownV2")
        assert len(result) <= TELEGRAM_MESSAGE_LIMIT


class TestFinalizeErrorHandling:
    """Tests for finalize() error handling improvements."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock Bot instance."""
        bot = AsyncMock(spec=Bot)
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=123))
        return bot

    @pytest.fixture
    def streamer(self, mock_bot):
        """Create a DraftStreamer instance."""
        return DraftStreamer(bot=mock_bot, chat_id=100, topic_id=200)

    @pytest.mark.asyncio
    async def test_finalize_truncates_long_text(self, streamer, mock_bot):
        """finalize() should truncate text exceeding 4096 chars."""
        long_text = "x" * 5000
        streamer.last_text = long_text

        await streamer.finalize(final_text=long_text, parse_mode=None)

        # send_message should be called with truncated text
        call_args = mock_bot.send_message.call_args
        assert len(call_args.kwargs["text"]) <= TELEGRAM_MESSAGE_LIMIT

    @pytest.mark.asyncio
    async def test_finalize_handles_message_too_long(self, streamer, mock_bot):
        """finalize() should fallback on 'message is too long' error."""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TelegramBadRequest(
                    method=MagicMock(),
                    message="Bad Request: message is too long")
            return MagicMock(message_id=123)

        mock_bot.send_message = AsyncMock(side_effect=side_effect)

        # Text within our truncation limit but Telegram still rejects
        streamer.last_text = "x" * 4000

        message = await streamer.finalize(final_text="x" * 4000,
                                          parse_mode="MarkdownV2")

        assert message.message_id == 123
        assert call_count == 2  # First failed, second succeeded with plain text

    @pytest.mark.asyncio
    async def test_finalize_parse_error_with_truncation(self, streamer,
                                                        mock_bot):
        """finalize() should truncate when falling back to plain text."""
        # MarkdownV2 escaped text is long; plain text fallback should truncate
        escaped_text = "\\=" * 3000  # 6000 chars (3000 \= pairs)
        streamer.last_text = escaped_text

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TelegramBadRequest(
                    method=MagicMock(),
                    message="Bad Request: can't parse entities: "
                    "Character '=' is reserved")
            return MagicMock(message_id=123)

        mock_bot.send_message = AsyncMock(side_effect=side_effect)

        message = await streamer.finalize(final_text=escaped_text,
                                          parse_mode="MarkdownV2")

        # Second call should have truncated text
        second_call_text = mock_bot.send_message.call_args_list[1].kwargs[
            "text"]
        assert len(second_call_text) <= TELEGRAM_MESSAGE_LIMIT
        assert message.message_id == 123

    @pytest.mark.asyncio
    async def test_finalize_non_parse_error_still_raised(
            self, streamer, mock_bot):
        """finalize() should re-raise non-parse, non-length errors."""
        mock_bot.send_message = AsyncMock(side_effect=TelegramBadRequest(
            method=MagicMock(), message="Bad Request: chat not found"))

        streamer.last_text = "test"

        with pytest.raises(TelegramBadRequest, match="chat not found"):
            await streamer.finalize(final_text="test")
