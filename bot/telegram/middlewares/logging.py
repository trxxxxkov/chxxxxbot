"""Logging middleware for Telegram updates"""

import time
from typing import Callable, Dict, Any, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Update
import structlog

from utils.logging import get_logger

logger = get_logger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Middleware to log incoming updates with context"""

    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        """Process update with logging

        Args:
            handler: Next handler in chain
            event: Telegram update
            data: Handler data

        Returns:
            Handler result
        """
        # Extract context
        update_id = event.update_id
        user_id = None
        message_id = None

        if event.message:
            message_id = event.message.message_id
            if event.message.from_user:
                user_id = event.message.from_user.id
        elif event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id

        # Bind context to logger
        log = logger.bind(
            update_id=update_id,
            user_id=user_id,
            message_id=message_id,
        )

        # Log incoming update
        log.info(
            "incoming_update",
            update_type=event.event_type if hasattr(event, 'event_type') else "unknown"
        )

        # Measure execution time
        start_time = time.time()

        try:
            result = await handler(event, data)
            execution_time = time.time() - start_time

            log.info(
                "update_processed",
                execution_time_ms=round(execution_time * 1000, 2)
            )

            return result

        except Exception as e:
            execution_time = time.time() - start_time

            log.error(
                "update_error",
                error=str(e),
                error_type=type(e).__name__,
                execution_time_ms=round(execution_time * 1000, 2),
                exc_info=True
            )
            raise
