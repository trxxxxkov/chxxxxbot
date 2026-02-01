"""Tests for data cleanup service.

Tests for the retention policy cleanup functionality:
- messages: 90 days
- tool_calls: 90 days
- user_files: 90 days
- threads: 90 days (empty only)
"""

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from db.models.chat import Chat
from db.models.message import Message
from db.models.message import MessageRole
from db.models.thread import Thread
from db.models.tool_call import ToolCall
from db.models.user import User
from db.models.user_file import FileSource
from db.models.user_file import FileType
from db.models.user_file import UserFile
import pytest
from services.cleanup import BATCH_SIZE
from services.cleanup import cleanup_empty_threads
from services.cleanup import cleanup_messages
from services.cleanup import cleanup_task
from services.cleanup import cleanup_tool_calls
from services.cleanup import cleanup_user_files
from services.cleanup import RETENTION_MESSAGES
from services.cleanup import RETENTION_THREADS
from services.cleanup import RETENTION_TOOL_CALLS
from services.cleanup import RETENTION_USER_FILES
from services.cleanup import run_cleanup


class TestRetentionConstants:
    """Test retention policy constants."""

    def test_retention_periods(self):
        """Verify retention periods are set correctly."""
        assert RETENTION_MESSAGES == 90
        assert RETENTION_TOOL_CALLS == 90
        assert RETENTION_USER_FILES == 90
        assert RETENTION_THREADS == 90

    def test_batch_size(self):
        """Verify batch size is reasonable."""
        assert BATCH_SIZE == 500


class TestCleanupMessages:
    """Tests for message cleanup."""

    @pytest.fixture
    async def setup_messages(self, test_session):
        """Create test user, chat, thread and messages."""
        # Create user
        user = User(
            id=123456789,
            is_bot=False,
            first_name="Test",
            is_premium=False,
            added_to_attachment_menu=False,
            model_id="claude:sonnet",
        )
        test_session.add(user)

        # Create chat
        chat = Chat(id=123456789, type="private", is_forum=False)
        test_session.add(chat)
        await test_session.flush()

        # Create thread
        thread = Thread(chat_id=chat.id, user_id=user.id)
        test_session.add(thread)
        await test_session.flush()

        return user, chat, thread

    @pytest.mark.asyncio
    async def test_cleanup_old_messages(self, test_session, setup_messages):
        """Test that old messages are deleted."""
        user, chat, thread = setup_messages

        now = datetime.now(timezone.utc)
        old_timestamp = int((now - timedelta(days=100)).timestamp())
        new_timestamp = int((now - timedelta(days=10)).timestamp())

        # Create old message (should be deleted)
        old_msg = Message(
            chat_id=chat.id,
            message_id=1,
            thread_id=thread.id,
            from_user_id=user.id,
            date=old_timestamp,
            role=MessageRole.USER,
            has_photos=False,
            has_documents=False,
            has_voice=False,
            has_video=False,
            attachment_count=0,
            created_at=old_timestamp,
        )
        test_session.add(old_msg)

        # Create new message (should remain)
        new_msg = Message(
            chat_id=chat.id,
            message_id=2,
            thread_id=thread.id,
            from_user_id=user.id,
            date=new_timestamp,
            role=MessageRole.USER,
            has_photos=False,
            has_documents=False,
            has_voice=False,
            has_video=False,
            attachment_count=0,
            created_at=new_timestamp,
        )
        test_session.add(new_msg)
        await test_session.flush()

        # Run cleanup
        cutoff = int((now - timedelta(days=90)).timestamp())
        logger = MagicMock()

        deleted = await cleanup_messages(test_session, cutoff, logger)

        assert deleted == 1
        logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_no_old_messages(self, test_session, setup_messages):
        """Test cleanup when no messages are old enough."""
        user, chat, thread = setup_messages

        now = datetime.now(timezone.utc)
        new_timestamp = int((now - timedelta(days=10)).timestamp())

        # Create only new messages
        msg = Message(
            chat_id=chat.id,
            message_id=1,
            thread_id=thread.id,
            from_user_id=user.id,
            date=new_timestamp,
            role=MessageRole.USER,
            has_photos=False,
            has_documents=False,
            has_voice=False,
            has_video=False,
            attachment_count=0,
            created_at=new_timestamp,
        )
        test_session.add(msg)
        await test_session.flush()

        cutoff = int((now - timedelta(days=90)).timestamp())
        logger = MagicMock()

        deleted = await cleanup_messages(test_session, cutoff, logger)

        assert deleted == 0
        logger.info.assert_not_called()


class TestCleanupToolCalls:
    """Tests for tool_calls cleanup."""

    @pytest.fixture
    async def setup_tool_calls(self, test_session):
        """Create test user and chat for tool calls."""
        user = User(
            id=123456790,
            is_bot=False,
            first_name="Test",
            is_premium=False,
            added_to_attachment_menu=False,
            model_id="claude:sonnet",
        )
        test_session.add(user)

        chat = Chat(id=123456790, type="private", is_forum=False)
        test_session.add(chat)
        await test_session.flush()

        return user, chat

    @pytest.mark.asyncio
    async def test_cleanup_old_tool_calls(self, test_session, setup_tool_calls):
        """Test that old tool calls are deleted."""
        user, chat = setup_tool_calls

        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=100)
        new_date = now - timedelta(days=10)

        # Create old tool call
        old_call = ToolCall(
            user_id=user.id,
            chat_id=chat.id,
            tool_name="test_tool",
            model_id="claude-sonnet-4-5",
            cost_usd=Decimal("0.001"),
            created_at=old_date,
        )
        test_session.add(old_call)

        # Create new tool call
        new_call = ToolCall(
            user_id=user.id,
            chat_id=chat.id,
            tool_name="test_tool",
            model_id="claude-sonnet-4-5",
            cost_usd=Decimal("0.001"),
            created_at=new_date,
        )
        test_session.add(new_call)
        await test_session.flush()

        cutoff = now - timedelta(days=90)
        logger = MagicMock()

        deleted = await cleanup_tool_calls(test_session, cutoff, logger)

        assert deleted == 1


class TestCleanupUserFiles:
    """Tests for user_files cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_old_user_files(self, test_session):
        """Test that old user file metadata is deleted."""
        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=100)
        new_date = now - timedelta(days=10)

        # Create old file metadata
        old_file = UserFile(
            message_id=1,
            claude_file_id="file_old_123",
            filename="old.txt",
            file_type=FileType.DOCUMENT,
            mime_type="text/plain",
            file_size=100,
            uploaded_at=old_date,
            expires_at=old_date + timedelta(hours=24),
            source=FileSource.USER,
        )
        test_session.add(old_file)

        # Create new file metadata
        new_file = UserFile(
            message_id=2,
            claude_file_id="file_new_456",
            filename="new.txt",
            file_type=FileType.DOCUMENT,
            mime_type="text/plain",
            file_size=100,
            uploaded_at=new_date,
            expires_at=new_date + timedelta(hours=24),
            source=FileSource.USER,
        )
        test_session.add(new_file)
        await test_session.flush()

        cutoff = now - timedelta(days=90)
        logger = MagicMock()

        deleted = await cleanup_user_files(test_session, cutoff, logger)

        assert deleted == 1


class TestCleanupEmptyThreads:
    """Tests for empty thread cleanup."""

    @pytest.fixture
    async def setup_threads(self, test_session):
        """Create test user and chat."""
        user = User(
            id=123456791,
            is_bot=False,
            first_name="Test",
            is_premium=False,
            added_to_attachment_menu=False,
            model_id="claude:sonnet",
        )
        test_session.add(user)

        chat = Chat(id=123456791, type="private", is_forum=False)
        test_session.add(chat)
        await test_session.flush()

        return user, chat

    @pytest.mark.asyncio
    async def test_cleanup_empty_old_threads(self, test_session, setup_threads):
        """Test that empty old threads are deleted."""
        user, chat = setup_threads

        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=100)
        new_date = now - timedelta(days=10)

        # Create old empty thread (should be deleted)
        old_thread = Thread(
            chat_id=chat.id,
            user_id=user.id,
            thread_id=1,
            updated_at=old_date,
        )
        test_session.add(old_thread)

        # Create new empty thread (should remain)
        new_thread = Thread(
            chat_id=chat.id,
            user_id=user.id,
            thread_id=2,
            updated_at=new_date,
        )
        test_session.add(new_thread)
        await test_session.flush()

        cutoff = now - timedelta(days=90)
        logger = MagicMock()

        deleted = await cleanup_empty_threads(test_session, cutoff, logger)

        assert deleted == 1

    @pytest.mark.asyncio
    async def test_keep_threads_with_messages(self, test_session,
                                              setup_threads):
        """Test that threads with messages are not deleted."""
        user, chat = setup_threads

        now = datetime.now(timezone.utc)
        old_date = now - timedelta(days=100)
        old_timestamp = int(old_date.timestamp())

        # Create old thread with message
        old_thread = Thread(
            chat_id=chat.id,
            user_id=user.id,
            thread_id=3,
            updated_at=old_date,
        )
        test_session.add(old_thread)
        await test_session.flush()

        # Add message to thread
        msg = Message(
            chat_id=chat.id,
            message_id=100,
            thread_id=old_thread.id,
            from_user_id=user.id,
            date=old_timestamp,
            role=MessageRole.USER,
            has_photos=False,
            has_documents=False,
            has_voice=False,
            has_video=False,
            attachment_count=0,
            created_at=old_timestamp,
        )
        test_session.add(msg)
        await test_session.flush()

        cutoff = now - timedelta(days=90)
        logger = MagicMock()

        deleted = await cleanup_empty_threads(test_session, cutoff, logger)

        # Thread should not be deleted because it has messages
        assert deleted == 0


class TestRunCleanup:
    """Tests for the full cleanup run."""

    @pytest.mark.asyncio
    async def test_run_cleanup_logs_results(self):
        """Test that run_cleanup logs completed results."""
        logger = MagicMock()

        with patch('services.cleanup.get_session') as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(
                return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock()

            # Mock all cleanup functions
            with patch('services.cleanup.cleanup_messages',
                       return_value=10) as mock_msg, \
                 patch('services.cleanup.cleanup_tool_calls',
                       return_value=5) as mock_tools, \
                 patch('services.cleanup.cleanup_user_files',
                       return_value=3) as mock_files, \
                 patch('services.cleanup.cleanup_empty_threads',
                       return_value=2) as mock_threads:

                results = await run_cleanup(logger)

                assert results["messages"] == 10
                assert results["tool_calls"] == 5
                assert results["user_files"] == 3
                assert results["threads"] == 2

    @pytest.mark.asyncio
    async def test_run_cleanup_handles_errors(self):
        """Test that run_cleanup handles errors gracefully."""
        logger = MagicMock()

        with patch('services.cleanup.get_session') as mock_get_session:
            mock_get_session.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("DB error"))
            mock_get_session.return_value.__aexit__ = AsyncMock()

            results = await run_cleanup(logger)

            # Should return zeros on error
            assert results["messages"] == 0
            logger.error.assert_called()


class TestCleanupTask:
    """Tests for the background cleanup task."""

    @pytest.mark.asyncio
    async def test_cleanup_task_cancellation(self):
        """Test that cleanup task handles cancellation gracefully."""
        logger = MagicMock()

        task = asyncio.create_task(cleanup_task(logger))

        # Let it start
        await asyncio.sleep(0.01)

        # Cancel it
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_task_schedules_correctly(self):
        """Test that cleanup task calculates next run time correctly."""
        logger = MagicMock()

        with patch('services.cleanup.run_cleanup',
                   new_callable=AsyncMock) as mock_run:
            with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                # Make sleep raise CancelledError to exit loop
                mock_sleep.side_effect = asyncio.CancelledError()

                with pytest.raises(asyncio.CancelledError):
                    await cleanup_task(logger)

                # Verify sleep was called with some positive value
                mock_sleep.assert_called_once()
                sleep_time = mock_sleep.call_args[0][0]
                assert sleep_time > 0
                # Should be less than 24 hours
                assert sleep_time < 86400
