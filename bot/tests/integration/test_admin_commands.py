"""Admin commands integration tests (Phase 2.1 Stage 9).

Tests admin-only commands (topup, set_margin) with privilege checking.

NO __init__.py - use direct import:
    pytest tests/integration/test_admin_commands.py
"""

from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import config
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.user_repository import UserRepository
import pytest
from services.balance_service import BalanceService
from telegram.handlers import admin

# =============================================================================
# Fixtures
# =============================================================================

ADMIN_USER_ID = 111111111
REGULAR_USER_ID = 222222222


@pytest.fixture
def admin_user_id():
    """Admin user ID for privilege tests."""
    return ADMIN_USER_ID


@pytest.fixture
def regular_user_id():
    """Regular (non-privileged) user ID for tests."""
    return REGULAR_USER_ID


@contextmanager
def privileged_context(user_id: int):
    """Context manager to temporarily set user as privileged.

    Args:
        user_id: User ID to add to privileged set.

    Yields:
        None. Use as context manager.
    """
    with patch.object(config, 'PRIVILEGED_USERS', {user_id}):
        yield


@contextmanager
def no_privileged_users():
    """Context manager with empty privileged users set."""
    with patch.object(config, 'PRIVILEGED_USERS', set()):
        yield


def create_admin_message(user_id: int, text: str, test_session=None) -> Mock:
    """Create a mock message from an admin user.

    Args:
        user_id: User ID for the message sender.
        text: Message text (command).
        test_session: Optional session to attach to bot.

    Returns:
        Mock message object.
    """
    mock_message = Mock()
    mock_message.from_user = Mock()
    mock_message.from_user.id = user_id
    mock_message.from_user.username = "admin_user" if user_id == ADMIN_USER_ID else "regular_user"
    mock_message.from_user.language_code = "en"  # Explicit English for i18n
    mock_message.text = text
    mock_message.answer = AsyncMock()
    mock_message.bot = Mock()
    if test_session:
        mock_message.bot.get = Mock(return_value=test_session)
    return mock_message


# =============================================================================
# Tests
# =============================================================================


@pytest.mark.asyncio
class TestTopupCommand:
    """Test /topup admin command."""

    async def test_topup_add_balance_by_id(self, test_session, sample_user,
                                           admin_user_id):
        """Test adding balance by user ID.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            mock_message = create_admin_message(
                admin_user_id,
                f"/topup {sample_user.id} 5.00",
                test_session,
            )

            # Get initial balance
            user_repo = UserRepository(test_session)
            user = await user_repo.get_by_id(sample_user.id)
            balance_before = user.balance

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify balance increased
            user = await user_repo.get_by_id(sample_user.id)
            assert user.balance == balance_before + Decimal("5.00")

            # Verify success message sent
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "Balance adjusted" in response
            assert "Added" in response
            assert "$5.00" in response or "$5" in response

    async def test_topup_deduct_balance_by_id(self, test_session, sample_user,
                                              admin_user_id):
        """Test deducting balance by user ID.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            mock_message = create_admin_message(
                admin_user_id,
                f"/topup {sample_user.id} -0.05",
                test_session,
            )

            # Get initial balance
            user_repo = UserRepository(test_session)
            user = await user_repo.get_by_id(sample_user.id)
            balance_before = user.balance

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify balance decreased
            user = await user_repo.get_by_id(sample_user.id)
            assert user.balance == balance_before - Decimal("0.05")

            # Verify success message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "Balance adjusted" in response
            assert "Deducted" in response

    async def test_topup_by_username(self, test_session, sample_user,
                                     admin_user_id):
        """Test topup by username.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            # sample_user has username "test_user"
            mock_message = create_admin_message(
                admin_user_id,
                "/topup @test_user 3.50",
                test_session,
            )

            # Get initial balance
            user_repo = UserRepository(test_session)
            user = await user_repo.get_by_id(sample_user.id)
            balance_before = user.balance

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify balance increased
            user = await user_repo.get_by_id(sample_user.id)
            assert user.balance == balance_before + Decimal("3.50")

    async def test_topup_unauthorized_user(self, test_session, sample_user,
                                           regular_user_id):
        """Test that non-privileged user cannot topup.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
            regular_user_id: Regular user ID fixture.
        """
        with no_privileged_users():
            mock_message = create_admin_message(
                regular_user_id,
                f"/topup {sample_user.id} 100.00",
                test_session,
            )

            # Get initial balance
            user_repo = UserRepository(test_session)
            user = await user_repo.get_by_id(sample_user.id)
            balance_before = user.balance

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify balance unchanged
            user = await user_repo.get_by_id(sample_user.id)
            assert user.balance == balance_before

            # Verify unauthorized message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "privileged users" in response.lower()

    async def test_topup_invalid_user_id(self, test_session, admin_user_id):
        """Test topup with invalid user ID.

        Args:
            test_session: Async session fixture.
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            # Non-existent user
            mock_message = create_admin_message(
                admin_user_id,
                "/topup 999999999 5.00",
                test_session,
            )

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "failed" in response.lower(
            ) or "not found" in response.lower()

    async def test_topup_invalid_amount(self, test_session, sample_user,
                                        admin_user_id):
        """Test topup with invalid amount format.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            mock_message = create_admin_message(
                admin_user_id,
                f"/topup {sample_user.id} invalid",
            )

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "Invalid amount" in response

    async def test_topup_missing_arguments(self, test_session, admin_user_id):
        """Test topup with missing arguments.

        Args:
            test_session: Async session fixture.
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            mock_message = create_admin_message(admin_user_id, "/topup")

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify usage message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "Usage" in response
            assert "/topup" in response


@pytest.mark.asyncio
class TestSetMarginCommand:
    """Test /set_margin admin command."""

    async def test_set_margin_valid_value(self, admin_user_id):
        """Test setting valid margin value.

        Args:
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            original_margin = config.DEFAULT_OWNER_MARGIN
            mock_message = create_admin_message(
                admin_user_id,
                "/set_margin 0.10",  # Set 10% margin
            )

            # Call handler
            await admin.cmd_set_margin(mock_message)

            # Verify margin updated
            assert config.DEFAULT_OWNER_MARGIN == 0.10

            # Verify success message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "margin updated" in response.lower()
            assert "10" in response  # 10%

            # Restore original value
            config.DEFAULT_OWNER_MARGIN = original_margin

    async def test_set_margin_zero(self, admin_user_id):
        """Test setting margin to zero (no profit).

        Args:
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            original_margin = config.DEFAULT_OWNER_MARGIN
            mock_message = create_admin_message(
                admin_user_id,
                "/set_margin 0.0",
            )

            await admin.cmd_set_margin(mock_message)

            # Verify margin set to 0
            assert config.DEFAULT_OWNER_MARGIN == 0.0

            mock_message.answer.assert_called_once()

            # Restore
            config.DEFAULT_OWNER_MARGIN = original_margin

    async def test_set_margin_exceeds_max(self, admin_user_id):
        """Test setting margin that exceeds maximum allowed.

        k1 + k2 + k3 must not exceed 1.0.

        Args:
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            # Too high (k1=0.35, k2=0.15)
            mock_message = create_admin_message(
                admin_user_id,
                "/set_margin 0.60",
            )

            # Call handler
            await admin.cmd_set_margin(mock_message)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "exceeds 100%" in response or "Maximum" in response

    async def test_set_margin_negative(self, admin_user_id):
        """Test setting negative margin (invalid).

        Args:
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            mock_message = create_admin_message(
                admin_user_id,
                "/set_margin -0.10",  # Negative
            )

            await admin.cmd_set_margin(mock_message)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "range [0, 1]" in response or "must be" in response.lower()

    async def test_set_margin_unauthorized(self, regular_user_id):
        """Test that non-privileged user cannot set margin.

        Args:
            regular_user_id: Regular user ID fixture.
        """
        with no_privileged_users():
            original_margin = config.DEFAULT_OWNER_MARGIN
            mock_message = create_admin_message(
                regular_user_id,
                "/set_margin 0.50",
            )

            await admin.cmd_set_margin(mock_message)

            # Verify margin unchanged
            assert config.DEFAULT_OWNER_MARGIN == original_margin

            # Verify unauthorized message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "privileged users" in response.lower()

    async def test_set_margin_invalid_format(self, admin_user_id):
        """Test setting margin with invalid format.

        Args:
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            mock_message = create_admin_message(
                admin_user_id,
                "/set_margin invalid",
            )

            await admin.cmd_set_margin(mock_message)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "Invalid" in response

    async def test_set_margin_no_arguments(self, admin_user_id):
        """Test /set_margin with no arguments (shows usage).

        Args:
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            mock_message = create_admin_message(admin_user_id, "/set_margin")

            await admin.cmd_set_margin(mock_message)

            # Verify usage message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "Usage" in response or "Owner Margin" in response
            assert "k1" in response.lower()
            assert "k2" in response.lower()
            assert "k3" in response.lower()


@pytest.mark.asyncio
class TestPrivilegeChecking:
    """Test privilege checking mechanism."""

    async def test_is_privileged_function(self, admin_user_id, regular_user_id):
        """Test is_privileged() helper function.

        Args:
            admin_user_id: Admin user ID fixture.
            regular_user_id: Regular user ID fixture.
        """
        with privileged_context(admin_user_id):
            assert admin.is_privileged(admin_user_id) is True
            assert admin.is_privileged(regular_user_id) is False

    async def test_empty_privileged_set(self, admin_user_id, regular_user_id):
        """Test behavior when no privileged users configured.

        Args:
            admin_user_id: Admin user ID fixture.
            regular_user_id: Regular user ID fixture.
        """
        with no_privileged_users():
            assert admin.is_privileged(admin_user_id) is False
            assert admin.is_privileged(regular_user_id) is False

    async def test_multiple_privileged_users(self, regular_user_id):
        """Test multiple privileged users.

        Args:
            regular_user_id: Regular user ID fixture.
        """
        admin1 = 111111
        admin2 = 222222

        with patch.object(config, 'PRIVILEGED_USERS', {admin1, admin2}):
            assert admin.is_privileged(admin1) is True
            assert admin.is_privileged(admin2) is True
            assert admin.is_privileged(regular_user_id) is False


def create_clear_message(user_id: int,
                         chat_id: int,
                         message_thread_id: int | None = None) -> Mock:
    """Create a mock message for /clear command.

    Args:
        user_id: User ID for the message sender.
        chat_id: Chat ID where command is sent.
        message_thread_id: Optional topic/thread ID.

    Returns:
        Mock message object.
    """
    mock_message = create_admin_message(user_id, "/clear")
    mock_message.chat = Mock()
    mock_message.chat.id = chat_id
    mock_message.message_thread_id = message_thread_id
    mock_message.bot = Mock()
    mock_message.bot.delete_forum_topic = AsyncMock()
    return mock_message


@pytest.mark.asyncio
class TestClearCommand:
    """Test /clear admin command for deleting forum topics."""

    async def test_clear_unauthorized_user(self, test_session, regular_user_id):
        """Test that non-privileged user cannot use /clear.

        Args:
            test_session: Async session fixture.
            regular_user_id: Regular user ID fixture.
        """
        with no_privileged_users():
            mock_message = create_clear_message(
                regular_user_id,
                chat_id=123456789,
            )

            await admin.cmd_clear(mock_message, test_session)

            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            # Response indicates user needs admin rights
            assert "admin rights" in response.lower()

    async def test_clear_no_topics(self, test_session, admin_user_id):
        """Test /clear when no topics exist.

        Args:
            test_session: Async session fixture.
            admin_user_id: Admin user ID fixture.
        """
        with privileged_context(admin_user_id):
            # Chat with no topics
            mock_message = create_clear_message(
                admin_user_id,
                chat_id=999999999,
            )

            await admin.cmd_clear(mock_message, test_session)

            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "No forum topics" in response

    async def test_clear_all_from_general(self, test_session, admin_user_id):
        """Test /clear from General shows confirmation for multiple topics.

        Args:
            test_session: Async session fixture.
            admin_user_id: Admin user ID fixture.
        """
        from db.repositories.thread_repository import ThreadRepository

        chat_id = 888888888

        # Create some threads with topics
        thread_repo = ThreadRepository(test_session)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=1001)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=1002)
        await test_session.flush()

        with privileged_context(admin_user_id):
            mock_message = create_clear_message(
                admin_user_id,
                chat_id=chat_id,
            )

            await admin.cmd_clear(mock_message, test_session)

            # Now shows confirmation instead of immediate deletion
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "2" in response  # Number of topics

    async def test_clear_single_topic(self, test_session, admin_user_id):
        """Test /clear in existing topic deletes only that topic.

        topic_was_created=False means it's an existing topic, not new.

        Args:
            test_session: Async session fixture.
            admin_user_id: Admin user ID fixture.
        """
        from db.repositories.thread_repository import ThreadRepository

        chat_id = 666666666

        # Create threads
        thread_repo = ThreadRepository(test_session)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=3001)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=3002)
        await test_session.flush()

        with privileged_context(admin_user_id):
            mock_message = create_clear_message(
                admin_user_id,
                chat_id=chat_id,
                message_thread_id=3001,  # From topic 3001
            )

            # topic_was_created=False means existing topic, delete only this one
            await admin.cmd_clear(mock_message,
                                  test_session,
                                  topic_was_created=False)

            # Should delete only topic 3001
            mock_message.bot.delete_forum_topic.assert_called_once()
            call_kwargs = mock_message.bot.delete_forum_topic.call_args[1]
            assert call_kwargs["message_thread_id"] == 3001

    async def test_clear_general_topic_id_1(self, test_session, admin_user_id):
        """Test /clear with topic_id=1 (General) shows confirmation.

        Args:
            test_session: Async session fixture.
            admin_user_id: Admin user ID fixture.
        """
        from db.repositories.thread_repository import ThreadRepository

        chat_id = 555555555

        thread_repo = ThreadRepository(test_session)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=4001)
        await test_session.flush()

        with privileged_context(admin_user_id):
            mock_message = create_clear_message(
                admin_user_id,
                chat_id=chat_id,
                message_thread_id=1,  # General topic ID
            )

            await admin.cmd_clear(mock_message, test_session)

            # Now shows confirmation instead of immediate deletion
            mock_message.answer.assert_called_once()

    async def test_clear_from_new_topic_deletes_all(self, test_session,
                                                    admin_user_id):
        """Test /clear from a newly created topic shows confirmation.

        When CommandMiddleware sets topic_was_created=True, the /clear
        command should show confirmation for deleting ALL topics.

        Args:
            test_session: Async session fixture.
            admin_user_id: Admin user ID fixture.
        """
        from db.repositories.thread_repository import ThreadRepository

        chat_id = 777777777

        # Create multiple threads (topics)
        thread_repo = ThreadRepository(test_session)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=5001)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=5002)
        await test_session.flush()

        with privileged_context(admin_user_id):
            mock_message = create_clear_message(
                admin_user_id,
                chat_id=chat_id,
                message_thread_id=5001,  # New topic
            )

            # topic_was_created=True means new topic, treat as "all topics"
            await admin.cmd_clear(mock_message,
                                  test_session,
                                  topic_was_created=True)

            # Now shows confirmation instead of immediate deletion
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "2" in response  # Number of topics
