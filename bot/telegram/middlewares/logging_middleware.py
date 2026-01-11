"""Logging middleware for Telegram updates.

This module provides middleware that logs all incoming Telegram updates with
structured context information. It extracts user_id, message_id, and update_id
from updates, binds them to the logger context, and measures execution time
for each update handler.

Phase 3: Adds request_id (correlation ID) for tracing all logs from one request.
"""

import time
import uuid
from typing import Any, Awaitable, Callable, Dict

import structlog
from aiogram import BaseMiddleware
from aiogram.types import Update
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Middleware that logs all incoming Telegram updates with context.

    This middleware intercepts every update before it reaches handlers,
    extracts relevant context (user_id, message_id, update_id), logs the
    incoming update, measures execution time, and logs the result or any
    errors that occur during processing.
    """

    async def __call__(self, handler: Callable[[Update, Dict[str, Any]],
                                               Awaitable[Any]], event: Update,
                       data: Dict[str, Any]) -> Any:
        """Processes update with logging and execution time measurement.

        Extracts context from the update, binds it to the logger, logs the
        incoming update, calls the next handler in the chain, and logs the
        result with execution time. If an error occurs, logs the error with
        full traceback.

        Args:
            handler: Next handler in the middleware/handler chain.
            event: Incoming Telegram update to process.
            data: Additional data passed between handlers.

        Returns:
            Result from the handler chain.

        Raises:
            Exception: Re-raises any exception from handlers after logging.
        """
        # Generate unique request_id for tracing (Phase 3)
        request_id = str(uuid.uuid4())[:8]

        # Extract context
        update_id = event.update_id
        user_id = None
        message_id = None
        chat_id = None

        if event.message:
            message_id = event.message.message_id
            chat_id = event.message.chat.id
            if event.message.from_user:
                user_id = event.message.from_user.id
        elif event.callback_query and event.callback_query.from_user:
            user_id = event.callback_query.from_user.id

        # Bind context to structlog contextvars (propagates to all loggers)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            update_id=update_id,
            user_id=user_id,
            message_id=message_id,
            chat_id=chat_id,
        )

        # Bind context to local logger as well
        log = logger.bind(
            request_id=request_id,
            update_id=update_id,
            user_id=user_id,
            message_id=message_id,
            chat_id=chat_id,
        )

        # Log incoming update
        log.info("incoming_update",
                 update_type=event.event_type
                 if hasattr(event, 'event_type') else "unknown")

        # Measure execution time
        start_time = time.time()

        try:
            result = await handler(event, data)
            execution_time = time.time() - start_time

            log.info("update_processed",
                     execution_time_ms=round(execution_time * 1000, 2))

            return result

        except Exception as e:
            execution_time = time.time() - start_time

            log.error("update_error",
                      error=str(e),
                      error_type=type(e).__name__,
                      execution_time_ms=round(execution_time * 1000, 2),
                      exc_info=True)
            raise
