"""Tests for generation_tracker module.

Tests the GenerationTracker class and generation_context context manager.
"""

import asyncio

import pytest
from telegram.generation_tracker import generation_context
from telegram.generation_tracker import GenerationTracker


class TestGenerationTracker:
    """Tests for GenerationTracker class."""

    @pytest.fixture
    def tracker(self) -> GenerationTracker:
        """Create a fresh tracker for each test."""
        return GenerationTracker()

    @pytest.mark.asyncio
    async def test_start_creates_event(self,
                                       tracker: GenerationTracker) -> None:
        """Test that start() creates an asyncio.Event."""
        event = await tracker.start(chat_id=123, user_id=456)

        assert isinstance(event, asyncio.Event)
        assert not event.is_set()

    @pytest.mark.asyncio
    async def test_start_tracks_generation(self,
                                           tracker: GenerationTracker) -> None:
        """Test that start() adds generation to tracking."""
        await tracker.start(chat_id=123, user_id=456)

        assert tracker.is_active(chat_id=123, user_id=456)
        assert tracker.get_active_count() == 1

    @pytest.mark.asyncio
    async def test_start_overwrites_existing(
            self, tracker: GenerationTracker) -> None:
        """Test that starting new generation overwrites previous."""
        event1 = await tracker.start(chat_id=123, user_id=456)
        event2 = await tracker.start(chat_id=123, user_id=456)

        assert event1 is not event2
        assert tracker.get_active_count() == 1

    @pytest.mark.asyncio
    async def test_cancel_sets_event(self, tracker: GenerationTracker) -> None:
        """Test that cancel() sets the event."""
        event = await tracker.start(chat_id=123, user_id=456)

        result = await tracker.cancel(chat_id=123, user_id=456)

        assert result is True
        assert event.is_set()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(
            self, tracker: GenerationTracker) -> None:
        """Test that cancel() returns False for nonexistent generation."""
        result = await tracker.cancel(chat_id=123, user_id=456)

        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_removes_generation(
            self, tracker: GenerationTracker) -> None:
        """Test that cleanup() removes generation from tracking."""
        await tracker.start(chat_id=123, user_id=456)

        await tracker.cleanup(chat_id=123, user_id=456)

        assert not tracker.is_active(chat_id=123, user_id=456)
        assert tracker.get_active_count() == 0

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_is_safe(
            self, tracker: GenerationTracker) -> None:
        """Test that cleanup() is safe to call on nonexistent generation."""
        # Should not raise
        await tracker.cleanup(chat_id=123, user_id=456)

        assert tracker.get_active_count() == 0

    @pytest.mark.asyncio
    async def test_is_active_returns_false_after_cancel(
            self, tracker: GenerationTracker) -> None:
        """Test that is_active() returns False after cancellation."""
        await tracker.start(chat_id=123, user_id=456)
        await tracker.cancel(chat_id=123, user_id=456)

        # Still in _active dict but event is set
        assert not tracker.is_active(chat_id=123, user_id=456)

    @pytest.mark.asyncio
    async def test_multiple_users_tracked_separately(
            self, tracker: GenerationTracker) -> None:
        """Test that different users are tracked separately."""
        event1 = await tracker.start(chat_id=123, user_id=1)
        event2 = await tracker.start(chat_id=123, user_id=2)

        await tracker.cancel(chat_id=123, user_id=1)

        assert event1.is_set()
        assert not event2.is_set()
        assert tracker.get_active_count() == 2

    @pytest.mark.asyncio
    async def test_multiple_chats_tracked_separately(
            self, tracker: GenerationTracker) -> None:
        """Test that different chats are tracked separately."""
        event1 = await tracker.start(chat_id=100, user_id=1)
        event2 = await tracker.start(chat_id=200, user_id=1)

        await tracker.cancel(chat_id=100, user_id=1)

        assert event1.is_set()
        assert not event2.is_set()


class TestGenerationContext:
    """Tests for generation_context context manager."""

    @pytest.mark.asyncio
    async def test_context_yields_event(self) -> None:
        """Test that context manager yields asyncio.Event."""
        async with generation_context(chat_id=123, user_id=456) as cancel_event:
            assert isinstance(cancel_event, asyncio.Event)
            assert not cancel_event.is_set()

    @pytest.mark.asyncio
    async def test_context_cleans_up_tracker(self) -> None:
        """Test that tracker is cleaned up after context exits."""
        # Import tracker to check state
        from telegram.generation_tracker import generation_tracker

        initial_count = generation_tracker.get_active_count()

        async with generation_context(chat_id=999, user_id=999):
            # Should be tracked during context
            assert generation_tracker.is_active(999, 999)

        # Should be cleaned up after context
        assert generation_tracker.get_active_count() == initial_count

    @pytest.mark.asyncio
    async def test_context_cleanup_on_exception(self) -> None:
        """Test that cleanup happens even on exception."""
        from telegram.generation_tracker import generation_tracker

        initial_count = generation_tracker.get_active_count()

        with pytest.raises(ValueError):
            async with generation_context(chat_id=998, user_id=998):
                raise ValueError("Test error")

        # Should be cleaned up after context despite exception
        assert generation_tracker.get_active_count() == initial_count

    @pytest.mark.asyncio
    async def test_context_cancel_event_works(self) -> None:
        """Test that cancel event can be used to detect cancellation."""
        from telegram.generation_tracker import generation_tracker

        async with generation_context(chat_id=997, user_id=997) as cancel_event:
            # Initially not cancelled
            assert not cancel_event.is_set()

            # Cancel the generation
            await generation_tracker.cancel(997, 997)

            # Now event should be set
            assert cancel_event.is_set()
