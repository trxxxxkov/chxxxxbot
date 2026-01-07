"""Bot and Dispatcher initialization.

This module provides factory functions for creating and configuring
Bot and Dispatcher instances. It registers all handlers, middlewares,
and routers in the correct order.
"""

from aiogram import Bot
from aiogram import Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from telegram.handlers import echo
from telegram.handlers import start
from telegram.middlewares.database_middleware import DatabaseMiddleware
from telegram.middlewares.logging_middleware import LoggingMiddleware
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def create_bot(token: str) -> Bot:
    """Creates and configures Bot instance.

    Args:
        token: Telegram Bot API token from BotFather.

    Returns:
        Configured Bot instance with default properties.
    """
    bot = Bot(token=token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    logger.info("bot_created")
    return bot


def create_dispatcher() -> Dispatcher:
    """Creates and configures Dispatcher.

    Registers all middlewares and routers in the correct order.
    Middleware order: first registered is executed first.
    Router order: first registered handler that matches wins.

    Returns:
        Configured Dispatcher with all routers and middlewares.
    """
    dispatcher = Dispatcher()

    # Register middleware (order matters - first registered, first executed)
    dispatcher.update.middleware(LoggingMiddleware())
    dispatcher.update.middleware(DatabaseMiddleware())

    # Register routers (order matters - first match wins)
    dispatcher.include_router(start.router)
    dispatcher.include_router(echo.router)  # Catch-all should be last

    logger.info("dispatcher_created", routers=["start", "echo"])
    return dispatcher
