"""Bot and Dispatcher initialization"""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from telegram.handlers import start, echo
from telegram.middlewares.logging import LoggingMiddleware
from utils.logging import get_logger

logger = get_logger(__name__)


def create_bot(token: str) -> Bot:
    """Create and configure Bot instance

    Args:
        token: Telegram Bot API token

    Returns:
        Configured Bot instance
    """
    bot = Bot(
        token=token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML
        )
    )
    logger.info("bot_created")
    return bot


def create_dispatcher() -> Dispatcher:
    """Create and configure Dispatcher

    Returns:
        Configured Dispatcher with routers and middlewares
    """
    dp = Dispatcher()

    # Register middleware (order matters - first registered, first executed)
    dp.update.middleware(LoggingMiddleware())

    # Register routers (order matters - first match wins)
    dp.include_router(start.router)
    dp.include_router(echo.router)  # Catch-all should be last

    logger.info("dispatcher_created", routers=["start", "echo"])
    return dp
