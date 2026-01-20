"""Tests for upload tracker.

Tests the PendingUploadTracker class which synchronizes file uploads
with the message queue to prevent race conditions.
"""

import asyncio

from core.upload_tracker import get_upload_tracker
from core.upload_tracker import PendingUploadTracker
import pytest


class TestPendingUploadTracker:
    """Tests for PendingUploadTracker class."""

    @pytest.fixture
    def tracker(self):
        """Create a fresh tracker instance."""
        return PendingUploadTracker()

    @pytest.mark.asyncio
    async def test_no_pending_uploads_returns_immediately(self, tracker):
        """wait_for_uploads returns True immediately when no uploads."""
        result = await tracker.wait_for_uploads(chat_id=123)
        assert result is True

    @pytest.mark.asyncio
    async def test_start_and_finish_upload(self, tracker):
        """Basic start/finish cycle works correctly."""
        chat_id = 123

        # Start upload
        await tracker.start_upload(chat_id)
        assert tracker.has_pending_uploads(chat_id)
        assert tracker.get_pending_count(chat_id) == 1

        # Finish upload
        await tracker.finish_upload(chat_id)
        assert not tracker.has_pending_uploads(chat_id)
        assert tracker.get_pending_count(chat_id) == 0

    @pytest.mark.asyncio
    async def test_multiple_concurrent_uploads(self, tracker):
        """Multiple uploads in same chat are tracked correctly."""
        chat_id = 123

        # Start three uploads
        await tracker.start_upload(chat_id)
        await tracker.start_upload(chat_id)
        await tracker.start_upload(chat_id)

        assert tracker.get_pending_count(chat_id) == 3

        # Finish two
        await tracker.finish_upload(chat_id)
        await tracker.finish_upload(chat_id)

        assert tracker.get_pending_count(chat_id) == 1
        assert tracker.has_pending_uploads(chat_id)

        # Finish last one
        await tracker.finish_upload(chat_id)
        assert not tracker.has_pending_uploads(chat_id)

    @pytest.mark.asyncio
    async def test_different_chats_are_independent(self, tracker):
        """Uploads in different chats don't affect each other."""
        chat_1 = 100
        chat_2 = 200

        await tracker.start_upload(chat_1)
        await tracker.start_upload(chat_2)

        assert tracker.get_pending_count(chat_1) == 1
        assert tracker.get_pending_count(chat_2) == 1

        await tracker.finish_upload(chat_1)

        assert not tracker.has_pending_uploads(chat_1)
        assert tracker.has_pending_uploads(chat_2)

    @pytest.mark.asyncio
    async def test_wait_blocks_until_upload_complete(self, tracker):
        """wait_for_uploads blocks until all uploads complete."""
        chat_id = 123
        completed = False

        async def do_upload():
            nonlocal completed
            await asyncio.sleep(0.1)
            await tracker.finish_upload(chat_id)
            completed = True

        await tracker.start_upload(chat_id)

        # Start upload completion in background
        asyncio.create_task(do_upload())

        # Wait should block until complete
        result = await tracker.wait_for_uploads(chat_id, timeout=1.0)

        assert result is True
        assert completed is True

    @pytest.mark.asyncio
    async def test_wait_timeout(self, tracker):
        """wait_for_uploads returns False on timeout."""
        chat_id = 123

        # Start upload but never finish
        await tracker.start_upload(chat_id)

        # Should timeout
        result = await tracker.wait_for_uploads(chat_id, timeout=0.1)

        assert result is False
        assert tracker.has_pending_uploads(chat_id)

    @pytest.mark.asyncio
    async def test_finish_without_start_is_safe(self, tracker):
        """Finishing without starting doesn't go negative."""
        chat_id = 123

        # Finish without starting (edge case)
        await tracker.finish_upload(chat_id)

        assert tracker.get_pending_count(chat_id) == 0
        assert not tracker.has_pending_uploads(chat_id)

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, tracker):
        """reset() clears all pending uploads for a chat."""
        chat_id = 123

        await tracker.start_upload(chat_id)
        await tracker.start_upload(chat_id)

        assert tracker.get_pending_count(chat_id) == 2

        await tracker.reset(chat_id)

        assert tracker.get_pending_count(chat_id) == 0
        assert not tracker.has_pending_uploads(chat_id)

    @pytest.mark.asyncio
    async def test_reset_unblocks_waiters(self, tracker):
        """reset() unblocks any tasks waiting on uploads."""
        chat_id = 123
        wait_completed = False

        async def wait_for_upload():
            nonlocal wait_completed
            await tracker.wait_for_uploads(chat_id, timeout=5.0)
            wait_completed = True

        await tracker.start_upload(chat_id)

        # Start wait in background
        wait_task = asyncio.create_task(wait_for_upload())

        # Give it a moment to start waiting
        await asyncio.sleep(0.05)

        # Reset should unblock the waiter
        await tracker.reset(chat_id)

        # Wait for the task to complete
        await asyncio.wait_for(wait_task, timeout=1.0)

        assert wait_completed is True


class TestGetUploadTracker:
    """Tests for get_upload_tracker singleton."""

    def test_returns_same_instance(self):
        """get_upload_tracker returns the same instance."""
        tracker1 = get_upload_tracker()
        tracker2 = get_upload_tracker()

        assert tracker1 is tracker2

    def test_returns_pending_upload_tracker(self):
        """get_upload_tracker returns a PendingUploadTracker."""
        tracker = get_upload_tracker()

        assert isinstance(tracker, PendingUploadTracker)
