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
import pytest
from telegram.draft_streaming import DraftStreamer
from telegram.draft_streaming import MIN_UPDATE_INTERVAL


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
        """Text longer than 4096 chars should be truncated."""
        long_text = "x" * 5000
        await streamer.update(long_text, force=True)

        assert len(streamer.last_text) == 4096
        assert streamer.last_text.endswith("...")


class TestDraftStreamerFinalize:
    """Tests for finalize() method."""

    @pytest.mark.asyncio
    async def test_finalize_with_different_text_calls_edit(
            self, streamer, mock_bot):
        """finalize() should edit message when final_text differs."""
        # Set up streamer with some text
        streamer.last_text = "text with thinking"

        # Finalize with different text
        await streamer.finalize(final_text="clean text")

        # Should have called send_message and edit_message_text
        mock_bot.send_message.assert_called_once()
        mock_bot.edit_message_text.assert_called_once_with(
            chat_id=100,
            message_id=123,
            text="clean text",
            parse_mode="HTML",
        )

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
    async def test_finalize_edit_failure_still_returns_message(
            self, streamer, mock_bot):
        """finalize() should return message even if edit fails."""
        streamer.last_text = "text with thinking"
        mock_bot.edit_message_text.side_effect = Exception("Edit failed")

        message = await streamer.finalize(final_text="clean text")

        # Should still return the message
        assert message.message_id == 123

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


class TestDraftStreamerClear:
    """Tests for clear() method."""

    @pytest.mark.asyncio
    async def test_clear_returns_true_on_success(self, streamer, mock_bot):
        """clear() should return True on success."""
        result = await streamer.clear()

        assert result is True

    @pytest.mark.asyncio
    async def test_clear_handles_error(self, streamer, mock_bot):
        """clear() should handle errors gracefully."""
        # Make the bot call raise an exception
        mock_bot.side_effect = Exception("Network error")

        result = await streamer.clear()

        assert result is False


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
