"""Tests for write_behind module.

Tests the write-behind queue pattern for async database writes.
"""

from datetime import datetime
from datetime import timezone
from decimal import Decimal
import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from cache.write_behind import _auto_replay_dlq
from cache.write_behind import DLQ_MAX_AGE
from cache.write_behind import flush_writes
from cache.write_behind import flush_writes_batch
from cache.write_behind import get_queue_depth
from cache.write_behind import queue_write
from cache.write_behind import write_behind_task
from cache.write_behind import WRITE_DLQ_KEY
from cache.write_behind import WRITE_QUEUE_KEY
from cache.write_behind import WriteType
import pytest


class TestQueueWrite:
    """Tests for queue_write function."""

    @pytest.mark.asyncio
    async def test_queue_write_success(self):
        """Test successful write queuing."""
        mock_redis = AsyncMock()
        mock_redis.rpush = AsyncMock()

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            result = await queue_write(
                WriteType.MESSAGE,
                {
                    "chat_id": 123,
                    "message_id": 456
                },
            )

        assert result is True
        mock_redis.rpush.assert_called_once()

    @pytest.mark.asyncio
    async def test_queue_write_redis_unavailable(self):
        """Test graceful degradation when Redis unavailable."""
        with patch("cache.write_behind.get_redis", return_value=None):
            result = await queue_write(
                WriteType.MESSAGE,
                {"chat_id": 123},
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_queue_write_payload_structure(self):
        """Test queued payload has correct structure."""
        mock_redis = AsyncMock()
        captured_payload = None

        async def capture_rpush(key, payload):
            nonlocal captured_payload
            captured_payload = payload

        mock_redis.rpush = capture_rpush

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            await queue_write(
                WriteType.USER_STATS,
                {
                    "user_id": 123,
                    "messages": 5,
                    "tokens": 1000
                },
            )

        payload = json.loads(captured_payload)
        assert payload["type"] == "user_stats"
        assert payload["data"]["user_id"] == 123
        assert "queued_at" in payload


class TestGetQueueDepth:
    """Tests for get_queue_depth function."""

    @pytest.mark.asyncio
    async def test_get_queue_depth_success(self):
        """Test getting queue depth."""
        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=5)

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            depth = await get_queue_depth()

        assert depth == 5

    @pytest.mark.asyncio
    async def test_get_queue_depth_redis_unavailable(self):
        """Test returns 0 when Redis unavailable."""
        with patch("cache.write_behind.get_redis", return_value=None):
            depth = await get_queue_depth()

        assert depth == 0


class TestFlushWritesBatch:
    """Tests for flush_writes_batch function."""

    @pytest.mark.asyncio
    async def test_flush_writes_batch_empty(self):
        """Test empty queue returns empty list and batch_size."""
        mock_redis = AsyncMock()
        mock_redis.lpop = AsyncMock(return_value=None)
        mock_redis.llen = AsyncMock(return_value=0)

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            writes, batch_size = await flush_writes_batch()

        assert writes == []
        assert batch_size == 100  # Default batch size for depth < 100

    @pytest.mark.asyncio
    async def test_flush_writes_batch_with_items(self):
        """Test returns items from queue."""
        items = [
            json.dumps({
                "type": "message",
                "data": {
                    "id": 1
                }
            }).encode(),
            json.dumps({
                "type": "message",
                "data": {
                    "id": 2
                }
            }).encode(),
            None,  # End of queue
        ]
        call_count = 0

        async def mock_lpop(key):
            nonlocal call_count
            result = items[call_count] if call_count < len(items) else None
            call_count += 1
            return result

        mock_redis = AsyncMock()
        mock_redis.lpop = mock_lpop
        mock_redis.llen = AsyncMock(return_value=2)

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            writes, batch_size = await flush_writes_batch()

        assert len(writes) == 2
        assert writes[0]["data"]["id"] == 1
        assert writes[1]["data"]["id"] == 2
        assert batch_size == 100  # Default for depth < 100


class TestFlushWrites:
    """Tests for flush_writes function."""

    @pytest.mark.asyncio
    async def test_flush_writes_empty_queue(self):
        """Test flush with empty queue returns 0."""
        mock_redis = AsyncMock()
        mock_redis.lpop = AsyncMock(return_value=None)
        mock_redis.llen = AsyncMock(return_value=0)
        mock_session = AsyncMock()

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            result = await flush_writes(mock_session)

        assert result == 0

    @pytest.mark.asyncio
    async def test_flush_writes_messages(self):
        """Test flushing message writes."""
        msg_payload = json.dumps({
            "type": "message",
            "data": {
                "chat_id": 123,
                "message_id": 456,
                "thread_id": 1,
                "from_user_id": None,
                "date": datetime.now(timezone.utc).isoformat(),
                "role": "assistant",
                "text_content": "Hello",
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "thinking_tokens": 0,
            },
        }).encode()

        call_count = 0

        async def mock_lpop(key):
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return msg_payload
            return None

        mock_redis = AsyncMock()
        mock_redis.lpop = mock_lpop
        mock_redis.llen = AsyncMock(return_value=0)

        # Create mock result for execute that returns rowcount
        mock_result = MagicMock()
        mock_result.rowcount = 1

        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            result = await flush_writes(mock_session)

        assert result == 1
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_called_once()


class TestAutoReplayDlq:
    """Tests for _auto_replay_dlq function."""

    @pytest.mark.asyncio
    async def test_replays_fresh_items(self):
        """Test fresh DLQ items are replayed to main queue."""
        import time

        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=1)
        item = json.dumps({
            "type": "message",
            "data": {
                "chat_id": 1
            },
            "queued_at": time.time() - 60,
            "retry_count": 3,
            "retry_after": 0,
        })
        mock_redis.lpop = AsyncMock(side_effect=[item.encode(), None])
        mock_redis.rpush = AsyncMock()

        mock_log = MagicMock()

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            await _auto_replay_dlq(mock_log)

        mock_redis.rpush.assert_called_once()
        # Verify retry_count was stripped
        replayed = json.loads(mock_redis.rpush.call_args[0][1])
        assert "retry_count" not in replayed
        assert "retry_after" not in replayed

    @pytest.mark.asyncio
    async def test_discards_expired_items(self):
        """Test items older than DLQ_MAX_AGE are discarded."""
        import time

        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=1)
        old_item = json.dumps({
            "type": "message",
            "data": {
                "chat_id": 1
            },
            "queued_at": time.time() - DLQ_MAX_AGE - 3600,
        })
        mock_redis.lpop = AsyncMock(side_effect=[old_item.encode(), None])
        mock_redis.rpush = AsyncMock()

        mock_log = MagicMock()

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            await _auto_replay_dlq(mock_log)

        mock_redis.rpush.assert_not_called()
        mock_log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_dlq_noop(self):
        """Test does nothing when DLQ is empty."""
        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=0)
        mock_log = MagicMock()

        with patch("cache.write_behind.get_redis", return_value=mock_redis):
            await _auto_replay_dlq(mock_log)

        mock_redis.lpop.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_unavailable(self):
        """Test graceful handling when Redis is unavailable."""
        mock_log = MagicMock()

        with patch("cache.write_behind.get_redis", return_value=None):
            await _auto_replay_dlq(mock_log)

        # Should not raise


class TestWriteTypes:
    """Tests for WriteType enum."""

    def test_write_type_values(self):
        """Test WriteType enum has expected values."""
        assert WriteType.MESSAGE.value == "message"
        assert WriteType.USER_STATS.value == "user_stats"
        assert WriteType.BALANCE_OP.value == "balance_op"
        assert WriteType.FILE.value == "file"
