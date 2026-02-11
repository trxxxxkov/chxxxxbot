"""Tests for payment handlers.

Comprehensive tests for telegram/handlers/payment.py:
- cmd_pay - Show Stars packages
- callback_buy_stars - Handle package selection
- process_custom_amount - Custom amount FSM
- process_pre_checkout_query - Pre-checkout validation
- process_successful_payment - Payment processing
- cmd_refund - Refund command
- cmd_balance - Balance command
- cmd_paysupport - Support command
"""

from datetime import datetime
from datetime import timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.types import Message
from aiogram.types import PreCheckoutQuery
from aiogram.types import User
import pytest

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_session():
    """Create mock database session."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_user():
    """Create mock Telegram User."""
    user = MagicMock(spec=User)
    user.id = 123456
    user.is_bot = False
    user.first_name = "Test"
    user.last_name = "User"
    user.username = "testuser"
    user.language_code = "en"
    user.is_premium = False
    user.added_to_attachment_menu = False
    user.allows_users_to_create_topics = False
    return user


@pytest.fixture
def mock_message(mock_user):
    """Create mock Telegram message."""
    message = MagicMock(spec=Message)
    message.from_user = mock_user
    message.chat = MagicMock()
    message.chat.id = 789012
    message.message_thread_id = None
    message.text = "/pay"
    message.answer = AsyncMock()
    message.bot = MagicMock()
    return message


@pytest.fixture
def mock_fsm_context():
    """Create mock FSM context."""
    context = MagicMock(spec=FSMContext)
    context.set_state = AsyncMock()
    context.clear = AsyncMock()
    context.get_state = AsyncMock(return_value=None)
    return context


@pytest.fixture
def mock_services():
    """Create mock ServiceFactory."""
    services = MagicMock()

    # Mock users service
    services.users = MagicMock()
    services.users.get_or_create = AsyncMock()

    # Mock payment service
    services.payment = MagicMock()
    services.payment.calculate_usd_amount = MagicMock(
        return_value=(100, Decimal("1.30"), Decimal("0.03"), Decimal("0.02"),
                      Decimal("1.35")))
    services.payment.send_invoice = AsyncMock()
    services.payment.process_successful_payment = AsyncMock()
    services.payment.process_refund = AsyncMock()

    # Mock balance service
    services.balance = MagicMock()
    services.balance.get_balance = AsyncMock(return_value=Decimal("10.00"))
    services.balance.get_balance_history = AsyncMock(return_value=[])

    return services


# ============================================================================
# Tests for cmd_pay
# ============================================================================


class TestCmdPay:
    """Tests for /pay command handler."""

    @pytest.mark.asyncio
    async def test_pay_shows_packages(
        self,
        mock_message,
        mock_fsm_context,
        mock_session,
        mock_services,
    ):
        """Should display Stars packages with inline keyboard."""
        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                with patch("telegram.handlers.payment.log_bot_response"):
                    from telegram.handlers.payment import cmd_pay

                    await cmd_pay(mock_message, mock_fsm_context, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        response_text = call_args[0][0]

        # Verify response contains key elements
        assert "Top-up your balance" in response_text
        assert "reply_markup" in call_args[1]

    @pytest.mark.asyncio
    async def test_pay_no_user(
        self,
        mock_message,
        mock_fsm_context,
        mock_session,
    ):
        """Should handle missing from_user."""
        mock_message.from_user = None

        from telegram.handlers.payment import cmd_pay

        await cmd_pay(mock_message, mock_fsm_context, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Unable to identify user" in call_args

    @pytest.mark.asyncio
    async def test_pay_creates_user_if_needed(
        self,
        mock_message,
        mock_fsm_context,
        mock_session,
        mock_services,
    ):
        """Should auto-create user in database."""
        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                with patch("telegram.handlers.payment.log_bot_response"):
                    from telegram.handlers.payment import cmd_pay

                    await cmd_pay(mock_message, mock_fsm_context, mock_session)

        mock_services.users.get_or_create.assert_called_once()


# ============================================================================
# Tests for callback_buy_stars
# ============================================================================


class TestCallbackBuyStars:
    """Tests for Stars package selection callback."""

    @pytest.fixture
    def mock_callback(self, mock_user, mock_message):
        """Create mock callback query."""
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = mock_user
        callback.data = "buy_stars:100"
        callback.message = mock_message
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()
        return callback

    @pytest.mark.asyncio
    async def test_select_package_sends_invoice(
        self,
        mock_callback,
        mock_fsm_context,
        mock_session,
        mock_services,
    ):
        """Should send invoice when package selected."""
        mock_callback.data = "buy_stars:100"

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                from telegram.handlers.payment import callback_buy_stars

                await callback_buy_stars(mock_callback, mock_fsm_context,
                                         mock_session)

        mock_services.payment.send_invoice.assert_called_once()
        mock_callback.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_custom_enters_fsm_state(
        self,
        mock_callback,
        mock_fsm_context,
        mock_session,
    ):
        """Should enter FSM state when custom selected."""
        mock_callback.data = "buy_stars:custom"

        with patch("telegram.handlers.payment.logger"):
            from telegram.handlers.payment import BuyStarsStates
            from telegram.handlers.payment import callback_buy_stars

            await callback_buy_stars(mock_callback, mock_fsm_context,
                                     mock_session)

        mock_fsm_context.set_state.assert_called_once_with(
            BuyStarsStates.waiting_for_custom_amount)
        mock_callback.message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_amount_shows_alert(
        self,
        mock_callback,
        mock_fsm_context,
        mock_session,
    ):
        """Should show alert for invalid callback data."""
        mock_callback.data = "buy_stars:invalid"

        with patch("telegram.handlers.payment.logger"):
            from telegram.handlers.payment import callback_buy_stars

            await callback_buy_stars(mock_callback, mock_fsm_context,
                                     mock_session)

        mock_callback.answer.assert_called_once_with(
            "Invalid amount",
            show_alert=True,
        )


# ============================================================================
# Tests for process_custom_amount
# ============================================================================


class TestProcessCustomAmount:
    """Tests for custom amount FSM handler."""

    @pytest.mark.asyncio
    async def test_valid_custom_amount_sends_invoice(
        self,
        mock_message,
        mock_fsm_context,
        mock_session,
        mock_services,
    ):
        """Should send invoice for valid custom amount."""
        mock_message.text = "500"

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                from telegram.handlers.payment import process_custom_amount

                await process_custom_amount(mock_message, mock_fsm_context,
                                            mock_session)

        mock_fsm_context.clear.assert_called_once()
        mock_services.payment.send_invoice.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_text_rejected(
        self,
        mock_message,
        mock_fsm_context,
        mock_session,
    ):
        """Should reject non-numeric input."""
        mock_message.text = "not a number"

        with patch("telegram.handlers.payment.logger"):
            from telegram.handlers.payment import process_custom_amount

            await process_custom_amount(mock_message, mock_fsm_context,
                                        mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Invalid input" in call_args
        mock_fsm_context.clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_amount_below_minimum_rejected(
        self,
        mock_message,
        mock_fsm_context,
        mock_session,
    ):
        """Should reject amount below minimum."""
        mock_message.text = "10"  # Below MIN_CUSTOM_STARS (usually 50)

        with patch("telegram.handlers.payment.MIN_CUSTOM_STARS", 50):
            with patch("telegram.handlers.payment.MAX_CUSTOM_STARS", 10000):
                with patch("telegram.handlers.payment.logger"):
                    from telegram.handlers.payment import process_custom_amount

                    await process_custom_amount(mock_message, mock_fsm_context,
                                                mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "must be between" in call_args

    @pytest.mark.asyncio
    async def test_amount_above_maximum_rejected(
        self,
        mock_message,
        mock_fsm_context,
        mock_session,
    ):
        """Should reject amount above maximum."""
        mock_message.text = "50000"  # Above MAX_CUSTOM_STARS

        with patch("telegram.handlers.payment.MIN_CUSTOM_STARS", 50):
            with patch("telegram.handlers.payment.MAX_CUSTOM_STARS", 10000):
                with patch("telegram.handlers.payment.logger"):
                    from telegram.handlers.payment import process_custom_amount

                    await process_custom_amount(mock_message, mock_fsm_context,
                                                mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "must be between" in call_args

    @pytest.mark.asyncio
    async def test_non_text_message_rejected(
        self,
        mock_message,
        mock_fsm_context,
        mock_session,
    ):
        """Should reject non-text messages (stickers, photos)."""
        mock_message.text = None

        from telegram.handlers.payment import process_custom_amount

        await process_custom_amount(mock_message, mock_fsm_context,
                                    mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "send a number" in call_args


# ============================================================================
# Tests for process_pre_checkout_query
# ============================================================================


class TestProcessPreCheckoutQuery:
    """Tests for pre-checkout query handler."""

    @pytest.fixture
    def mock_pre_checkout(self, mock_user):
        """Create mock pre-checkout query."""
        query = MagicMock(spec=PreCheckoutQuery)
        query.from_user = mock_user
        query.currency = "XTR"
        query.total_amount = 100
        query.invoice_payload = "topup_123456_1234567890_100"
        query.answer = AsyncMock()
        return query

    @pytest.mark.asyncio
    async def test_valid_checkout_approved(
        self,
        mock_pre_checkout,
        mock_session,
    ):
        """Should approve valid pre-checkout query."""
        with patch("telegram.handlers.payment.logger"):
            from telegram.handlers.payment import process_pre_checkout_query

            await process_pre_checkout_query(mock_pre_checkout, mock_session)

        mock_pre_checkout.answer.assert_called_once_with(ok=True)

    @pytest.mark.asyncio
    async def test_invalid_payload_rejected(
        self,
        mock_pre_checkout,
        mock_session,
    ):
        """Should reject invalid invoice payload."""
        mock_pre_checkout.invoice_payload = "invalid_payload"

        with patch("telegram.handlers.payment.logger"):
            from telegram.handlers.payment import process_pre_checkout_query

            await process_pre_checkout_query(mock_pre_checkout, mock_session)

        mock_pre_checkout.answer.assert_called_once()
        call_kwargs = mock_pre_checkout.answer.call_args[1]
        assert call_kwargs["ok"] is False
        assert "Invalid invoice" in call_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_invalid_currency_rejected(
        self,
        mock_pre_checkout,
        mock_session,
    ):
        """Should reject non-XTR currency."""
        mock_pre_checkout.currency = "USD"

        with patch("telegram.handlers.payment.logger"):
            from telegram.handlers.payment import process_pre_checkout_query

            await process_pre_checkout_query(mock_pre_checkout, mock_session)

        mock_pre_checkout.answer.assert_called_once()
        call_kwargs = mock_pre_checkout.answer.call_args[1]
        assert call_kwargs["ok"] is False
        assert "currency" in call_kwargs["error_message"].lower()


# ============================================================================
# Tests for process_successful_payment
# ============================================================================


class TestProcessSuccessfulPayment:
    """Tests for successful payment handler."""

    @pytest.fixture
    def mock_successful_payment(self):
        """Create mock successful payment data."""
        payment = MagicMock()
        payment.currency = "XTR"
        payment.total_amount = 100
        payment.telegram_payment_charge_id = "tg_charge_123"
        payment.invoice_payload = "topup_123456_1234567890_100"
        return payment

    @pytest.fixture
    def mock_payment_record(self):
        """Create mock payment record."""
        record = MagicMock()
        record.id = 1
        record.credited_usd_amount = Decimal("1.30")
        record.stars_amount = 100
        return record

    @pytest.mark.asyncio
    async def test_successful_payment_credits_balance(
        self,
        mock_message,
        mock_session,
        mock_services,
        mock_successful_payment,
        mock_payment_record,
    ):
        """Should process payment and credit balance."""
        mock_message.successful_payment = mock_successful_payment
        mock_services.payment.process_successful_payment.return_value = mock_payment_record

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                from telegram.handlers.payment import \
                    process_successful_payment

                await process_successful_payment(mock_message, mock_session)

        mock_services.payment.process_successful_payment.assert_called_once_with(
            user_id=123456,
            telegram_payment_charge_id="tg_charge_123",
            stars_amount=100,
            invoice_payload="topup_123456_1234567890_100",
            owner_margin=pytest.approx(0.05, abs=0.1),  # DEFAULT_OWNER_MARGIN
        )

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Payment successful" in call_args
        assert "$1.30" in call_args

    @pytest.mark.asyncio
    async def test_payment_error_shows_support(
        self,
        mock_message,
        mock_session,
        mock_services,
        mock_successful_payment,
    ):
        """Should show support message on payment error."""
        mock_message.successful_payment = mock_successful_payment
        mock_services.payment.process_successful_payment.side_effect = Exception(
            "DB error")

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                from telegram.handlers.payment import \
                    process_successful_payment

                await process_successful_payment(mock_message, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "error" in call_args.lower()
        assert "paysupport" in call_args.lower()


# ============================================================================
# Tests for cmd_refund
# ============================================================================


class TestCmdRefund:
    """Tests for /refund command handler."""

    @pytest.fixture
    def mock_payment_record(self):
        """Create mock payment record for refund."""
        record = MagicMock()
        record.id = 1
        record.stars_amount = 100
        record.credited_usd_amount = Decimal("1.30")
        return record

    @pytest.mark.asyncio
    async def test_refund_no_args_shows_help(
        self,
        mock_message,
        mock_session,
        mock_services,
    ):
        """Should show help when no transaction ID provided."""
        mock_message.text = "/refund"

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            from telegram.handlers.payment import cmd_refund

            await cmd_refund(mock_message, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Refund Instructions" in call_args

    @pytest.mark.asyncio
    async def test_refund_success(
        self,
        mock_message,
        mock_session,
        mock_services,
        mock_payment_record,
    ):
        """Should process refund successfully."""
        mock_message.text = "/refund tg_charge_123"
        mock_message.bot.refund_star_payment = AsyncMock(return_value=True)
        mock_services.payment.process_refund.return_value = mock_payment_record

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                from telegram.handlers.payment import cmd_refund

                await cmd_refund(mock_message, mock_session)

        mock_services.payment.process_refund.assert_called_once_with(
            123456,
            "tg_charge_123",
        )
        mock_message.bot.refund_star_payment.assert_called_once()
        mock_message.answer.assert_called()
        call_args = mock_message.answer.call_args[0][0]
        assert "Refund successful" in call_args

    @pytest.mark.asyncio
    async def test_refund_telegram_api_failure_rollback(
        self,
        mock_message,
        mock_session,
        mock_services,
        mock_payment_record,
    ):
        """Should rollback on Telegram API failure."""
        mock_message.text = "/refund tg_charge_123"
        mock_message.bot.refund_star_payment = AsyncMock(return_value=False)
        mock_services.payment.process_refund.return_value = mock_payment_record

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                from telegram.handlers.payment import cmd_refund

                await cmd_refund(mock_message, mock_session)

        mock_session.rollback.assert_called_once()
        mock_message.answer.assert_called()
        call_args = mock_message.answer.call_args[0][0]
        assert "failed" in call_args.lower()

    @pytest.mark.asyncio
    async def test_refund_validation_error(
        self,
        mock_message,
        mock_session,
        mock_services,
    ):
        """Should show error for validation failures."""
        mock_message.text = "/refund tg_charge_123"
        mock_services.payment.process_refund.side_effect = ValueError(
            "Refund period expired")

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                from telegram.handlers.payment import cmd_refund

                await cmd_refund(mock_message, mock_session)

        mock_message.answer.assert_called()
        call_args = mock_message.answer.call_args[0][0]
        assert "Refund failed" in call_args
        assert "Refund period expired" in call_args

    @pytest.mark.asyncio
    async def test_refund_no_user(
        self,
        mock_message,
        mock_session,
    ):
        """Should handle missing from_user."""
        mock_message.from_user = None
        mock_message.text = "/refund tg_charge_123"

        from telegram.handlers.payment import cmd_refund

        await cmd_refund(mock_message, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Unable to identify user" in call_args


# ============================================================================
# Tests for cmd_balance
# ============================================================================


class TestCmdBalance:
    """Tests for /balance command handler."""

    @pytest.fixture
    def mock_balance_operations(self):
        """Create mock balance operations."""
        op1 = MagicMock()
        op1.created_at = datetime(2026, 1, 27, 12, 0, tzinfo=timezone.utc)
        op1.amount = Decimal("1.30")
        op1.operation_type = "payment"

        op2 = MagicMock()
        op2.created_at = datetime(2026, 1, 27, 13, 0, tzinfo=timezone.utc)
        op2.amount = Decimal("-0.05")
        op2.operation_type = "usage"

        return [op1, op2]

    @pytest.mark.asyncio
    async def test_balance_shows_current_and_history(
        self,
        mock_message,
        mock_session,
        mock_services,
        mock_balance_operations,
    ):
        """Should display balance and history."""
        mock_services.balance.get_balance_history.return_value = mock_balance_operations

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                with patch("telegram.handlers.payment.log_bot_response"):
                    from telegram.handlers.payment import cmd_balance

                    await cmd_balance(mock_message, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Your Balance" in call_args
        assert "$10.00" in call_args
        assert "payment" in call_args

    @pytest.mark.asyncio
    async def test_balance_no_history(
        self,
        mock_message,
        mock_session,
        mock_services,
    ):
        """Should handle empty history."""
        mock_services.balance.get_balance_history.return_value = []

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                with patch("telegram.handlers.payment.log_bot_response"):
                    from telegram.handlers.payment import cmd_balance

                    await cmd_balance(mock_message, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "No history yet" in call_args

    @pytest.mark.asyncio
    async def test_balance_error_handling(
        self,
        mock_message,
        mock_session,
        mock_services,
    ):
        """Should handle balance retrieval errors."""
        mock_services.balance.get_balance.side_effect = Exception("DB error")

        with patch(
                "telegram.handlers.payment.ServiceFactory",
                return_value=mock_services,
        ):
            with patch("telegram.handlers.payment.logger"):
                from telegram.handlers.payment import cmd_balance

                await cmd_balance(mock_message, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Failed to retrieve" in call_args

    @pytest.mark.asyncio
    async def test_balance_no_user(
        self,
        mock_message,
        mock_session,
    ):
        """Should handle missing from_user."""
        mock_message.from_user = None

        from telegram.handlers.payment import cmd_balance

        await cmd_balance(mock_message, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Unable to identify user" in call_args


# ============================================================================
# Tests for cmd_paysupport
# ============================================================================


class TestCmdPaysupport:
    """Tests for /paysupport command handler."""

    @pytest.mark.asyncio
    async def test_paysupport_shows_info(
        self,
        mock_message,
        mock_session,
    ):
        """Should display support information."""
        with patch("telegram.handlers.payment.logger"):
            with patch("telegram.handlers.payment.log_bot_response"):
                from telegram.handlers.payment import cmd_paysupport

                await cmd_paysupport(mock_message, mock_session)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "Payment Support" in call_args
        assert "/balance" in call_args
        assert "/refund" in call_args
