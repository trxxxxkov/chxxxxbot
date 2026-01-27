"""Tests for concurrency_limiter module.

Tests the UserConcurrencyLimiter class and concurrency_context context manager.
"""

import asyncio

import pytest
from telegram.concurrency_limiter import concurrency_context
from telegram.concurrency_limiter import ConcurrencyLimitExceeded
from telegram.concurrency_limiter import UserConcurrencyLimiter


class TestUserConcurrencyLimiter:
    """Tests for UserConcurrencyLimiter class."""

    @pytest.fixture
    def limiter(self) -> UserConcurrencyLimiter:
        """Create a fresh limiter for each test with small limits."""
        return UserConcurrencyLimiter(max_concurrent=2, queue_timeout=1.0)

    @pytest.mark.asyncio
    async def test_acquire_returns_zero_when_available(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that acquire returns queue_position=0 when slot available."""
        async with limiter.acquire(user_id=123, thread_id=1) as queue_pos:
            assert queue_pos == 0

    @pytest.mark.asyncio
    async def test_acquire_increments_active_count(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that acquire increments active count."""
        async with limiter.acquire(user_id=123, thread_id=1):
            count = await limiter.get_active_count(123)
            assert count == 1

    @pytest.mark.asyncio
    async def test_release_decrements_active_count(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that release decrements active count."""
        async with limiter.acquire(user_id=123, thread_id=1):
            pass

        count = await limiter.get_active_count(123)
        assert count == 0

    @pytest.mark.asyncio
    async def test_multiple_acquires_within_limit(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that multiple acquires work within limit."""
        async with limiter.acquire(user_id=123, thread_id=1) as pos1:
            async with limiter.acquire(user_id=123, thread_id=2) as pos2:
                # Both should get immediate access (limit is 2)
                assert pos1 == 0
                assert pos2 == 0

                count = await limiter.get_active_count(123)
                assert count == 2

    @pytest.mark.asyncio
    async def test_acquire_blocks_when_at_limit(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that third acquire blocks when at limit of 2."""
        acquired_third = asyncio.Event()
        third_position = None

        async def acquire_third():
            nonlocal third_position
            async with limiter.acquire(user_id=123, thread_id=3) as pos:
                third_position = pos
                acquired_third.set()

        async with limiter.acquire(user_id=123, thread_id=1):
            async with limiter.acquire(user_id=123, thread_id=2):
                # Start third acquisition (should block)
                task = asyncio.create_task(acquire_third())

                # Give it a moment - should NOT acquire yet
                await asyncio.sleep(0.1)
                assert not acquired_third.is_set()

            # Second slot released - third should acquire now
            await asyncio.wait_for(acquired_third.wait(), timeout=1.0)
            assert third_position == 1  # Was queued

        await task  # Clean up task

    @pytest.mark.asyncio
    async def test_acquire_timeout_raises_exception(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that acquire raises ConcurrencyLimitExceeded on timeout."""
        async with limiter.acquire(user_id=123, thread_id=1):
            async with limiter.acquire(user_id=123, thread_id=2):
                # Third should timeout
                with pytest.raises(ConcurrencyLimitExceeded) as exc_info:
                    async with limiter.acquire(user_id=123, thread_id=3):
                        pass  # Should not reach here

                assert exc_info.value.user_id == 123
                assert exc_info.value.queue_position == 1

    @pytest.mark.asyncio
    async def test_different_users_tracked_separately(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that different users have separate limits."""
        async with limiter.acquire(user_id=1, thread_id=1):
            async with limiter.acquire(user_id=1, thread_id=2):
                # User 1 at limit, but user 2 should be fine
                async with limiter.acquire(user_id=2, thread_id=1) as pos:
                    assert pos == 0  # Immediate access

                    count1 = await limiter.get_active_count(1)
                    count2 = await limiter.get_active_count(2)
                    assert count1 == 2
                    assert count2 == 1

    @pytest.mark.asyncio
    async def test_queue_position_tracking(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that queue position is accurately reported."""
        # With max_concurrent=2, third request should be position 1
        pos = await limiter.get_queue_position(123)
        assert pos == 0  # No activity

        async with limiter.acquire(user_id=123, thread_id=1):
            pos = await limiter.get_queue_position(123)
            assert pos == 0  # Still has capacity

            async with limiter.acquire(user_id=123, thread_id=2):
                pos = await limiter.get_queue_position(123)
                assert pos == 1  # At capacity, next would be position 1

    @pytest.mark.asyncio
    async def test_get_stats(self, limiter: UserConcurrencyLimiter) -> None:
        """Test get_stats returns correct information."""
        stats = limiter.get_stats()

        assert stats["max_concurrent_per_user"] == 2
        assert stats["queue_timeout"] == 1.0
        assert stats["total_users_tracked"] == 0
        assert stats["total_active_generations"] == 0

        async with limiter.acquire(user_id=123, thread_id=1):
            stats = limiter.get_stats()
            assert stats["total_users_tracked"] == 1
            assert stats["total_active_generations"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_on_exception(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that slot is released even on exception."""
        with pytest.raises(ValueError):
            async with limiter.acquire(user_id=123, thread_id=1):
                raise ValueError("Test error")

        # Should be cleaned up
        count = await limiter.get_active_count(123)
        assert count == 0

    @pytest.mark.asyncio
    async def test_cancellation_releases_slot(
            self, limiter: UserConcurrencyLimiter) -> None:
        """Test that cancelled task releases slot."""

        async def long_running():
            async with limiter.acquire(user_id=123, thread_id=1):
                await asyncio.sleep(10)  # Will be cancelled

        task = asyncio.create_task(long_running())
        await asyncio.sleep(0.1)  # Let it acquire

        count = await limiter.get_active_count(123)
        assert count == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Give cleanup a moment
        await asyncio.sleep(0.1)

        count = await limiter.get_active_count(123)
        assert count == 0


class TestConcurrencyContext:
    """Tests for concurrency_context context manager."""

    @pytest.mark.asyncio
    async def test_context_yields_queue_position(self) -> None:
        """Test that context manager yields queue position."""
        async with concurrency_context(user_id=123, thread_id=1) as pos:
            assert isinstance(pos, int)
            assert pos == 0  # First request, immediate

    @pytest.mark.asyncio
    async def test_context_uses_global_limiter(self) -> None:
        """Test that context uses global limiter singleton."""
        from telegram.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()
        initial_processed = limiter.get_stats()["total_processed"]

        async with concurrency_context(user_id=999, thread_id=1):
            pass

        final_processed = limiter.get_stats()["total_processed"]
        assert final_processed == initial_processed + 1

    @pytest.mark.asyncio
    async def test_context_cleanup_on_exception(self) -> None:
        """Test that cleanup happens on exception."""
        from telegram.concurrency_limiter import get_concurrency_limiter

        limiter = get_concurrency_limiter()

        with pytest.raises(ValueError):
            async with concurrency_context(user_id=998, thread_id=1):
                count = await limiter.get_active_count(998)
                assert count == 1
                raise ValueError("Test")

        count = await limiter.get_active_count(998)
        assert count == 0


class TestConcurrencyLimitExceeded:
    """Tests for ConcurrencyLimitExceeded exception."""

    def test_exception_attributes(self) -> None:
        """Test that exception has correct attributes."""
        exc = ConcurrencyLimitExceeded(
            user_id=123,
            queue_position=5,
            wait_time=30.5,
        )

        assert exc.user_id == 123
        assert exc.queue_position == 5
        assert exc.wait_time == 30.5

    def test_exception_message(self) -> None:
        """Test that exception has meaningful message."""
        exc = ConcurrencyLimitExceeded(
            user_id=123,
            queue_position=5,
            wait_time=30.5,
        )

        assert "123" in str(exc)
        assert "5" in str(exc)
        assert "30.5" in str(exc)
