"""Integration tests for MessageQueueManager (Phase 1.6).

Tests message batching with universal media architecture:
- MediaContent integration for all media types
- Immediate processing for media (no batching delay)
- Time-based split detection for text (200ms window)
- Per-thread independent queues
- Processing states and retry logic
"""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from core.message_queue import MessageBatch
from core.message_queue import MessageQueueManager
import pytest
from telegram.media_processor import MediaContent
from telegram.media_processor import MediaType


@pytest.fixture
def mock_message():
    """Create mock Telegram message."""
    message = MagicMock()
    message.text = "Test message"
    message.message_id = 12345
    return message


@pytest.fixture
def mock_process_callback():
    """Create mock process callback."""
    return AsyncMock()


@pytest.fixture
def queue_manager(mock_process_callback):
    """Create MessageQueueManager instance."""
    return MessageQueueManager(mock_process_callback)


# ============================================================================
# MessageBatch Tests
# ============================================================================


def test_message_batch_initialization():
    """Test MessageBatch dataclass initialization."""
    batch = MessageBatch()

    assert batch.messages == []
    assert batch.processing is False
    assert batch.timer_task is None


def test_message_batch_with_messages():
    """Test MessageBatch with messages."""
    message = MagicMock()
    media = MediaContent(type=MediaType.VOICE, text_content="transcript")

    batch = MessageBatch(messages=[(message, media)], processing=True)

    assert len(batch.messages) == 1
    assert batch.messages[0][0] is message
    assert batch.messages[0][1] is media
    assert batch.processing is True


# ============================================================================
# MessageQueueManager Initialization Tests
# ============================================================================


def test_queue_manager_initialization(queue_manager, mock_process_callback):
    """Test MessageQueueManager initialization."""
    assert queue_manager.queues == {}
    assert queue_manager.process_callback is mock_process_callback


def test_get_or_create_queue(queue_manager):
    """Test queue creation for new thread."""
    thread_id = 42

    # Get queue (creates new)
    queue = queue_manager._get_or_create_queue(thread_id)

    assert isinstance(queue, MessageBatch)
    assert thread_id in queue_manager.queues
    assert queue_manager.queues[thread_id] is queue


def test_get_or_create_queue_returns_existing(queue_manager):
    """Test that get_or_create_queue returns existing queue."""
    thread_id = 42

    # Create queue
    queue1 = queue_manager._get_or_create_queue(thread_id)

    # Get same queue
    queue2 = queue_manager._get_or_create_queue(thread_id)

    assert queue1 is queue2


# ============================================================================
# MediaContent Integration Tests (Phase 1.6)
# ============================================================================


@pytest.mark.asyncio
async def test_add_message_with_media_content_immediate(queue_manager,
                                                        mock_message,
                                                        mock_process_callback):
    """Test immediate processing for media messages.

    Media messages should process WITHOUT 200ms batching delay.
    """
    thread_id = 1
    media_content = MediaContent(type=MediaType.VOICE,
                                 text_content="Hello world",
                                 metadata={"duration": 5})

    # Add media message with immediate=True
    await queue_manager.add_message(thread_id,
                                    mock_message,
                                    media_content=media_content,
                                    immediate=True)

    # Should process immediately (no delay)
    mock_process_callback.assert_called_once()
    call_args = mock_process_callback.call_args[0]

    assert call_args[0] == thread_id
    assert len(call_args[1]) == 1
    assert call_args[1][0][0] is mock_message
    assert call_args[1][0][1] is media_content


@pytest.mark.asyncio
async def test_add_message_text_with_batching_delay(queue_manager, mock_message,
                                                    mock_process_callback):
    """Test 200ms batching delay for text messages.

    Text messages should wait 200ms for potential split parts.
    """
    thread_id = 1

    # Add text message (immediate=False)
    await queue_manager.add_message(thread_id,
                                    mock_message,
                                    media_content=None,
                                    immediate=False)

    # Should NOT process immediately
    mock_process_callback.assert_not_called()

    # Wait for 200ms timer
    await asyncio.sleep(0.25)

    # Now should process
    mock_process_callback.assert_called_once()


@pytest.mark.asyncio
async def test_mixed_batch_media_and_text(queue_manager, mock_process_callback):
    """Test batch with both media and text messages."""
    thread_id = 1

    # Add text message first
    msg1 = MagicMock()
    msg1.text = "Text message"
    await queue_manager.add_message(thread_id, msg1, immediate=False)

    # Add media message (should trigger immediate processing)
    msg2 = MagicMock()
    media = MediaContent(type=MediaType.IMAGE, file_id="file_abc123")
    await queue_manager.add_message(thread_id,
                                    msg2,
                                    media_content=media,
                                    immediate=True)

    # Should process both messages together
    mock_process_callback.assert_called_once()
    call_args = mock_process_callback.call_args[0]

    assert call_args[0] == thread_id
    assert len(call_args[1]) == 2
    assert call_args[1][0][0] is msg1
    assert call_args[1][0][1] is None  # No media
    assert call_args[1][1][0] is msg2
    assert call_args[1][1][1] is media


@pytest.mark.asyncio
async def test_media_types_integration(queue_manager, mock_process_callback):
    """Test all media types pass through correctly."""
    thread_id = 1

    # Voice message
    msg_voice = MagicMock()
    media_voice = MediaContent(type=MediaType.VOICE,
                               text_content="Voice transcript")

    await queue_manager.add_message(thread_id,
                                    msg_voice,
                                    media_content=media_voice,
                                    immediate=True)

    # Verify voice MediaContent passed
    call_args = mock_process_callback.call_args[0]
    assert call_args[1][0][1].type == MediaType.VOICE
    assert call_args[1][0][1].text_content == "Voice transcript"

    mock_process_callback.reset_mock()

    # Image message
    msg_image = MagicMock()
    media_image = MediaContent(type=MediaType.IMAGE, file_id="file_img")

    await queue_manager.add_message(thread_id,
                                    msg_image,
                                    media_content=media_image,
                                    immediate=True)

    # Verify image MediaContent passed
    call_args = mock_process_callback.call_args[0]
    assert call_args[1][0][1].type == MediaType.IMAGE
    assert call_args[1][0][1].file_id == "file_img"


# ============================================================================
# Batching Logic Tests
# ============================================================================


@pytest.mark.asyncio
async def test_split_message_accumulation(queue_manager, mock_process_callback):
    """Test split message detection with timer cancellation.

    When multiple messages arrive < 200ms apart, should accumulate them.
    """
    thread_id = 1

    # Add first part
    msg1 = MagicMock()
    msg1.text = "Part 1"
    await queue_manager.add_message(thread_id, msg1, immediate=False)

    # Wait 50ms
    await asyncio.sleep(0.05)

    # Add second part (should cancel first timer)
    msg2 = MagicMock()
    msg2.text = "Part 2"
    await queue_manager.add_message(thread_id, msg2, immediate=False)

    # Wait 50ms
    await asyncio.sleep(0.05)

    # Add third part
    msg3 = MagicMock()
    msg3.text = "Part 3"
    await queue_manager.add_message(thread_id, msg3, immediate=False)

    # Should not have processed yet (timers cancelled)
    mock_process_callback.assert_not_called()

    # Wait for final timer (200ms from last message + buffer for async processing)
    await asyncio.sleep(0.25)

    # Should process all 3 messages together
    mock_process_callback.assert_called_once()
    call_args = mock_process_callback.call_args[0]
    assert len(call_args[1]) == 3


@pytest.mark.asyncio
async def test_timer_cancellation_on_immediate(queue_manager,
                                               mock_process_callback):
    """Test that immediate message cancels pending timer.

    Media message should cancel text message timer and process immediately.
    """
    thread_id = 1

    # Add text message (starts 200ms timer)
    msg_text = MagicMock()
    msg_text.text = "Text"
    await queue_manager.add_message(thread_id, msg_text, immediate=False)

    # Wait 50ms (timer still pending)
    await asyncio.sleep(0.05)

    # Add media message (should cancel timer and process immediately)
    msg_media = MagicMock()
    media = MediaContent(type=MediaType.AUDIO, text_content="Transcript")
    await queue_manager.add_message(thread_id,
                                    msg_media,
                                    media_content=media,
                                    immediate=True)

    # Should process immediately with both messages
    mock_process_callback.assert_called_once()
    call_args = mock_process_callback.call_args[0]
    assert len(call_args[1]) == 2


# ============================================================================
# Processing State Tests
# ============================================================================


@pytest.mark.asyncio
async def test_accumulation_during_processing(queue_manager,
                                              mock_process_callback):
    """Test message accumulation while processing is active.

    New messages should accumulate and process after current batch completes.
    """
    thread_id = 1

    # Make process_callback block for 100ms
    async def slow_process(*args):
        await asyncio.sleep(0.1)

    mock_process_callback.side_effect = slow_process

    # Add first message (starts processing)
    msg1 = MagicMock()
    await queue_manager.add_message(thread_id, msg1, immediate=True)

    # Immediately add second message (should accumulate)
    msg2 = MagicMock()
    await queue_manager.add_message(thread_id, msg2, immediate=True)

    # Wait for both batches to process
    await asyncio.sleep(0.3)

    # Should have called twice (first batch, then second batch)
    assert mock_process_callback.call_count == 2

    # First call: msg1
    first_call = mock_process_callback.call_args_list[0][0]
    assert len(first_call[1]) == 1
    assert first_call[1][0][0] is msg1

    # Second call: msg2
    second_call = mock_process_callback.call_args_list[1][0]
    assert len(second_call[1]) == 1
    assert second_call[1][0][0] is msg2


@pytest.mark.asyncio
async def test_multiple_accumulation_during_processing(queue_manager,
                                                       mock_process_callback):
    """Test multiple messages accumulate during processing.

    All accumulated messages should process together in next batch.
    """
    thread_id = 1

    # Make process_callback block
    async def slow_process(*args):
        await asyncio.sleep(0.1)

    mock_process_callback.side_effect = slow_process

    # Start processing
    msg1 = MagicMock()
    await queue_manager.add_message(thread_id, msg1, immediate=True)

    # Add multiple messages during processing
    msg2 = MagicMock()
    msg3 = MagicMock()
    msg4 = MagicMock()
    await queue_manager.add_message(thread_id, msg2, immediate=False)
    await queue_manager.add_message(thread_id, msg3, immediate=False)
    await queue_manager.add_message(thread_id, msg4, immediate=True)

    # Wait for processing
    await asyncio.sleep(0.3)

    # Should have two batches
    assert mock_process_callback.call_count == 2

    # Second batch should have msg2, msg3, msg4
    second_call = mock_process_callback.call_args_list[1][0]
    assert len(second_call[1]) == 3


# ============================================================================
# Retry Logic Tests
# ============================================================================


@pytest.mark.asyncio
async def test_retry_on_processing_failure(queue_manager,
                                           mock_process_callback):
    """Test batch retry on processing failure.

    Should retry once, then give up if still fails.
    """
    thread_id = 1

    # Make first call fail, second succeed
    mock_process_callback.side_effect = [Exception("Failed"), None]

    # Add message
    msg = MagicMock()
    await queue_manager.add_message(thread_id, msg, immediate=True)

    # Wait for processing + retry
    await asyncio.sleep(0.1)

    # Should have called twice (original + retry)
    assert mock_process_callback.call_count == 2


@pytest.mark.asyncio
async def test_retry_failure_stops_after_one(queue_manager,
                                             mock_process_callback):
    """Test that retry stops after one failure.

    Should not infinitely retry.
    """
    thread_id = 1

    # Make all calls fail
    mock_process_callback.side_effect = Exception("Always fails")

    # Add message
    msg = MagicMock()
    await queue_manager.add_message(thread_id, msg, immediate=True)

    # Wait for processing + retry
    await asyncio.sleep(0.1)

    # Should have called twice (original + one retry)
    assert mock_process_callback.call_count == 2


# ============================================================================
# Multi-thread Tests
# ============================================================================


@pytest.mark.asyncio
async def test_multiple_threads_independent(queue_manager,
                                            mock_process_callback):
    """Test that different threads have independent queues.

    Messages from different threads should not interfere.
    """
    thread_id_1 = 1
    thread_id_2 = 2

    # Add messages to both threads
    msg1 = MagicMock()
    msg1.text = "Thread 1"
    await queue_manager.add_message(thread_id_1, msg1, immediate=True)

    msg2 = MagicMock()
    msg2.text = "Thread 2"
    await queue_manager.add_message(thread_id_2, msg2, immediate=True)

    # Both should process independently
    assert mock_process_callback.call_count == 2

    # Verify thread IDs
    call_1 = mock_process_callback.call_args_list[0][0]
    call_2 = mock_process_callback.call_args_list[1][0]

    assert call_1[0] == thread_id_1
    assert call_2[0] == thread_id_2


@pytest.mark.asyncio
async def test_concurrent_processing_different_threads(queue_manager,
                                                       mock_process_callback):
    """Test concurrent processing of different threads.

    Multiple threads should be able to process simultaneously.
    """
    thread_id_1 = 1
    thread_id_2 = 2

    # Make processing slow
    async def slow_process(*args):
        await asyncio.sleep(0.05)

    mock_process_callback.side_effect = slow_process

    # Start processing both threads concurrently
    msg1 = MagicMock()
    msg2 = MagicMock()

    await asyncio.gather(
        queue_manager.add_message(thread_id_1, msg1, immediate=True),
        queue_manager.add_message(thread_id_2, msg2, immediate=True))

    # Wait for processing
    await asyncio.sleep(0.15)

    # Both should have processed
    assert mock_process_callback.call_count == 2


# ============================================================================
# get_stats() Tests
# ============================================================================


def test_get_stats_empty(queue_manager):
    """Test get_stats with no queues."""
    stats = queue_manager.get_stats()

    assert stats['total_threads'] == 0
    assert stats['processing_threads'] == 0
    assert stats['waiting_threads'] == 0


@pytest.mark.asyncio
async def test_get_stats_with_queues(queue_manager):
    """Test get_stats with active queues."""
    # Create multiple queues
    queue_manager._get_or_create_queue(1)
    queue_manager._get_or_create_queue(2)
    queue_manager._get_or_create_queue(3)

    # Mark some as processing
    queue_manager.queues[1].processing = True
    queue_manager.queues[2].processing = True

    # Add messages to some
    msg = MagicMock()
    queue_manager.queues[2].messages.append((msg, None))
    queue_manager.queues[3].messages.append((msg, None))

    stats = queue_manager.get_stats()

    assert stats['total_threads'] == 3
    assert stats['processing_threads'] == 2
    assert stats['waiting_threads'] == 2  # Queue 2 and 3 have messages


# ============================================================================
# Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_empty_batch_handling(queue_manager, mock_process_callback):
    """Test that empty batches are handled gracefully.

    Should log warning and not call process_callback.
    """
    thread_id = 1

    # Manually trigger empty batch (edge case)
    await queue_manager._process_batch(thread_id, [])

    # Should not call process_callback
    mock_process_callback.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_timer_during_wait(queue_manager):
    """Test timer cancellation during sleep.

    Should handle CancelledError gracefully.
    """
    thread_id = 1

    # Start timer
    msg = MagicMock()
    await queue_manager.add_message(thread_id, msg, immediate=False)

    queue = queue_manager.queues[thread_id]
    timer_task = queue.timer_task

    # Cancel timer during wait
    await asyncio.sleep(0.05)
    timer_task.cancel()

    # Wait for cancellation
    await asyncio.sleep(0.05)

    # Should handle gracefully (no exception raised)
