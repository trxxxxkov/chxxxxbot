"""Admin commands integration tests (Phase 2.1 Stage 9).

Tests admin-only commands (topup, set_margin) with privilege checking.

NO __init__.py - use direct import:
    pytest tests/integration/test_admin_commands.py
"""

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


@pytest.mark.asyncio
class TestTopupCommand:
    """Test /topup admin command."""

    async def test_topup_add_balance_by_id(self, test_session, sample_user):
        """Test adding balance by user ID.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: Admin user (add to privileged list)
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            # Mock message from admin
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.from_user.username = "admin_user"
            mock_message.text = f"/topup {sample_user.id} 5.00"
            mock_message.answer = AsyncMock()
            mock_message.bot = Mock()
            mock_message.bot.get = Mock(return_value=test_session)

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

    async def test_topup_deduct_balance_by_id(self, test_session, sample_user):
        """Test deducting balance by user ID.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.from_user.username = "admin_user"
            mock_message.text = f"/topup {sample_user.id} -0.05"
            mock_message.answer = AsyncMock()
            mock_message.bot = Mock()
            mock_message.bot.get = Mock(return_value=test_session)

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

    async def test_topup_by_username(self, test_session, sample_user):
        """Test topup by username.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.from_user.username = "admin_user"
            # sample_user has username "test_user"
            mock_message.text = "/topup @test_user 3.50"
            mock_message.answer = AsyncMock()
            mock_message.bot = Mock()
            mock_message.bot.get = Mock(return_value=test_session)

            # Get initial balance
            user_repo = UserRepository(test_session)
            user = await user_repo.get_by_id(sample_user.id)
            balance_before = user.balance

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify balance increased
            user = await user_repo.get_by_id(sample_user.id)
            assert user.balance == balance_before + Decimal("3.50")

    async def test_topup_unauthorized_user(self, test_session, sample_user):
        """Test that non-privileged user cannot topup.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Non-privileged user
        regular_user_id = 222222222
        with patch.object(config, 'PRIVILEGED_USERS', set()):  # Empty set
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = regular_user_id
            mock_message.from_user.username = "regular_user"
            mock_message.text = f"/topup {sample_user.id} 100.00"
            mock_message.answer = AsyncMock()
            mock_message.bot = Mock()
            mock_message.bot.get = Mock(return_value=test_session)

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

    async def test_topup_invalid_user_id(self, test_session):
        """Test topup with invalid user ID.

        Args:
            test_session: Async session fixture.
        """
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.from_user.username = "admin_user"
            mock_message.text = "/topup 999999999 5.00"  # Non-existent user
            mock_message.answer = AsyncMock()
            mock_message.bot = Mock()
            mock_message.bot.get = Mock(return_value=test_session)

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "failed" in response.lower(
            ) or "not found" in response.lower()

    async def test_topup_invalid_amount(self, test_session, sample_user):
        """Test topup with invalid amount format.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.text = f"/topup {sample_user.id} invalid"
            mock_message.answer = AsyncMock()

            # Call handler
            await admin.cmd_topup(mock_message, test_session)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "Invalid amount" in response

    async def test_topup_missing_arguments(self, test_session):
        """Test topup with missing arguments.

        Args:
            test_session: Async session fixture.
        """
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.text = "/topup"  # No arguments
            mock_message.answer = AsyncMock()

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

    async def test_set_margin_valid_value(self):
        """Test setting valid margin value."""
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            # Store original value
            original_margin = config.DEFAULT_OWNER_MARGIN

            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.from_user.username = "admin_user"
            mock_message.text = "/set_margin 0.10"  # Set 10% margin
            mock_message.answer = AsyncMock()

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

    async def test_set_margin_zero(self):
        """Test setting margin to zero (no profit)."""
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            original_margin = config.DEFAULT_OWNER_MARGIN

            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.from_user.username = "admin_user"
            mock_message.text = "/set_margin 0.0"
            mock_message.answer = AsyncMock()

            await admin.cmd_set_margin(mock_message)

            # Verify margin set to 0
            assert config.DEFAULT_OWNER_MARGIN == 0.0

            mock_message.answer.assert_called_once()

            # Restore
            config.DEFAULT_OWNER_MARGIN = original_margin

    async def test_set_margin_exceeds_max(self):
        """Test setting margin that exceeds maximum allowed.

        k1 + k2 + k3 must not exceed 1.0.
        """
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.text = "/set_margin 0.60"  # Too high (k1=0.35, k2=0.15)
            mock_message.answer = AsyncMock()

            # Call handler
            await admin.cmd_set_margin(mock_message)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "exceeds 100%" in response or "Maximum" in response

    async def test_set_margin_negative(self):
        """Test setting negative margin (invalid)."""
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.text = "/set_margin -0.10"  # Negative
            mock_message.answer = AsyncMock()

            await admin.cmd_set_margin(mock_message)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "range [0, 1]" in response or "must be" in response.lower()

    async def test_set_margin_unauthorized(self):
        """Test that non-privileged user cannot set margin."""
        regular_user_id = 222222222
        with patch.object(config, 'PRIVILEGED_USERS', set()):  # Empty
            original_margin = config.DEFAULT_OWNER_MARGIN

            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = regular_user_id
            mock_message.from_user.username = "regular_user"
            mock_message.text = "/set_margin 0.50"
            mock_message.answer = AsyncMock()

            await admin.cmd_set_margin(mock_message)

            # Verify margin unchanged
            assert config.DEFAULT_OWNER_MARGIN == original_margin

            # Verify unauthorized message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "privileged users" in response.lower()

    async def test_set_margin_invalid_format(self):
        """Test setting margin with invalid format."""
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.text = "/set_margin invalid"
            mock_message.answer = AsyncMock()

            await admin.cmd_set_margin(mock_message)

            # Verify error message
            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "Invalid" in response

    async def test_set_margin_no_arguments(self):
        """Test /set_margin with no arguments (shows usage)."""
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.text = "/set_margin"  # No arguments
            mock_message.answer = AsyncMock()

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

    async def test_is_privileged_function(self):
        """Test is_privileged() helper function."""
        privileged_id = 123456
        regular_id = 999999

        with patch.object(config, 'PRIVILEGED_USERS', {privileged_id}):
            # Privileged user
            assert admin.is_privileged(privileged_id) is True

            # Regular user
            assert admin.is_privileged(regular_id) is False

    async def test_empty_privileged_set(self):
        """Test behavior when no privileged users configured."""
        with patch.object(config, 'PRIVILEGED_USERS', set()):
            # Nobody should be privileged
            assert admin.is_privileged(123456) is False
            assert admin.is_privileged(999999) is False

    async def test_multiple_privileged_users(self):
        """Test multiple privileged users."""
        admin1 = 111111
        admin2 = 222222
        regular = 333333

        with patch.object(config, 'PRIVILEGED_USERS', {admin1, admin2}):
            assert admin.is_privileged(admin1) is True
            assert admin.is_privileged(admin2) is True
            assert admin.is_privileged(regular) is False


@pytest.mark.asyncio
class TestClearCommand:
    """Test /clear admin command for deleting forum topics."""

    async def test_clear_unauthorized_user(self, test_session):
        """Test that non-privileged user cannot use /clear.

        Args:
            test_session: Async session fixture.
        """
        regular_user_id = 222222222
        with patch.object(config, 'PRIVILEGED_USERS', set()):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = regular_user_id
            mock_message.from_user.username = "regular_user"
            mock_message.chat = Mock()
            mock_message.chat.id = 123456789
            mock_message.text = "/clear"
            mock_message.message_thread_id = None
            mock_message.answer = AsyncMock()

            await admin.cmd_clear(mock_message, test_session)

            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "privileged users" in response.lower()

    async def test_clear_no_topics(self, test_session):
        """Test /clear when no topics exist.

        Args:
            test_session: Async session fixture.
        """
        admin_user_id = 111111111
        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.chat = Mock()
            mock_message.chat.id = 999999999  # Chat with no topics
            mock_message.text = "/clear"
            mock_message.message_thread_id = None  # General
            mock_message.answer = AsyncMock()

            await admin.cmd_clear(mock_message, test_session)

            mock_message.answer.assert_called_once()
            response = mock_message.answer.call_args[0][0]
            assert "No forum topics" in response

    async def test_clear_all_from_general(self, test_session):
        """Test /clear from General deletes all topics.

        Args:
            test_session: Async session fixture.
        """
        from db.repositories.thread_repository import ThreadRepository

        admin_user_id = 111111111
        chat_id = 888888888

        # Create some threads with topics
        thread_repo = ThreadRepository(test_session)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=1001)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=1002)
        await test_session.flush()  # Flush instead of commit

        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.chat = Mock()
            mock_message.chat.id = chat_id
            mock_message.text = "/clear"
            mock_message.message_thread_id = None  # General
            mock_message.answer = AsyncMock()
            mock_message.bot = Mock()
            mock_message.bot.delete_forum_topic = AsyncMock()
            mock_message.bot.send_message = AsyncMock()

            await admin.cmd_clear(mock_message, test_session)

            # Should delete both topics
            assert mock_message.bot.delete_forum_topic.call_count == 2
            mock_message.bot.send_message.assert_called_once()
            assert "All topics cleared" in mock_message.bot.send_message.call_args[
                0][1]

    async def test_clear_single_topic(self, test_session):
        """Test /clear in a topic deletes only that topic.

        Args:
            test_session: Async session fixture.
        """
        from db.repositories.thread_repository import ThreadRepository

        admin_user_id = 111111111
        chat_id = 666666666

        # Create threads
        thread_repo = ThreadRepository(test_session)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=3001)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=3002)
        await test_session.flush()  # Flush instead of commit

        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.chat = Mock()
            mock_message.chat.id = chat_id
            mock_message.text = "/clear"  # No "all"
            mock_message.message_thread_id = 3001  # From topic 3001
            mock_message.answer = AsyncMock()
            mock_message.bot = Mock()
            mock_message.bot.delete_forum_topic = AsyncMock()
            mock_message.bot.send_message = AsyncMock()

            await admin.cmd_clear(mock_message, test_session)

            # Should delete only topic 3001
            mock_message.bot.delete_forum_topic.assert_called_once()
            call_kwargs = mock_message.bot.delete_forum_topic.call_args[1]
            assert call_kwargs["message_thread_id"] == 3001

            # No "All topics cleared" message for single mode
            mock_message.bot.send_message.assert_not_called()

    async def test_clear_general_topic_id_1(self, test_session):
        """Test /clear with topic_id=1 (General) deletes all.

        Args:
            test_session: Async session fixture.
        """
        from db.repositories.thread_repository import ThreadRepository

        admin_user_id = 111111111
        chat_id = 555555555

        thread_repo = ThreadRepository(test_session)
        await thread_repo.get_or_create_thread(chat_id=chat_id,
                                               user_id=admin_user_id,
                                               thread_id=4001)
        await test_session.flush()  # Flush instead of commit

        with patch.object(config, 'PRIVILEGED_USERS', {admin_user_id}):
            mock_message = Mock()
            mock_message.from_user = Mock()
            mock_message.from_user.id = admin_user_id
            mock_message.chat = Mock()
            mock_message.chat.id = chat_id
            mock_message.text = "/clear"
            mock_message.message_thread_id = 1  # General topic ID
            mock_message.answer = AsyncMock()
            mock_message.bot = Mock()
            mock_message.bot.delete_forum_topic = AsyncMock()
            mock_message.bot.send_message = AsyncMock()

            await admin.cmd_clear(mock_message, test_session)

            # Should delete the topic (all mode)
            mock_message.bot.delete_forum_topic.assert_called_once()
            mock_message.bot.send_message.assert_called_once()
