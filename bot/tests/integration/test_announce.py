"""Tests for /announce broadcast command.

Tests cover:
- Privilege checking (unauthorized users rejected)
- Target parsing (usernames, IDs, mixed)
- Case-insensitive username lookup
- All-users mode (no targets)
- FSM state transitions
- Preview via copy_message
- Rate-limited broadcast with flood control
- TelegramRetryAfter handling
- Progress updates
- Delivery report generation
- Confirmation and cancellation flows
"""

from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

import config
from db.models.user import User
from db.repositories.user_repository import UserRepository
import pytest
from telegram.handlers import announce
from telegram.handlers.announce import _broadcast_message
from telegram.handlers.announce import _generate_report
from telegram.handlers.announce import _register_announce_topics
from telegram.handlers.announce import announce_cancel_callback
from telegram.handlers.announce import announce_confirm_callback
from telegram.handlers.announce import announce_message_received
from telegram.handlers.announce import AnnounceStates
from telegram.handlers.announce import cmd_announce

# =============================================================================
# Constants
# =============================================================================

ADMIN_USER_ID = 111111111
REGULAR_USER_ID = 222222222

# =============================================================================
# Helpers
# =============================================================================


@contextmanager
def privileged_context(user_id: int):
    """Temporarily set user as privileged."""
    with patch.object(config, 'PRIVILEGED_USERS', {user_id}):
        yield


@contextmanager
def no_privileged_users():
    """Empty privileged users set."""
    with patch.object(config, 'PRIVILEGED_USERS', set()):
        yield


def make_message(user_id: int, text: str, username: str = "admin") -> Mock:
    """Create mock message for announce tests."""
    msg = Mock()
    msg.from_user = Mock()
    msg.from_user.id = user_id
    msg.from_user.username = username
    msg.from_user.language_code = "en"
    msg.text = text
    msg.chat = Mock()
    msg.chat.id = 100
    msg.message_id = 42
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    msg.bot = Mock()
    msg.bot.copy_message = AsyncMock()
    return msg


def make_state(data: dict | None = None) -> AsyncMock:
    """Create mock FSM context."""
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=data or {})
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.clear = AsyncMock()
    return state


def make_callback(user_id: int, data: str) -> Mock:
    """Create mock callback query."""
    cb = Mock()
    cb.from_user = Mock()
    cb.from_user.id = user_id
    cb.from_user.language_code = "en"
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = Mock()
    cb.message.answer = AsyncMock(return_value=Mock(edit_text=AsyncMock()))
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer_document = AsyncMock()
    cb.bot = Mock()
    cb.bot.copy_message = AsyncMock()
    return cb


# =============================================================================
# Tests: Privilege Check
# =============================================================================


@pytest.mark.asyncio
class TestAnnouncePrivilege:
    """Test privilege checking for /announce."""

    async def test_unauthorized_user_rejected(self, test_session):
        """Unprivileged user gets error message."""
        with no_privileged_users():
            msg = make_message(REGULAR_USER_ID, "/announce")
            state = make_state()

            await cmd_announce(msg, test_session, state)

            msg.answer.assert_called_once()
            call_text = msg.answer.call_args[0][0]
            assert "❌" in call_text
            state.set_state.assert_not_called()

    async def test_authorized_user_allowed(self, test_session, sample_user):
        """Privileged user can use /announce."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(ADMIN_USER_ID, "/announce")
            state = make_state()

            await cmd_announce(msg, test_session, state)

            # Should enter waiting_for_message state (all users mode)
            state.set_state.assert_called_once_with(
                AnnounceStates.waiting_for_message)

    async def test_no_from_user_returns(self, test_session):
        """Message with no from_user returns silently."""
        msg = make_message(ADMIN_USER_ID, "/announce")
        msg.from_user = None
        state = make_state()

        await cmd_announce(msg, test_session, state)

        msg.answer.assert_not_called()


# =============================================================================
# Tests: Target Parsing
# =============================================================================


@pytest.mark.asyncio
class TestAnnounceTargetParsing:
    """Test target parsing for /announce with specific users."""

    async def test_parse_numeric_id(self, test_session, sample_user):
        """Parse numeric user ID."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(ADMIN_USER_ID, f"/announce {sample_user.id}")
            state = make_state()

            await cmd_announce(msg, test_session, state)

            state.set_state.assert_called_once_with(
                AnnounceStates.waiting_for_message)
            # Check target_ids in update_data
            call_kwargs = state.update_data.call_args[1]
            assert sample_user.id in call_kwargs["target_ids"]
            assert call_kwargs["is_all"] is False

    async def test_parse_username(self, test_session, sample_user):
        """Parse @username target."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(ADMIN_USER_ID,
                               f"/announce @{sample_user.username}")
            state = make_state()

            await cmd_announce(msg, test_session, state)

            state.set_state.assert_called_once()
            call_kwargs = state.update_data.call_args[1]
            assert sample_user.id in call_kwargs["target_ids"]

    async def test_parse_username_case_insensitive(self, test_session,
                                                   sample_user):
        """Parse @Username with different case still finds user."""
        with privileged_context(ADMIN_USER_ID):
            # sample_user.username is 'test_user', query with upper case
            upper_username = sample_user.username.upper()
            msg = make_message(ADMIN_USER_ID, f"/announce @{upper_username}")
            state = make_state()

            await cmd_announce(msg, test_session, state)

            state.set_state.assert_called_once()
            call_kwargs = state.update_data.call_args[1]
            assert sample_user.id in call_kwargs["target_ids"]

    async def test_not_found_targets(self, test_session):
        """Unknown targets reported as not found."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(ADMIN_USER_ID, "/announce @nonexistent 999999")
            state = make_state()

            await cmd_announce(msg, test_session, state)

            # Should report not found and not enter state
            calls = msg.answer.call_args_list
            # First call: warnings, second call: no valid targets
            assert len(calls) >= 1
            state.set_state.assert_not_called()

    async def test_deduplicates_targets(self, test_session, sample_user):
        """Duplicate targets are deduplicated."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(
                ADMIN_USER_ID,
                f"/announce {sample_user.id} {sample_user.id} @{sample_user.username}",
            )
            state = make_state()

            await cmd_announce(msg, test_session, state)

            call_kwargs = state.update_data.call_args[1]
            assert len(call_kwargs["target_ids"]) == 1


# =============================================================================
# Tests: All Users Mode
# =============================================================================


@pytest.mark.asyncio
class TestAnnounceAllUsers:
    """Test /announce with no targets (all users mode)."""

    async def test_all_users_mode(self, test_session, sample_user):
        """No targets → broadcast to all users."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(ADMIN_USER_ID, "/announce")
            state = make_state()

            await cmd_announce(msg, test_session, state)

            state.set_state.assert_called_once_with(
                AnnounceStates.waiting_for_message)
            call_kwargs = state.update_data.call_args[1]
            assert call_kwargs["is_all"] is True
            assert sample_user.id in call_kwargs["target_ids"]

    async def test_all_users_empty_db(self, test_session):
        """No users in DB → error message."""
        with privileged_context(ADMIN_USER_ID):
            msg = make_message(ADMIN_USER_ID, "/announce")
            state = make_state()

            await cmd_announce(msg, test_session, state)

            # Should get no valid targets message
            msg.answer.assert_called()
            state.set_state.assert_not_called()


# =============================================================================
# Tests: FSM - Message Received (Preview)
# =============================================================================


@pytest.mark.asyncio
class TestAnnounceMessageReceived:
    """Test message received in waiting_for_message state."""

    async def test_message_received_shows_confirmation(self):
        """Admin message shows reply-quote confirmation with buttons."""
        msg = make_message(ADMIN_USER_ID, "Hello everyone!")
        state = make_state({
            "admin_user_id": ADMIN_USER_ID,
            "target_ids": [1, 2, 3],
            "is_all": False,
        })

        await announce_message_received(msg, state)

        # Should store broadcast message reference
        state.update_data.assert_called_once()
        call_kwargs = state.update_data.call_args[1]
        assert call_kwargs["broadcast_chat_id"] == msg.chat.id
        assert call_kwargs["broadcast_message_id"] == msg.message_id

        # Should reply with confirmation + inline buttons
        msg.reply.assert_called_once()
        reply_kwargs = msg.reply.call_args[1]
        assert reply_kwargs["reply_markup"] is not None

        # State set AFTER buttons sent successfully
        state.set_state.assert_called_once_with(
            AnnounceStates.waiting_for_confirmation)

    async def test_wrong_user_ignored(self):
        """Non-admin user message is ignored."""
        msg = make_message(REGULAR_USER_ID, "Hijack attempt")
        state = make_state({
            "admin_user_id": ADMIN_USER_ID,
            "target_ids": [1, 2, 3],
        })

        await announce_message_received(msg, state)

        msg.bot.copy_message.assert_not_called()
        msg.reply.assert_not_called()
        state.set_state.assert_not_called()


# =============================================================================
# Tests: Confirmation/Cancellation
# =============================================================================


@pytest.mark.asyncio
class TestAnnounceConfirmation:
    """Test broadcast confirmation and cancellation."""

    @pytest.fixture(autouse=True)
    def _patch_topic_registration(self):
        """Patch out topic registration to avoid DB calls."""
        with patch(
                "telegram.handlers.announce._register_announce_topics",
                new_callable=AsyncMock,
        ):
            yield

    async def test_confirm_broadcasts(self):
        """Confirm button triggers copy_message broadcast with rate limiting."""
        cb = make_callback(ADMIN_USER_ID, "announce:confirm")
        state = make_state({
            "admin_user_id": ADMIN_USER_ID,
            "target_ids": [1001, 1002, 1003],
            "broadcast_chat_id": 100,
            "broadcast_message_id": 42,
        })

        with patch("telegram.handlers.announce.asyncio.sleep",
                   new_callable=AsyncMock):
            await announce_confirm_callback(cb, state)

        # Should clear state
        state.clear.assert_called_once()

        # Should call copy_message for each target
        assert cb.bot.copy_message.call_count == 3

        # Should send delivery report
        cb.message.answer_document.assert_called_once()

    async def test_confirm_handles_errors(self):
        """Broadcast handles blocked users gracefully."""
        from aiogram.exceptions import TelegramForbiddenError

        cb = make_callback(ADMIN_USER_ID, "announce:confirm")
        # First succeeds, second throws blocked error, third succeeds
        cb.bot.copy_message = AsyncMock(side_effect=[
            None,
            TelegramForbiddenError(method=MagicMock(),
                                   message="Forbidden: bot was blocked"),
            None,
        ])
        state = make_state({
            "admin_user_id": ADMIN_USER_ID,
            "target_ids": [1001, 1002, 1003],
            "broadcast_chat_id": 100,
            "broadcast_message_id": 42,
        })

        with patch("telegram.handlers.announce.asyncio.sleep",
                   new_callable=AsyncMock):
            await announce_confirm_callback(cb, state)

        assert cb.bot.copy_message.call_count == 3
        # Report should still be generated
        cb.message.answer_document.assert_called_once()

    async def test_cancel_clears_state(self):
        """Cancel button clears FSM state."""
        cb = make_callback(ADMIN_USER_ID, "announce:cancel")
        state = make_state({
            "admin_user_id": ADMIN_USER_ID,
            "target_ids": [1, 2, 3],
        })

        await announce_cancel_callback(cb, state)

        state.clear.assert_called_once()
        cb.message.edit_text.assert_called_once()

    async def test_wrong_user_confirm_ignored(self):
        """Non-admin clicking confirm is ignored."""
        cb = make_callback(REGULAR_USER_ID, "announce:confirm")
        state = make_state({
            "admin_user_id": ADMIN_USER_ID,
            "target_ids": [1, 2, 3],
            "broadcast_chat_id": 100,
            "broadcast_message_id": 42,
        })

        await announce_confirm_callback(cb, state)

        # Should not broadcast
        state.clear.assert_not_called()
        cb.bot.copy_message.assert_not_called()


# =============================================================================
# Tests: Broadcast Helper (_broadcast_message)
# =============================================================================


@pytest.mark.asyncio
class TestBroadcastMessage:
    """Test _broadcast_message helper with rate limiting and flood control."""

    @pytest.fixture(autouse=True)
    def _patch_topic_registration(self):
        """Patch out topic registration to avoid DB calls."""
        with patch(
                "telegram.handlers.announce._register_announce_topics",
                new_callable=AsyncMock,
        ):
            yield

    async def test_rate_limiting_sleeps_between_sends(self):
        """Should sleep 0.04s between each send."""
        bot = Mock()
        bot.copy_message = AsyncMock()
        progress_msg = Mock(edit_text=AsyncMock())

        with patch("telegram.handlers.announce.asyncio.sleep",
                   new_callable=AsyncMock) as mock_sleep:
            await _broadcast_message(
                bot=bot,
                target_ids=[1, 2, 3],
                usernames={},
                broadcast_chat_id=100,
                broadcast_message_id=42,
                progress_msg=progress_msg,
                lang="en",
            )

        # Should sleep 0.04 for each target
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_calls.count(0.04) == 3

    async def test_retry_after_retries_and_succeeds(self):
        """TelegramRetryAfter triggers retry after sleeping."""
        from aiogram.exceptions import TelegramRetryAfter

        bot = Mock()
        # First call: retry_after, second call: success
        bot.copy_message = AsyncMock(side_effect=[
            TelegramRetryAfter(retry_after=1, method="copy", message="Flood"),
            None,
        ])
        progress_msg = Mock(edit_text=AsyncMock())

        with patch("telegram.handlers.announce.asyncio.sleep",
                   new_callable=AsyncMock) as mock_sleep:
            delivered, failed = await _broadcast_message(
                bot=bot,
                target_ids=[1001],
                usernames={},
                broadcast_chat_id=100,
                broadcast_message_id=42,
                progress_msg=progress_msg,
                lang="en",
            )

        assert delivered == [1001]
        assert failed == []
        # Should have slept for retry_after (1s) + rate limit (0.04s)
        sleep_values = [c[0][0] for c in mock_sleep.call_args_list]
        assert 1 in sleep_values

    async def test_retry_after_exhaustion(self):
        """TelegramRetryAfter exhausts max_retries → fails."""
        from aiogram.exceptions import TelegramRetryAfter

        bot = Mock()
        bot.copy_message = AsyncMock(side_effect=TelegramRetryAfter(
            retry_after=0.01, method="copy", message="Flood"))
        progress_msg = Mock(edit_text=AsyncMock())

        with patch("telegram.handlers.announce.asyncio.sleep",
                   new_callable=AsyncMock):
            delivered, failed = await _broadcast_message(
                bot=bot,
                target_ids=[1001],
                usernames={},
                broadcast_chat_id=100,
                broadcast_message_id=42,
                progress_msg=progress_msg,
                lang="en",
                max_retries=2,
            )

        assert delivered == []
        assert len(failed) == 1
        assert failed[0][0] == 1001
        assert "Flood control" in failed[0][1]
        # Should have been called max_retries times
        assert bot.copy_message.call_count == 2

    async def test_progress_updates_every_5(self):
        """Progress message updated every 5 sends."""
        bot = Mock()
        bot.copy_message = AsyncMock()
        progress_msg = Mock(edit_text=AsyncMock())

        with patch("telegram.handlers.announce.asyncio.sleep",
                   new_callable=AsyncMock):
            await _broadcast_message(
                bot=bot,
                target_ids=list(range(12)),
                usernames={},
                broadcast_chat_id=100,
                broadcast_message_id=42,
                progress_msg=progress_msg,
                lang="en",
            )

        # Updates at: 5, 10, 12 (final)
        assert progress_msg.edit_text.call_count == 3


# =============================================================================
# Tests: Report Generation
# =============================================================================


class TestAnnounceReport:
    """Test delivery report generation."""

    def test_report_with_delivered_and_failed(self):
        """Report includes both delivered and failed sections."""
        report = _generate_report(
            delivered=[1001, 1002],
            failed=[(1003, "Bot blocked by user")],
        )

        assert "Total: 3" in report
        assert "Delivered: 2" in report
        assert "Failed: 1" in report
        assert "1001" in report
        assert "1002" in report
        assert "1003: Bot blocked by user" in report

    def test_report_all_delivered(self):
        """Report with no failures."""
        report = _generate_report(delivered=[1, 2, 3], failed=[])

        assert "Delivered: 3" in report
        assert "Failed: 0" in report
        assert "=== Failed ===" not in report

    def test_report_all_failed(self):
        """Report with no deliveries."""
        report = _generate_report(
            delivered=[],
            failed=[(1, "error1"), (2, "error2")],
        )

        assert "Delivered: 0" in report
        assert "Failed: 2" in report
        assert "=== Delivered ===" not in report

    def test_report_includes_usernames(self):
        """Report shows usernames next to IDs when available."""
        usernames = {1001: "alice", 1003: "charlie"}
        report = _generate_report(
            delivered=[1001, 1002],
            failed=[(1003, "Bot blocked by user")],
            usernames=usernames,
        )

        assert '1001 "@alice"' in report
        assert "1002" in report  # No username, just ID
        assert '1003 "@charlie": Bot blocked by user' in report


# =============================================================================
# Tests: Announce Topic Registration
# =============================================================================


@pytest.mark.asyncio
class TestAnnounceTopicRegistration:
    """Test _register_announce_topics for forum chat topic tracking."""

    async def test_registers_topics_for_forum_chats(self, test_session):
        """Topics registered for chats with is_forum=True."""
        from db.models.chat import Chat
        from db.models.thread import Thread

        # Create forum chat in DB
        chat = Chat(id=2001, type="supergroup", is_forum=True)
        test_session.add(chat)
        await test_session.flush()

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=test_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("db.engine.get_session", return_value=mock_session_cm):
            await _register_announce_topics(
                sent_message_ids={2001: 555},
                usernames={2001: "forum_user"},
            )

        # Verify thread was created
        from sqlalchemy import select
        result = await test_session.execute(
            select(Thread).where(Thread.chat_id == 2001,
                                 Thread.thread_id == 555))
        thread = result.scalar_one_or_none()
        assert thread is not None
        assert thread.user_id == 2001
        assert thread.thread_id == 555

    async def test_skips_non_forum_chats(self, test_session):
        """Non-forum chats are skipped — no Thread records created."""
        from db.models.chat import Chat
        from db.models.thread import Thread

        # Create non-forum chat
        chat = Chat(id=3001, type="private", is_forum=False)
        test_session.add(chat)
        await test_session.flush()

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=test_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("db.engine.get_session", return_value=mock_session_cm):
            await _register_announce_topics(
                sent_message_ids={3001: 777},
                usernames={3001: "regular_user"},
            )

        # No thread should be created
        from sqlalchemy import select
        result = await test_session.execute(
            select(Thread).where(Thread.chat_id == 3001))
        assert result.scalar_one_or_none() is None

    async def test_handles_db_error_gracefully(self):
        """DB errors are caught — function does not raise."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=RuntimeError("DB connection lost"))

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("db.engine.get_session", return_value=mock_session_cm):
            # Should NOT raise
            await _register_announce_topics(
                sent_message_ids={4001: 999},
                usernames={4001: "error_user"},
            )

    async def test_mixed_forum_and_non_forum(self, test_session):
        """Only forum chats get Thread records, non-forum are skipped."""
        from db.models.chat import Chat
        from db.models.thread import Thread

        # Create one forum and one non-forum chat
        test_session.add(Chat(id=5001, type="supergroup", is_forum=True))
        test_session.add(Chat(id=5002, type="private", is_forum=False))
        await test_session.flush()

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=test_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        with patch("db.engine.get_session", return_value=mock_session_cm):
            await _register_announce_topics(
                sent_message_ids={
                    5001: 111,
                    5002: 222
                },
                usernames={},
            )

        from sqlalchemy import select

        # Forum chat should have thread
        result = await test_session.execute(
            select(Thread).where(Thread.chat_id == 5001))
        assert result.scalar_one_or_none() is not None

        # Non-forum should not
        result = await test_session.execute(
            select(Thread).where(Thread.chat_id == 5002))
        assert result.scalar_one_or_none() is None
