"""Database middleware for session management.

This module provides middleware that manages database sessions for each
Telegram update. It creates a new AsyncSession, injects it into handler
data, handles automatic commit/rollback, and ensures proper cleanup.

NO __init__.py - use direct import:
    from telegram.middlewares.database_middleware import DatabaseMiddleware
"""

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Update
from db.engine import get_session_factory
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """Middleware that manages database sessions for handlers.

    This middleware creates a new AsyncSession for each update,
    injects it into handler data['session'], automatically commits
    on success, rolls back on errors, and ensures proper cleanup.

    Usage in handler:
        async def my_handler(message: Message, session: AsyncSession):
            user_repo = UserRepository(session)
            user = await user_repo.get_by_telegram_id(message.from_user.id)
            # No need to commit - middleware handles it
    """

    async def __call__(self, handler: Callable[[Update, Dict[str, Any]],
                                               Awaitable[Any]], event: Update,
                       data: Dict[str, Any]) -> Any:
        """Processes update with database session management.

        Creates AsyncSession, injects into data['session'], calls handler,
        commits on success, rolls back on error, and ensures cleanup.

        Args:
            handler: Next handler in the middleware/handler chain.
            event: Incoming Telegram update to process.
            data: Additional data passed between handlers (session injected
                here).

        Returns:
            Result from the handler chain.

        Raises:
            Exception: Re-raises any exception from handlers after rollback.
        """
        session_factory = get_session_factory()

        async with session_factory() as session:
            # Inject session into handler data
            data['session'] = session

            try:
                result = await handler(event, data)

                # Auto-commit on success
                await session.commit()
                logger.debug("database_session_committed",
                             update_id=event.update_id)

                return result

            except Exception as e:
                # Auto-rollback on error
                await session.rollback()
                logger.error(
                    "database_session_rollback",
                    error=str(e),
                    error_type=type(e).__name__,
                    update_id=event.update_id,
                )
                raise
