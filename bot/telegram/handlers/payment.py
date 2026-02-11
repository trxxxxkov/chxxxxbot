"""Payment handlers for Telegram Stars integration.

This module handles all payment-related user interactions:
- /pay command with predefined packages and custom amount
- Pre-checkout query validation
- Successful payment processing
- /refund command with validation
- /balance command with history
- /paysupport command (required by Telegram)
"""

from aiogram import F
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.state import StatesGroup
from aiogram.types import CallbackQuery
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.types import Message
from aiogram.types import PreCheckoutQuery
from config import DEFAULT_OWNER_MARGIN
from config import MAX_CUSTOM_STARS
from config import MIN_CUSTOM_STARS
from config import STARS_PACKAGES
from i18n import get_lang
from i18n import get_text
from services.factory import ServiceFactory
from sqlalchemy.ext.asyncio import AsyncSession
from utils.bot_response import log_bot_response
from utils.structured_logging import get_logger

logger = get_logger(__name__)
router = Router(name="payment")


# FSM States for custom Stars amount
class BuyStarsStates(StatesGroup):
    """FSM states for buying Stars with custom amount."""

    waiting_for_custom_amount = State()


@router.message(Command("pay"))
async def cmd_pay(message: Message, state: FSMContext, session: AsyncSession):
    """Handler for /pay command - show Stars packages.

    Displays predefined packages + custom amount option.
    Each package shows: Label, Stars amount, and resulting USD balance.

    Args:
        message: Telegram message with /pay command.
        state: FSM context for custom amount flow.
        session: Database session from middleware.
    """
    if not message.from_user:
        await message.answer(get_text("common.unable_to_identify_user", "en"))
        return

    user = message.from_user
    user_id = user.id
    lang = get_lang(user.language_code)

    # Ensure user exists in database (auto-create if first interaction)
    services = ServiceFactory(session)
    await services.users.get_or_create(
        telegram_id=user.id,
        is_bot=user.is_bot,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        is_premium=user.is_premium or False,
        added_to_attachment_menu=user.added_to_attachment_menu or False,
        allows_users_to_create_topics=(user.allows_users_to_create_topics or
                                       False),
    )

    logger.info(
        "payment.pay_command",
        user_id=user_id,
        username=user.username,
    )

    # Calculate USD for each package (for display)
    # Create keyboard with packages
    keyboard_buttons = []

    for package in STARS_PACKAGES:
        stars = package["stars"]
        label = package["label"]

        try:
            _, credited_usd, _, _, _ = services.payment.calculate_usd_amount(
                stars, DEFAULT_OWNER_MARGIN)
            button_text = f"{label}: {stars}⭐ → ${credited_usd}"
            callback_data = f"buy_stars:{stars}"

            keyboard_buttons.append([
                InlineKeyboardButton(text=button_text,
                                     callback_data=callback_data)
            ])
        except Exception as e:
            logger.error(
                "payment.buy_package_calculation_error",
                user_id=user_id,
                stars=stars,
                error=str(e),
            )

    # Add custom amount button
    keyboard_buttons.append([
        InlineKeyboardButton(
            text=get_text("payment.custom_amount_button",
                          lang,
                          min=MIN_CUSTOM_STARS,
                          max=MAX_CUSTOM_STARS),
            callback_data="buy_stars:custom",
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    response_text = get_text("payment.topup_title", lang)
    await message.answer(response_text, reply_markup=keyboard)

    log_bot_response(
        "bot.pay_response",
        chat_id=message.chat.id,
        user_id=user_id,
        message_length=len(response_text),
    )


@router.callback_query(F.data.startswith("buy_stars:"))
async def callback_buy_stars(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Handle Stars package selection from inline keyboard."""
    user_id = callback.from_user.id
    data = callback.data.split(":", 1)[1]

    logger.info(
        "payment.package_selected",
        user_id=user_id,
        selection=data,
    )

    if data == "custom":
        # Ask for custom amount
        await state.set_state(BuyStarsStates.waiting_for_custom_amount)
        lang = get_lang(callback.from_user.language_code)
        await callback.message.edit_text(
            get_text("payment.enter_custom_amount",
                     lang,
                     min=MIN_CUSTOM_STARS,
                     max=MAX_CUSTOM_STARS))
        await callback.answer()
        return

    # Parse Stars amount
    try:
        stars_amount = int(data)
    except ValueError:
        logger.error(
            "payment.invalid_callback_data",
            user_id=user_id,
            data=data,
        )
        lang = get_lang(callback.from_user.language_code)
        await callback.answer(get_text("payment.invalid_amount", lang),
                              show_alert=True)
        return

    # Send invoice
    await _send_invoice_to_user(callback.message, user_id, stars_amount,
                                session)
    await callback.answer()


@router.message(BuyStarsStates.waiting_for_custom_amount)
async def process_custom_amount(message: Message, state: FSMContext,
                                session: AsyncSession):
    """Process custom Stars amount input from user."""
    user_id = message.from_user.id
    lang = get_lang(message.from_user.language_code)

    # Check if message has text (could be sticker, photo, etc.)
    if not message.text:
        await message.answer(get_text("payment.invalid_not_number", lang))
        return

    try:
        stars_amount = int(message.text.strip())
    except ValueError:
        logger.info(
            "payment.invalid_custom_amount",
            user_id=user_id,
            text=message.text,
        )
        await message.answer(get_text("payment.invalid_number", lang))
        return

    if not (MIN_CUSTOM_STARS <= stars_amount <= MAX_CUSTOM_STARS):
        logger.info(
            "payment.custom_amount_out_of_range",
            user_id=user_id,
            stars_amount=stars_amount,
        )
        await message.answer(
            get_text("payment.amount_out_of_range",
                     lang,
                     min=MIN_CUSTOM_STARS,
                     max=MAX_CUSTOM_STARS))
        return

    await state.clear()

    # Send invoice
    await _send_invoice_to_user(message, user_id, stars_amount, session)


async def _send_invoice_to_user(
    message: Message,
    user_id: int,
    stars_amount: int,
    session: AsyncSession,
):
    """Helper to send payment invoice to user.

    Args:
        message: Message to reply to.
        user_id: Telegram user ID.
        stars_amount: Amount of Stars for payment.
        session: Database session from middleware.
    """
    logger.info(
        "payment.sending_invoice",
        user_id=user_id,
        stars_amount=stars_amount,
    )

    # Create services
    services = ServiceFactory(session)

    try:
        # Send invoice via Telegram (all info is in invoice description)
        await services.payment.send_invoice(
            message.bot,
            user_id,
            stars_amount,
            owner_margin=DEFAULT_OWNER_MARGIN,
            chat_id=message.chat.id,
            message_thread_id=message.message_thread_id,
        )

    except Exception as e:
        logger.info(
            "payment.send_invoice_error",
            user_id=user_id,
            stars_amount=stars_amount,
            error=str(e),
        )
        # Note: We don't have access to language_code here, use English fallback
        await message.answer(get_text("payment.invoice_error", "en"))


@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery,
                                     session: AsyncSession):
    """Handle pre-checkout query (approve/reject payment).

    This is called by Telegram BEFORE processing payment.
    We must answer to proceed.

    Validates:
    - Invoice payload format
    - Currency is XTR (Telegram Stars)
    """
    user_id = pre_checkout_query.from_user.id

    logger.info(
        "payment.pre_checkout_received",
        user_id=user_id,
        currency=pre_checkout_query.currency,
        total_amount=pre_checkout_query.total_amount,
        invoice_payload=pre_checkout_query.invoice_payload,
    )

    # Validate invoice payload format (topup_<user_id>_<timestamp>_<stars>)
    if not pre_checkout_query.invoice_payload.startswith("topup_"):
        logger.error(
            "payment.invalid_invoice_payload",
            user_id=user_id,
            payload=pre_checkout_query.invoice_payload,
            msg="Invalid invoice payload format",
        )
        lang = get_lang(pre_checkout_query.from_user.language_code)
        await pre_checkout_query.answer(ok=False,
                                        error_message=get_text(
                                            "payment.invalid_invoice", lang))
        return

    # Validate currency
    if pre_checkout_query.currency != "XTR":
        logger.error(
            "payment.invalid_currency",
            user_id=user_id,
            currency=pre_checkout_query.currency,
            msg="Invalid currency - only XTR (Stars) accepted",
        )
        lang = get_lang(pre_checkout_query.from_user.language_code)
        await pre_checkout_query.answer(
            ok=False,
            error_message=get_text("payment.invalid_currency", lang),
        )
        return

    # Approve payment
    await pre_checkout_query.answer(ok=True)

    logger.info(
        "payment.pre_checkout_approved",
        user_id=user_id,
        total_amount=pre_checkout_query.total_amount,
    )


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, session: AsyncSession):
    """Handle successful payment (credit user balance).

    This is called by Telegram AFTER payment is completed.
    Only now we deliver goods (add balance).

    Creates:
    - Payment record with commission breakdown
    - BalanceOperation for audit trail
    """
    user_id = message.from_user.id
    payment = message.successful_payment
    lang = get_lang(message.from_user.language_code)

    logger.info(
        "payment.successful_payment_received",
        user_id=user_id,
        currency=payment.currency,
        total_amount=payment.total_amount,
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
        invoice_payload=payment.invoice_payload,
        msg="Successful payment received from Telegram",
    )

    # Create services
    services = ServiceFactory(session)

    try:
        # Process payment (creates Payment record and credits balance)
        payment_record = await services.payment.process_successful_payment(
            user_id=user_id,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            stars_amount=payment.total_amount,
            invoice_payload=payment.invoice_payload,
            owner_margin=DEFAULT_OWNER_MARGIN,
        )

        # Get updated balance
        new_balance = await services.balance.get_balance(user_id)

        # Send confirmation with transaction ID
        await message.answer(
            get_text("payment.success",
                     lang,
                     credited_usd=payment_record.credited_usd_amount,
                     new_balance=new_balance,
                     transaction_id=payment.telegram_payment_charge_id))

        logger.info(
            "payment.success_confirmed",
            user_id=user_id,
            payment_id=payment_record.id,
            stars_amount=payment.total_amount,
            credited_usd=float(payment_record.credited_usd_amount),
            new_balance=float(new_balance),
            msg="Payment processed successfully and user notified",
        )

        # Separate event for dashboard tracking
        logger.info(
            "stars.donation_received",
            user_id=user_id,
            stars_amount=payment.total_amount,
            credited_usd=float(payment_record.credited_usd_amount),
        )

    except Exception as e:
        logger.error(
            "payment.process_error",
            user_id=user_id,
            charge_id=payment.telegram_payment_charge_id,
            error=str(e),
            exc_info=True,
            msg="CRITICAL: Failed to process successful payment!",
        )
        await message.answer(
            get_text("payment.processing_error",
                     lang,
                     transaction_id=payment.telegram_payment_charge_id))


@router.message(Command("refund"))
async def cmd_refund(message: Message, session: AsyncSession):
    """Handler for /refund command - refund a payment.

    Usage: /refund <transaction_id>

    Validates:
    - Payment exists and belongs to user
    - Payment status is COMPLETED
    - Within refund period (30 days)
    - User has sufficient balance
    """
    if not message.from_user:
        await message.answer(get_text("common.unable_to_identify_user", "en"))
        return

    user = message.from_user
    user_id = user.id
    lang = get_lang(user.language_code)

    # Create services
    services = ServiceFactory(session)

    # Ensure user exists in database (should exist if they made a payment, but be safe)
    await services.users.get_or_create(
        telegram_id=user.id,
        is_bot=user.is_bot,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        is_premium=user.is_premium or False,
        added_to_attachment_menu=user.added_to_attachment_menu or False,
        allows_users_to_create_topics=(user.allows_users_to_create_topics or
                                       False),
    )

    # Parse transaction ID from command
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(get_text("refund.instructions", lang))
        return

    transaction_id = args[1].strip()

    logger.info(
        "payment.refund_requested",
        user_id=user_id,
        transaction_id=transaction_id,
    )

    try:
        # Process refund (validates and updates database)
        payment_record = await services.payment.process_refund(
            user_id, transaction_id)

        # Call Telegram API to refund Stars
        success = await message.bot.refund_star_payment(
            user_id=user_id,
            telegram_payment_charge_id=transaction_id,
        )

        if not success:
            # Rollback database changes if Telegram API call failed
            await session.rollback()
            logger.error(
                "payment.refund_telegram_api_failed",
                user_id=user_id,
                transaction_id=transaction_id,
                msg="Telegram refund API call failed, rolled back DB changes",
            )
            await message.answer(get_text("refund.telegram_api_failed", lang))
            return

        # Get updated balance
        new_balance = await services.balance.get_balance(user_id)

        # Send confirmation
        await message.answer(
            get_text("refund.success",
                     lang,
                     stars_amount=payment_record.stars_amount,
                     usd_amount=payment_record.credited_usd_amount,
                     new_balance=new_balance))

        logger.info(
            "payment.refund_success",
            user_id=user_id,
            payment_id=payment_record.id,
            stars_refunded=payment_record.stars_amount,
            usd_deducted=float(payment_record.credited_usd_amount),
            new_balance=float(new_balance),
            msg="Refund processed successfully",
        )

        # Separate event for dashboard tracking
        logger.info(
            "stars.refund_processed",
            user_id=user_id,
            stars_amount=payment_record.stars_amount,
        )

    except ValueError as e:
        # Validation errors (refund not allowed)
        logger.info(
            "payment.refund_validation_error",
            user_id=user_id,
            transaction_id=transaction_id,
            error=str(e),
        )
        await message.answer(get_text("refund.failed", lang, error=str(e)))

    except Exception as e:
        logger.error(
            "payment.refund_error",
            user_id=user_id,
            transaction_id=transaction_id,
            error=str(e),
            exc_info=True,
            msg="Unexpected error during refund",
        )
        await message.answer(get_text("refund.processing_error", lang))


@router.message(Command("balance"))
async def cmd_balance(message: Message, session: AsyncSession):
    """Handler for /balance command - show current balance and history.

    Displays:
    - Current balance
    - Recent 5 balance operations with type and amount
    """
    if not message.from_user:
        await message.answer(get_text("common.unable_to_identify_user", "en"))
        return

    user = message.from_user
    user_id = user.id
    lang = get_lang(user.language_code)

    # Ensure user exists in database (auto-create if first interaction)
    services = ServiceFactory(session)
    await services.users.get_or_create(
        telegram_id=user.id,
        is_bot=user.is_bot,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        is_premium=user.is_premium or False,
        added_to_attachment_menu=user.added_to_attachment_menu or False,
        allows_users_to_create_topics=(user.allows_users_to_create_topics or
                                       False),
    )

    logger.info(
        "payment.balance_command",
        user_id=user_id,
    )

    try:
        # Get balance
        balance = await services.balance.get_balance(user_id)

        # Get recent history
        operations = await services.balance.get_balance_history(user_id,
                                                                limit=5)

        # Format history
        history_lines = []
        for op in operations:
            date = op.created_at.strftime("%Y-%m-%d %H:%M")
            amount_str = (f"+${op.amount}"
                          if op.amount > 0 else f"-${abs(op.amount)}")
            type_emoji = {
                "payment": "💳",
                "usage": "🔋",
                "refund": "↩️",
                "admin_topup": "👑",
            }.get(op.operation_type, "•")

            history_lines.append(
                f"{type_emoji} {date}: {amount_str} ({op.operation_type})")

        history_text = ("\n".join(history_lines) if history_lines else get_text(
            "balance.no_history", lang))

        # Send response
        response_text = get_text("balance.info",
                                 lang,
                                 balance=balance,
                                 history=history_text)
        await message.answer(response_text)

        logger.info(
            "payment.balance_checked",
            user_id=user_id,
            balance=float(balance),
            operations_count=len(operations),
        )

        log_bot_response(
            "bot.balance_response",
            chat_id=message.chat.id,
            user_id=user_id,
            message_length=len(response_text),
            balance=float(balance),
        )

    except Exception as e:
        logger.error(
            "payment.balance_check_error",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        await message.answer(get_text("balance.check_error", lang))


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, session: AsyncSession):
    """Handler for /paysupport command - payment support contact.

    Required by Telegram for bots accepting payments.
    """
    user_id = message.from_user.id
    lang = get_lang(
        message.from_user.language_code if message.from_user else None)

    logger.info(
        "payment.paysupport_requested",
        user_id=user_id,
    )

    response_text = get_text("paysupport.info", lang)
    await message.answer(response_text)

    log_bot_response(
        "bot.paysupport_response",
        chat_id=message.chat.id,
        user_id=user_id,
        message_length=len(response_text),
    )
