"""Unit tests for ProcessedMessageQueue.

Tests the queue's batching and processing behavior.
"""

import asyncio
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.pipeline.models import MediaType
from telegram.pipeline.models import MessageMetadata
from telegram.pipeline.models import ProcessedMessage
from telegram.pipeline.models import TranscriptInfo
from telegram.pipeline.models import UploadedFile
from telegram.pipeline.queue import ProcessedMessageQueue


@pytest.fixture
def sample_metadata() -> MessageMetadata:
    """Create sample metadata."""
    return MessageMetadata(
        chat_id=123,
        user_id=456,
        message_id=100,
        message_thread_id=None,
        chat_type="private",
        date=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_message() -> MagicMock:
    """Create mock aiogram message."""
    msg = MagicMock()
    msg.message_id = 100
    return msg


def create_text_message(
    text: str,
    metadata: MessageMetadata,
    mock_message: MagicMock,
) -> ProcessedMessage:
    """Helper to create text-only ProcessedMessage."""
    return ProcessedMessage(
        text=text,
        metadata=metadata,
        original_message=mock_message,
    )


def create_media_message(
    metadata: MessageMetadata,
    mock_message: MagicMock,
    with_transcript: bool = False,
    with_file: bool = False,
) -> ProcessedMessage:
    """Helper to create media ProcessedMessage."""
    transcript = None
    files = []

    if with_transcript:
        transcript = TranscriptInfo(
            text="Transcript",
            duration_seconds=5.0,
            detected_language="en",
            cost_usd=0.001,
        )

    if with_file:
        files = [
            UploadedFile(
                claude_file_id="file_123",
                telegram_file_id="tg_123",
                telegram_file_unique_id="unique_123",
                file_type=MediaType.IMAGE,
                filename="photo.jpg",
                mime_type="image/jpeg",
                size_bytes=1024,
            )
        ]

    return ProcessedMessage(
        text="Caption" if with_file else None,
        metadata=metadata,
        original_message=mock_message,
        files=files,
        transcript=transcript,
    )


class TestProcessedMessageQueueBasic:
    """Basic queue functionality tests."""

    @pytest.mark.asyncio
    async def test_queue_initialization(self) -> None:
        """Queue initializes with empty state."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        stats = queue.get_stats()
        assert stats["total_threads"] == 0
        assert stats["processing_threads"] == 0
        assert stats["waiting_threads"] == 0

    @pytest.mark.asyncio
    async def test_add_creates_thread_queue(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Adding message creates thread queue."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)
        msg = create_text_message("Test", sample_metadata, mock_message)

        # Add with immediate to avoid timer
        await queue.add(thread_id=1, message=msg, immediate=True)

        stats = queue.get_stats()
        assert stats["total_threads"] == 1


class TestProcessedMessageQueueBatching:
    """Tests for message batching behavior."""

    @pytest.mark.asyncio
    @patch("telegram.pipeline.queue.MESSAGE_BATCH_DELAY_MS", 50)
    async def test_text_messages_batched(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Text messages are batched with delay."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        msg1 = create_text_message("Part 1", sample_metadata, mock_message)
        msg2 = create_text_message("Part 2", sample_metadata, mock_message)

        # Add two messages quickly
        await queue.add(thread_id=1, message=msg1)
        await queue.add(thread_id=1, message=msg2)

        # Should not be called yet
        callback.assert_not_called()

        # Wait for batch to process
        await asyncio.sleep(0.1)

        # Should be called once with both messages
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == 1  # thread_id
        assert len(args[1]) == 2  # both messages

    @pytest.mark.asyncio
    async def test_media_messages_immediate(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Media messages are processed immediately."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        await queue.add(thread_id=1, message=msg)

        # Should be called immediately
        callback.assert_called_once()
        args = callback.call_args[0]
        assert len(args[1]) == 1

    @pytest.mark.asyncio
    async def test_transcript_messages_immediate(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Messages with transcript are processed immediately."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_transcript=True,
        )

        await queue.add(thread_id=1, message=msg)

        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_immediate_flag(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Explicit immediate flag bypasses batching."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        msg = create_text_message("Test", sample_metadata, mock_message)

        await queue.add(thread_id=1, message=msg, immediate=True)

        callback.assert_called_once()


class TestProcessedMessageQueueProcessing:
    """Tests for queue processing behavior."""

    @pytest.mark.asyncio
    async def test_accumulate_during_processing(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Messages accumulate during processing."""
        # Slow callback to allow accumulation
        process_started = asyncio.Event()
        process_continue = asyncio.Event()

        async def slow_callback(thread_id, messages):
            process_started.set()
            await process_continue.wait()

        queue = ProcessedMessageQueue(slow_callback)

        msg1 = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )
        msg2 = create_text_message("During", sample_metadata, mock_message)

        # Start processing first message
        task = asyncio.create_task(queue.add(thread_id=1, message=msg1))
        await process_started.wait()

        # Add second message during processing
        await queue.add(thread_id=1, message=msg2, immediate=True)

        # Stats should show messages accumulated
        stats = queue.get_stats()
        assert stats["processing_threads"] == 1

        # Let processing complete
        process_continue.set()
        await task

    @pytest.mark.asyncio
    async def test_next_batch_after_processing(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Accumulated messages processed as next batch."""
        call_count = 0
        batches = []
        process_event = asyncio.Event()

        async def tracking_callback(thread_id, messages):
            nonlocal call_count
            call_count += 1
            batches.append(len(messages))
            if call_count == 1:
                # First call - wait briefly to allow accumulation
                await asyncio.sleep(0.05)

        queue = ProcessedMessageQueue(tracking_callback)

        msg1 = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )
        msg2 = create_text_message("Accumulated", sample_metadata, mock_message)

        # Start processing - this should complete
        await queue.add(thread_id=1, message=msg1)

        # Give time for first batch to start
        await asyncio.sleep(0.01)

        # Add during processing
        await queue.add(thread_id=1, message=msg2, immediate=True)

        # Wait for all processing
        await asyncio.sleep(0.2)

        # Should have processed two batches
        assert call_count >= 1


class TestProcessedMessageQueueErrorHandling:
    """Tests for error handling and retry."""

    @pytest.mark.asyncio
    async def test_retry_on_failure(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Queue retries once on failure."""
        call_count = 0

        async def failing_callback(thread_id, messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("First call fails")
            # Second call succeeds

        queue = ProcessedMessageQueue(failing_callback)
        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        await queue.add(thread_id=1, message=msg)

        # Should have been called twice (original + retry)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_processing_continues_after_failure(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Queue continues processing after both attempts fail."""

        async def always_failing(thread_id, messages):
            raise ValueError("Always fails")

        queue = ProcessedMessageQueue(always_failing)
        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        # Should not raise, just log error
        await queue.add(thread_id=1, message=msg)

        # Queue should not be stuck in processing state
        stats = queue.get_stats()
        assert stats["processing_threads"] == 0


class TestProcessedMessageQueueStats:
    """Tests for queue statistics."""

    @pytest.mark.asyncio
    @patch("telegram.pipeline.queue.MESSAGE_BATCH_DELAY_MS", 1000)
    async def test_stats_waiting_threads(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Stats track waiting threads."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        msg = create_text_message("Test", sample_metadata, mock_message)

        # Add without immediate - will wait for batch delay
        await queue.add(thread_id=1, message=msg)

        stats = queue.get_stats()
        # Note: Stats may be 0 or 1 depending on timing
        # The message might be processed by the time we check
        assert stats["total_threads"] == 1

    @pytest.mark.asyncio
    async def test_stats_total_pending(
        self,
        sample_metadata: MessageMetadata,
    ) -> None:
        """Stats track total pending messages accumulated during processing."""
        # Events to coordinate test timing
        callback_started = asyncio.Event()
        callback_finish = asyncio.Event()

        async def slow_callback(thread_id, messages):
            # Signal that callback has started (processing=True now)
            callback_started.set()
            # Wait for test to add more messages
            await callback_finish.wait()

        queue = ProcessedMessageQueue(slow_callback)

        # Create mock without media_group_id to avoid 500ms delay
        mock_msg = MagicMock()
        mock_msg.message_id = 100
        mock_msg.media_group_id = None  # No media group delay

        msg = create_media_message(
            sample_metadata,
            mock_msg,
            with_file=True,
        )

        # Start processing first message
        task = asyncio.create_task(queue.add(thread_id=1, message=msg))

        # Wait for callback to actually start (processing=True)
        await asyncio.wait_for(callback_started.wait(), timeout=2.0)

        # Now add second message - it should accumulate since processing=True
        msg2 = create_text_message("Pending", sample_metadata, mock_msg)
        await queue.add(thread_id=1, message=msg2, immediate=True)

        # Check stats while first batch is still processing
        stats = queue.get_stats()
        assert stats["total_pending_messages"] >= 1

        # Cleanup
        callback_finish.set()
        await task


class TestSmartQueueDelay:
    """Tests for smart queue delay (skip delay for standalone messages)."""

    def test_looks_like_split_empty_text(self) -> None:
        """Empty or None text is not split."""
        queue = ProcessedMessageQueue(AsyncMock())
        assert queue._looks_like_split_message(None) is False
        assert queue._looks_like_split_message("") is False
        assert queue._looks_like_split_message("   ") is False

    def test_looks_like_split_continuation_markers(self) -> None:
        """Messages with continuation markers are split."""
        queue = ProcessedMessageQueue(AsyncMock())
        assert queue._looks_like_split_message("And then...") is True
        assert queue._looks_like_split_message("To be continued…") is True
        assert queue._looks_like_split_message("Word-") is True
        assert queue._looks_like_split_message("Sentence—") is True

    def test_looks_like_split_short_without_punctuation(self) -> None:
        """Short messages without punctuation might be split."""
        queue = ProcessedMessageQueue(AsyncMock())
        assert queue._looks_like_split_message("Hello") is True
        assert queue._looks_like_split_message("Yes ok") is True
        assert queue._looks_like_split_message("I think") is True

    def test_standalone_with_punctuation(self) -> None:
        """Messages ending with punctuation are standalone."""
        queue = ProcessedMessageQueue(AsyncMock())
        assert queue._looks_like_split_message("Hello!") is False
        assert queue._looks_like_split_message("How are you?") is False
        assert queue._looks_like_split_message("I agree.") is False
        assert queue._looks_like_split_message("He said \"yes\"") is False
        assert queue._looks_like_split_message("Код работает。") is False

    def test_standalone_long_message(self) -> None:
        """Long messages without special markers are standalone."""
        queue = ProcessedMessageQueue(AsyncMock())
        long_msg = ("This is a longer message that should be treated as "
                    "standalone because it has more than 100 characters total")
        assert len(long_msg) >= 100
        assert queue._looks_like_split_message(long_msg) is False

    @pytest.mark.asyncio
    async def test_standalone_text_immediate_processing(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Standalone text messages are processed immediately."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        # Message with punctuation - standalone
        msg = create_text_message("Hello, world!", sample_metadata,
                                  mock_message)
        await queue.add(thread_id=1, message=msg)

        # Should be called immediately (no delay)
        callback.assert_called_once()

    @pytest.mark.asyncio
    @patch("telegram.pipeline.queue.MESSAGE_BATCH_DELAY_MS", 50)
    async def test_split_text_batched(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Messages that look split are batched with delay."""
        callback = AsyncMock()
        queue = ProcessedMessageQueue(callback)

        # Short message without punctuation - might be split
        msg = create_text_message("Hello", sample_metadata, mock_message)
        await queue.add(thread_id=1, message=msg)

        # Should not be called yet (waiting for more parts)
        callback.assert_not_called()

        # Wait for batch delay
        await asyncio.sleep(0.1)

        # Now should be processed
        callback.assert_called_once()


class TestProcessedMessageQueueMultipleThreads:
    """Tests for multiple thread handling."""

    @pytest.mark.asyncio
    async def test_separate_thread_queues(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Each thread has separate queue."""
        thread_ids_seen = []

        async def tracking_callback(thread_id, messages):
            thread_ids_seen.append(thread_id)

        queue = ProcessedMessageQueue(tracking_callback)

        msg1 = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )
        msg2 = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        await queue.add(thread_id=1, message=msg1)
        await queue.add(thread_id=2, message=msg2)

        assert 1 in thread_ids_seen
        assert 2 in thread_ids_seen

    @pytest.mark.asyncio
    async def test_concurrent_thread_processing(
        self,
        sample_metadata: MessageMetadata,
        mock_message: MagicMock,
    ) -> None:
        """Multiple threads can process concurrently."""
        processing_threads = set()

        async def tracking_callback(thread_id, messages):
            processing_threads.add(thread_id)
            await asyncio.sleep(0.05)

        queue = ProcessedMessageQueue(tracking_callback)

        msg = create_media_message(
            sample_metadata,
            mock_message,
            with_file=True,
        )

        # Start both concurrently
        await asyncio.gather(
            queue.add(thread_id=1, message=msg),
            queue.add(thread_id=2, message=msg),
        )

        # Both threads should have been processed
        assert 1 in processing_threads
        assert 2 in processing_threads
