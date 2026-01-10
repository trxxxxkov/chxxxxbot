"""Middleware for checking user balance before processing paid requests.

This middleware blocks requests to paid features (Claude API, tools) if user's
balance is insufficient (balance <= 0). All payment-related commands remain free.
"""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery
from aiogram.types import Message
from aiogram.types import Update
from db.repositories.balance_operation_repository import \
    BalanceOperationRepository
from db.repositories.user_repository import UserRepository
from services.balance_service import BalanceService
import structlog

logger = structlog.get_logger(__name__)


class BalanceMiddleware(BaseMiddleware):
    """Middleware to check user balance before processing paid requests.

    Blocks requests to paid features (Claude API, tools) if balance <= 0.
    Allows all free commands (start, help, buy, balance, refund, etc.).

    Free commands (no balance check):
    - /start, /help
    - /buy, /balance, /refund, /paysupport
    - /topup, /set_margin (admin commands)
    - /model (model selection is free)
    """

    # Commands that don't require balance check (free)
    FREE_COMMANDS = {
        "/start",
        "/help",
        "/buy",
        "/balance",
        "/refund",
        "/paysupport",
        "/topup",
        "/set_margin",
        "/model",
    }

    async def __call__(
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
        elif isinstance(event, CallbackQuery):
            message = event.message

        if not message:
            # Not a message or callback - allow
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

        # Check if this is a paid request (any non-command message or callback)
        is_paid_request = ((isinstance(event, Message) and
                            not text.startswith("/")) or
                           isinstance(event, CallbackQuery))

        if not is_paid_request:
            # Not a paid request (e.g., unknown command) - allow
            logger.debug(
                "balance_middleware.not_paid_request",
                user_id=message.from_user.id,
                text=text[:50],
            )
            return await handler(event, data)

        # Paid request - check balance
        user_id = message.from_user.id
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

        # Check balance
        try:
            can_request = await balance_service.can_make_request(user_id)

            if not can_request:
                # Block request - insufficient balance
                balance = await balance_service.get_balance(user_id)

                await message.answer(
                    f"❌ <b>Insufficient balance</b>\n\n"
                    f"Current balance: <b>${balance}</b>\n\n"
                    f"To use paid features, please top up your balance.\n"
                    f"Use /buy to purchase balance with Telegram Stars.")

                logger.warning(
                    "balance_middleware.request_blocked",
                    user_id=user_id,
                    balance=float(balance),
                    msg="Request blocked: insufficient balance",
                )

                # Don't call next handler - request blocked
                return None

        except Exception as e:
            logger.error(
                "balance_middleware.check_error",
                user_id=user_id,
                error=str(e),
                exc_info=True,
                msg="Error checking balance, allowing request (fail-open)",
            )
            # Fail-open: allow request if balance check failed

        # Balance check passed - proceed to next handler
        logger.debug(
            "balance_middleware.request_allowed",
            user_id=user_id,
        )
        return await handler(event, data)
