"""Balance middleware tests (Phase 2.1 Stage 9).

Tests middleware that blocks paid requests when balance is insufficient.

NO __init__.py - use direct import:
    pytest tests/telegram/middlewares/test_balance_middleware.py
"""

from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch

from aiogram.types import CallbackQuery
from aiogram.types import Chat
from aiogram.types import Message
from aiogram.types import User
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.user_repository import UserRepository
import pytest
from services.balance_service import BalanceService
from telegram.middlewares.balance_middleware import BalanceMiddleware


@pytest.mark.asyncio
class TestBalanceMiddlewareFreeCommands:
    """Test that free commands bypass balance check."""

    @pytest.mark.parametrize("command", [
        "/start",
        "/help",
        "/pay",
        "/balance",
        "/refund",
        "/paysupport",
        "/topup",
        "/set_margin",
        "/model",
    ])
    async def test_free_commands_always_allowed(self, test_session, sample_user,
                                                command):
        """Test that free commands work even with zero balance.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
            command: Command to test.
        """
        # Setup: User with ZERO balance
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(sample_user.id)
        user.balance = Decimal("0.00")
        await test_session.flush()

        # Create middleware
        middleware = BalanceMiddleware()

        # Mock handler (should be called)
        mock_handler = AsyncMock(return_value="handler_result")

        # Create mock message with command
        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = command
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        # Call middleware
        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Verify handler was called (command not blocked)
        mock_handler.assert_called_once_with(mock_message, data)
        assert result == "handler_result"

        # Verify no blocking message sent
        mock_message.answer.assert_not_called()

    async def test_command_with_arguments_allowed(self, test_session,
                                                  sample_user):
        """Test that commands with arguments are recognized as free.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: User with ZERO balance
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(sample_user.id)
        user.balance = Decimal("0.00")
        await test_session.flush()

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock(return_value="ok")

        # Command with arguments
        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "/pay 100"  # Command with argument
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Should be allowed (free command)
        mock_handler.assert_called_once()
        assert result == "ok"


@pytest.mark.asyncio
class TestBalanceMiddlewarePaidRequests:
    """Test that paid requests are blocked when balance insufficient."""

    async def test_text_message_blocked_zero_balance(self, test_session,
                                                     sample_user):
        """Test that text messages are blocked when balance is zero.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: User with ZERO balance
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(sample_user.id)
        user.balance = Decimal("0.00")
        await test_session.flush()

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock()

        # Non-command message (paid request)
        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "Hello Claude!"  # Regular message
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Should be blocked
        mock_handler.assert_not_called()
        assert result is None

        # Should send blocking message
        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Insufficient balance" in call_args
        assert "/pay" in call_args

    async def test_text_message_allowed_positive_balance(
            self, test_session, sample_user):
        """Test that text messages work when balance is positive.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: User with positive balance
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(sample_user.id)
        user.balance = Decimal("0.10")
        await test_session.flush()

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock(return_value="processed")

        # Non-command message
        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "Hello Claude!"
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Should be allowed
        mock_handler.assert_called_once()
        assert result == "processed"

        # No blocking message
        mock_message.answer.assert_not_called()

    async def test_callback_query_blocked_zero_balance(self, test_session,
                                                       sample_user):
        """Test that callback queries are blocked when balance is zero.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: User with ZERO balance
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(sample_user.id)
        user.balance = Decimal("0.00")
        await test_session.flush()

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock()

        # Create mock callback query
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.message = Mock(spec=Message)
        mock_callback.message.from_user = Mock(spec=User)
        mock_callback.message.from_user.id = sample_user.id
        mock_callback.message.from_user.is_bot = False
        mock_callback.message.from_user.language_code = "en"
        mock_callback.message.text = ""
        mock_callback.message.caption = None
        mock_callback.message.answer = AsyncMock()
        mock_callback.message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_callback, data)

        # Should be blocked
        mock_handler.assert_not_called()
        assert result is None

        # Should send blocking message
        mock_callback.message.answer.assert_called_once()

    async def test_negative_balance_blocked(self, test_session, sample_user):
        """Test that negative balance blocks requests.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: User with NEGATIVE balance (after expensive request)
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(sample_user.id)
        user.balance = Decimal("-0.05")
        await test_session.flush()

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock()

        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "Another request"
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Should be blocked (balance <= 0)
        mock_handler.assert_not_called()
        assert result is None


@pytest.mark.asyncio
class TestBalanceMiddlewareEdgeCases:
    """Test edge cases and error handling."""

    async def test_no_session_fails_open(self, sample_user):
        """Test that middleware allows request if session not available.

        Fail-open behavior: if middleware can't check balance, allow request.

        Args:
            sample_user: Sample user fixture.
        """
        middleware = BalanceMiddleware()
        mock_handler = AsyncMock(return_value="allowed")

        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "Hello"
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        # No session in data (fail-open)
        data = {}
        result = await middleware(mock_handler, mock_message, data)

        # Should allow (fail-open)
        mock_handler.assert_called_once()
        assert result == "allowed"

    async def test_unregistered_user_auto_registered(self, test_session,
                                                     sample_user):
        """Test that unregistered users are auto-registered.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        import random
        new_user_id = random.randint(100000000, 999999998)

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock(return_value="allowed")

        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = new_user_id  # Non-existent user
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.from_user.first_name = "Test"
        mock_message.from_user.last_name = "User"
        mock_message.from_user.username = f"test_user_{new_user_id}"
        mock_message.from_user.language_code = "en"
        mock_message.from_user.is_premium = False
        mock_message.from_user.added_to_attachment_menu = False
        mock_message.text = "Hello"
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}

        result = await middleware(mock_handler, mock_message, data)

        # User should be auto-registered and request allowed
        # (new users get starter balance $0.10)
        mock_handler.assert_called_once()
        assert result == "allowed"

        # Verify user was created in database
        from db.repositories.user_repository import UserRepository
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(new_user_id)
        assert user is not None
        assert user.username == f"test_user_{new_user_id}"

    async def test_balance_check_error_fails_open(self, test_session,
                                                  sample_user):
        """Test that balance check errors don't block requests.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        from unittest.mock import patch

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock(return_value="allowed")

        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "Hello"
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}

        # Mock can_make_request to raise an exception (database error)
        mock_balance_service = MagicMock()
        mock_balance_service.can_make_request = AsyncMock(
            side_effect=Exception("Database error"))

        mock_services = MagicMock()
        mock_services.balance = mock_balance_service

        with patch('telegram.middlewares.balance_middleware.ServiceFactory',
                   return_value=mock_services):
            # Patch logger.error to avoid rich rendering Mock objects
            with patch('telegram.middlewares.balance_middleware.logger.error'):
                result = await middleware(mock_handler, mock_message, data)

        # Should allow (fail-open on error)
        mock_handler.assert_called_once()
        assert result == "allowed"

    async def test_empty_message_allowed(self, test_session, sample_user):
        """Test that empty messages are handled gracefully.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        middleware = BalanceMiddleware()
        mock_handler = AsyncMock(return_value="ok")

        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = None
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Empty message treated as paid request - check balance
        # With sample_user starter balance ($0.10), should be allowed
        mock_handler.assert_called_once()
        assert result == "ok"

    async def test_unknown_command_blocked_zero_balance(self, test_session,
                                                        sample_user):
        """Test that unknown commands are blocked with zero balance.

        Unknown commands (not in FREE_COMMANDS) are treated as paid requests
        and should be blocked when balance is insufficient.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: User with ZERO balance
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(sample_user.id)
        user.balance = Decimal("0.00")
        await test_session.flush()

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock(return_value="ok")

        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "/unknown_command"  # Not in FREE_COMMANDS
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Should be blocked (unknown commands are paid requests)
        mock_handler.assert_not_called()
        assert result is None
        mock_message.answer.assert_called_once()


@pytest.mark.asyncio
class TestBalanceMiddlewareIntegration:
    """Integration tests for balance middleware with real services."""

    async def test_middleware_with_real_balance_service(self, test_session,
                                                        sample_user):
        """Test middleware using real BalanceService.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: Spend all user's balance
        user_repo = UserRepository(test_session)
        balance_op_repo = BalanceOperationRepository(test_session)
        balance_service = BalanceService(test_session, user_repo,
                                         balance_op_repo)

        user = await user_repo.get_by_id(sample_user.id)
        await balance_service.charge_user(
            user_id=user.id,
            amount=user.balance,  # Spend everything
            description="Test charge",
        )

        # Verify balance is zero
        balance = await balance_service.get_balance(user.id)
        assert balance == Decimal("0.00")

        # Test middleware blocks request
        middleware = BalanceMiddleware()
        mock_handler = AsyncMock()

        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "Paid request"
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Should be blocked
        mock_handler.assert_not_called()
        assert result is None
        mock_message.answer.assert_called_once()

    async def test_soft_balance_check_one_request_allowed(
            self, test_session, sample_user):
        """Test soft balance check: allow one request if balance > 0.

        Args:
            test_session: Async session fixture.
            sample_user: Sample user fixture.
        """
        # Setup: User with $0.01
        user_repo = UserRepository(test_session)
        user = await user_repo.get_by_id(sample_user.id)
        user.balance = Decimal("0.01")
        await test_session.flush()

        middleware = BalanceMiddleware()
        mock_handler = AsyncMock(return_value="allowed")

        mock_message = Mock(spec=Message)
        mock_message.from_user = Mock(spec=User)
        mock_message.from_user.id = sample_user.id
        mock_message.from_user.is_bot = False
        mock_message.from_user.language_code = "en"
        mock_message.text = "Expensive request"
        mock_message.caption = None
        mock_message.answer = AsyncMock()
        mock_message.successful_payment = None

        data = {"session": test_session}
        result = await middleware(mock_handler, mock_message, data)

        # Should be allowed (balance > 0, soft check)
        mock_handler.assert_called_once()
        assert result == "allowed"
        mock_message.answer.assert_not_called()
