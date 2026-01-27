"""Middleware for checking user balance before processing paid requests.

This middleware blocks requests to paid features (Claude API, tools) if user's
balance is insufficient (balance <= 0). All payment-related commands remain free.

Phase 3.2: Uses Redis cache for fast balance checks.
"""

from decimal import Decimal
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery
from aiogram.types import Message
from aiogram.types import Update
from cache.user_cache import cache_user
from cache.user_cache import get_balance_from_cached
from cache.user_cache import get_cached_user
from config import MINIMUM_BALANCE_FOR_REQUEST
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.user_repository import UserRepository
from services.balance_service import BalanceService
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class BalanceMiddleware(BaseMiddleware):
    """Middleware to check user balance before processing paid requests.

    Blocks requests to paid features (Claude API, tools) if balance <= 0.
    Allows all free commands (start, help, pay, balance, refund, etc.).

    Free commands (no balance check):
    - /start, /help
    - /pay, /balance, /refund, /paysupport
    - /topup, /set_margin (admin commands)
    - /model (model selection is free)
    """

    # Commands that don't require balance check (free)
    FREE_COMMANDS = {
        "/start",
        "/help",
        "/pay",
        "/balance",
        "/refund",
        "/paysupport",
        "/topup",
        "/set_margin",
        "/model",
    }

    async def __call__(  # pylint: disable=too-many-return-statements
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        """Check balance before processing event.

        Args:
            handler: Next handler in chain.
            event: Update event.
            data: Handler data (contains db_session from DatabaseMiddleware).

        Returns:
            Handler result or None if blocked.
        """
        # Only check for messages and callbacks
        message = None
        if isinstance(event, Message):
            message = event
            # Skip payment-related messages (they are part of balance top-up flow)
            if message.successful_payment:
                logger.debug(
                    "balance_middleware.payment_message_skip",
                    user_id=message.from_user.id if message.from_user else None,
                    msg="Skipping balance check for successful_payment message",
                )
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            message = event.message

        if not message:
            # Not a message or callback - allow (e.g., PreCheckoutQuery)
            return await handler(event, data)

        # Skip if no user or user is a bot (system messages, bot messages)
        if not message.from_user or message.from_user.is_bot:
            logger.debug(
                "balance_middleware.system_message",
                user_id=message.from_user.id if message.from_user else None,
                msg="Skipping balance check for system/bot message",
            )
            return await handler(event, data)

        # Extract message text/caption
        text = message.text or message.caption or ""
        command = text.split()[0] if text else ""

        # Check if this is a free command
        if command in self.FREE_COMMANDS:
            # Free command - skip balance check
            logger.debug(
                "balance_middleware.free_command",
                user_id=message.from_user.id,
                command=command,
            )
            return await handler(event, data)

        # All other messages and callbacks require balance check (paid requests)
        # This includes:
        # - Regular messages without "/" prefix
        # - Messages starting with "/" but NOT in FREE_COMMANDS
        #   (user may write "/привет расскажи" as a message)
        # - Callback queries

        # Paid request - check balance
        user_id = message.from_user.id
        balance_check_start = time.perf_counter()

        # Phase 3.2: Try cache first for fast balance check
        cached_user = await get_cached_user(user_id)
        if cached_user:
            # Cache hit - check balance from cache
            cached_balance = get_balance_from_cached(cached_user)
            can_request = cached_balance > Decimal(
                str(MINIMUM_BALANCE_FOR_REQUEST))

            balance_check_ms = (time.perf_counter() -
                                balance_check_start) * 1000

            if can_request:
                # Pass cached user data to handler for potential reuse
                data["cached_user"] = cached_user
                logger.debug(
                    "balance_middleware.cache_hit_allowed",
                    user_id=user_id,
                    balance=str(cached_balance),
                    balance_check_ms=round(balance_check_ms, 2),
                    source="cache",
                )
                return await handler(event, data)
            else:
                # Cached balance insufficient - block immediately
                await message.answer(
                    f"❌ <b>Insufficient balance</b>\n\n"
                    f"Current balance: <b>${cached_balance}</b>\n\n"
                    f"To use paid features, please top up your balance.\n"
                    f"Use /pay to purchase balance with Telegram Stars.")

                logger.info(
                    "balance_middleware.cache_hit_blocked",
                    user_id=user_id,
                    balance=float(cached_balance),
                    balance_check_ms=round(balance_check_ms, 2),
                    source="cache",
                    msg="Request blocked: insufficient balance (from cache)",
                )
                return None

        # Cache miss - fall back to database
        session = data.get("session")

        if not session:
            logger.error(
                "balance_middleware.no_session",
                user_id=user_id,
                msg="DatabaseMiddleware not configured",
            )
            # Fail-open: allow request if session not available
            return await handler(event, data)

        # Create services
        user_repo = UserRepository(session)
        balance_op_repo = BalanceOperationRepository(session)
        balance_service = BalanceService(session, user_repo, balance_op_repo)

        # Check balance from database
        try:
            can_request, user_exists = await balance_service.can_make_request(
                user_id)

            if not user_exists:
                # Auto-register user (like /start does)
                from_user = message.from_user
                user, was_created = await user_repo.get_or_create(
                    telegram_id=from_user.id,
                    is_bot=from_user.is_bot,
                    first_name=from_user.first_name,
                    last_name=from_user.last_name,
                    username=from_user.username,
                    language_code=from_user.language_code,
                    is_premium=from_user.is_premium or False,
                    added_to_attachment_menu=from_user.added_to_attachment_menu
                    or False,
                )

                logger.info(
                    "balance_middleware.auto_registered",
                    user_id=user_id,
                    username=from_user.username,
                    msg="User auto-registered on first message",
                )

                # Cache the new user
                await cache_user(
                    user_id=user.id,
                    balance=user.balance,
                    model_id=user.model_id,
                    first_name=user.first_name,
                    username=user.username,
                )

                # Re-check balance after registration
                can_request, user_exists = \
                    await balance_service.can_make_request(user_id)
            else:
                # User exists, cache their data for future requests
                user = await user_repo.get_by_id(user_id)
                if user:
                    await cache_user(
                        user_id=user.id,
                        balance=user.balance,
                        model_id=user.model_id,
                        first_name=user.first_name,
                        username=user.username,
                    )

            balance_check_ms = (time.perf_counter() -
                                balance_check_start) * 1000

            if not can_request:
                # Block request - insufficient balance
                balance = await balance_service.get_balance(user_id)

                await message.answer(
                    f"❌ <b>Insufficient balance</b>\n\n"
                    f"Current balance: <b>${balance}</b>\n\n"
                    f"To use paid features, please top up your balance.\n"
                    f"Use /pay to purchase balance with Telegram Stars.")

                logger.info(
                    "balance_middleware.request_blocked",
                    user_id=user_id,
                    balance=float(balance),
                    balance_check_ms=round(balance_check_ms, 2),
                    source="database",
                    msg="Request blocked: insufficient balance",
                )

                # Don't call next handler - request blocked
                return None

        except Exception as e:
            balance_check_ms = (time.perf_counter() -
                                balance_check_start) * 1000
            logger.error(
                "balance_middleware.check_error",
                user_id=user_id,
                error=str(e),
                balance_check_ms=round(balance_check_ms, 2),
                exc_info=True,
                msg="Error checking balance, allowing request (fail-open)",
            )
            # Fail-open: allow request if balance check failed

        # Balance check passed - proceed to next handler
        balance_check_ms = (time.perf_counter() - balance_check_start) * 1000
        logger.debug(
            "balance_middleware.request_allowed",
            user_id=user_id,
            balance_check_ms=round(balance_check_ms, 2),
            source="database",
        )
        return await handler(event, data)
