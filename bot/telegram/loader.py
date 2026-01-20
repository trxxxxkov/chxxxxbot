"""Bot and Dispatcher initialization.

This module provides factory functions for creating and configuring
Bot and Dispatcher instances. It registers all handlers, middlewares,
and routers in the correct order.
"""

from aiogram import Bot
from aiogram import Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from telegram.handlers import admin  # Phase 2.1: Admin commands
from telegram.handlers import claude
from telegram.handlers import \
    edited_message  # Telegram features: edit tracking
from telegram.handlers import files
from telegram.handlers import media_handlers
from telegram.handlers import model
from telegram.handlers import payment  # Phase 2.1: Payment handlers
from telegram.handlers import personality
from telegram.handlers import start
from telegram.middlewares.balance_middleware import \
    BalanceMiddleware  # Phase 2.1: Balance check
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

    # Phase 2.1: Balance middleware (checks balance before paid requests)
    # Must be after DatabaseMiddleware (needs db_session in data)
    dispatcher.message.middleware(BalanceMiddleware())
    dispatcher.callback_query.middleware(BalanceMiddleware())

    # Register routers (order matters - first match wins)
    dispatcher.include_router(start.router)
    dispatcher.include_router(model.router)
    dispatcher.include_router(personality.router)
    dispatcher.include_router(payment.router)  # Phase 2.1: Payment commands
    dispatcher.include_router(admin.router)  # Phase 2.1: Admin commands
    dispatcher.include_router(files.router)  # Phase 1.5: Photo/document uploads
    dispatcher.include_router(
        media_handlers.router)  # Phase 1.6: Voice/audio/video
    dispatcher.include_router(edited_message.router)  # Edit tracking
    dispatcher.include_router(claude.router)  # Catch-all should be last

    logger.info(
        "dispatcher_created",
        routers=[
            "start",
            "model",
            "personality",
            "payment",
            "admin",
            "files",
            "media",
            "edited_message",
            "claude",
        ],
    )
    return dispatcher
