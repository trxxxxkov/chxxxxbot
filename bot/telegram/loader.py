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
from telegram.handlers import \
    edited_message  # Telegram features: edit tracking
from telegram.handlers import model
from telegram.handlers import payment  # Phase 2.1: Payment handlers
from telegram.handlers import personality
from telegram.handlers import start
from telegram.handlers import stop_generation  # Phase 2.5: Stop generation
from telegram.middlewares.balance_middleware import \
    BalanceMiddleware  # Phase 2.1: Balance check
from telegram.middlewares.command_middleware import \
    CallbackLoggingMiddleware  # Callback button logging
from telegram.middlewares.command_middleware import \
    CommandMiddleware  # Command logging + topic registration
from telegram.middlewares.database_middleware import DatabaseMiddleware
from telegram.middlewares.logging_middleware import LoggingMiddleware
import telegram.pipeline.handler as unified_handler
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
    logger.debug("bot_created")
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

    # Command middleware: logs all commands and registers topics
    # Must be after DatabaseMiddleware (needs session in data)
    dispatcher.message.middleware(CommandMiddleware())

    # Phase 2.1: Balance middleware (checks balance before paid requests)
    # Must be after DatabaseMiddleware (needs db_session in data)
    dispatcher.message.middleware(BalanceMiddleware())
    dispatcher.callback_query.middleware(BalanceMiddleware())

    # Callback logging middleware: logs button presses
    dispatcher.callback_query.middleware(CallbackLoggingMiddleware())

    # Register routers (order matters - first match wins)
    dispatcher.include_router(start.router)
    dispatcher.include_router(model.router)
    dispatcher.include_router(personality.router)
    dispatcher.include_router(payment.router)  # Phase 2.1: Payment commands
    dispatcher.include_router(admin.router)  # Phase 2.1: Admin commands
    dispatcher.include_router(
        stop_generation.router)  # Phase 2.5: Stop generation

    # Unified pipeline: Single handler for all message types
    # Handles: text, photo, document, voice, audio, video, video_note
    dispatcher.include_router(edited_message.router)  # Edit tracking
    dispatcher.include_router(unified_handler.router)  # Unified handler

    logger.debug(
        "dispatcher_created",
        routers=[
            "start",
            "model",
            "personality",
            "payment",
            "admin",
            "stop_generation",
            "edited_message",
            "unified_pipeline",
        ],
    )

    return dispatcher
