"""Unit tests for normalization tracker.

Tests the tracker's ability to synchronize message processing
for messages that arrive together (e.g., forwarded text + photo).
"""

import asyncio

import pytest


class TestNormalizationTrackerBasic:
    """Basic tracker functionality tests."""

    @pytest.mark.asyncio
    async def test_tracker_initialization(self) -> None:
        """Tracker initializes empty."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()

        assert tracker.get_stats()["total_chats"] == 0
        assert tracker.get_stats()["total_pending"] == 0

    @pytest.mark.asyncio
    async def test_start_tracking(self) -> None:
        """Start adds message to pending."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)

        assert tracker.has_pending(123)
        assert tracker.get_pending_count(123) == 1

    @pytest.mark.asyncio
    async def test_finish_tracking(self) -> None:
        """Finish removes message from pending."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)
        await tracker.finish(chat_id=123, message_id=100)

        assert not tracker.has_pending(123)
        assert tracker.get_pending_count(123) == 0

    @pytest.mark.asyncio
    async def test_multiple_messages_same_chat(self) -> None:
        """Multiple messages in same chat tracked separately."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)
        await tracker.start(chat_id=123, message_id=101)

        assert tracker.get_pending_count(123) == 2

        await tracker.finish(chat_id=123, message_id=100)
        assert tracker.get_pending_count(123) == 1

        await tracker.finish(chat_id=123, message_id=101)
        assert tracker.get_pending_count(123) == 0

    @pytest.mark.asyncio
    async def test_separate_chats(self) -> None:
        """Messages in different chats tracked independently."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)
        await tracker.start(chat_id=456, message_id=200)

        assert tracker.has_pending(123)
        assert tracker.has_pending(456)
        assert tracker.get_stats()["total_chats"] == 2


class TestNormalizationTrackerWaiting:
    """Tests for wait functionality."""

    @pytest.mark.asyncio
    async def test_wait_returns_immediately_if_no_pending(self) -> None:
        """Wait returns immediately when no pending messages."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()

        # Should return immediately
        result = await tracker.wait_for_chat(chat_id=123, timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_blocks_until_finished(self) -> None:
        """Wait blocks until all messages finish."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)

        # Start wait in background
        wait_task = asyncio.create_task(
            tracker.wait_for_chat(chat_id=123, timeout=5.0))

        # Give wait time to start
        await asyncio.sleep(0.01)
        assert not wait_task.done()

        # Finish the message
        await tracker.finish(chat_id=123, message_id=100)

        # Wait should complete now
        result = await asyncio.wait_for(wait_task, timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_timeout(self) -> None:
        """Wait returns False on timeout."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)

        # Wait with short timeout
        result = await tracker.wait_for_chat(chat_id=123, timeout=0.1)
        assert result is False

        # Clean up
        await tracker.finish(chat_id=123, message_id=100)

    @pytest.mark.asyncio
    async def test_wait_for_multiple_messages(self) -> None:
        """Wait waits for ALL messages in chat."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)
        await tracker.start(chat_id=123, message_id=101)

        # Start wait in background
        wait_task = asyncio.create_task(
            tracker.wait_for_chat(chat_id=123, timeout=5.0))

        await asyncio.sleep(0.01)
        assert not wait_task.done()

        # Finish first message - should still be waiting
        await tracker.finish(chat_id=123, message_id=100)
        await asyncio.sleep(0.01)
        assert not wait_task.done()

        # Finish second message - now should complete
        await tracker.finish(chat_id=123, message_id=101)
        result = await asyncio.wait_for(wait_task, timeout=1.0)
        assert result is True


class TestNormalizationTrackerConcurrency:
    """Tests for concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_start_finish(self) -> None:
        """Concurrent start/finish operations are safe."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()

        async def worker(msg_id: int) -> None:
            await tracker.start(chat_id=123, message_id=msg_id)
            await asyncio.sleep(0.01)
            await tracker.finish(chat_id=123, message_id=msg_id)

        # Run multiple workers concurrently
        await asyncio.gather(*[worker(i) for i in range(10)])

        # All should be done
        assert not tracker.has_pending(123)

    @pytest.mark.asyncio
    async def test_multiple_waiters(self) -> None:
        """Multiple waiters all get notified."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)

        # Create multiple waiters
        wait_tasks = [
            asyncio.create_task(tracker.wait_for_chat(chat_id=123, timeout=5.0))
            for _ in range(3)
        ]

        await asyncio.sleep(0.01)

        # Finish the message
        await tracker.finish(chat_id=123, message_id=100)

        # All waiters should complete
        results = await asyncio.gather(*wait_tasks)
        assert all(r is True for r in results)


class TestNormalizationTrackerEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_finish_nonexistent_message(self) -> None:
        """Finish on non-existent message is safe."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()

        # Should not raise
        await tracker.finish(chat_id=123, message_id=100)

    @pytest.mark.asyncio
    async def test_finish_nonexistent_chat(self) -> None:
        """Finish on non-existent chat is safe."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        await tracker.start(chat_id=123, message_id=100)

        # Finish wrong chat - should not raise
        await tracker.finish(chat_id=456, message_id=100)

        # Original should still be pending
        assert tracker.has_pending(123)

        # Clean up
        await tracker.finish(chat_id=123, message_id=100)

    @pytest.mark.asyncio
    async def test_has_pending_empty_chat(self) -> None:
        """has_pending returns False for unknown chat."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        assert not tracker.has_pending(999)

    @pytest.mark.asyncio
    async def test_get_pending_count_empty_chat(self) -> None:
        """get_pending_count returns 0 for unknown chat."""
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = NormalizationTracker()
        assert tracker.get_pending_count(999) == 0


class TestNormalizationTrackerSingleton:
    """Tests for singleton behavior."""

    def test_get_tracker_returns_same_instance(self) -> None:
        """get_tracker returns singleton."""
        # Reset singleton for test
        import telegram.pipeline.tracker as tracker_module
        tracker_module._tracker = None

        from telegram.pipeline.tracker import get_tracker

        t1 = get_tracker()
        t2 = get_tracker()
        assert t1 is t2

    def test_get_tracker_returns_tracker_type(self) -> None:
        """get_tracker returns NormalizationTracker."""
        from telegram.pipeline.tracker import get_tracker
        from telegram.pipeline.tracker import NormalizationTracker

        tracker = get_tracker()
        assert isinstance(tracker, NormalizationTracker)
