"""Bot entry point.

This module serves as the application entry point. It reads secrets from
Docker secrets, initializes logging and database, creates bot and dispatcher
instances, and starts polling for updates from Telegram.
"""

import asyncio
from pathlib import Path

from config import get_database_url
from db.engine import dispose_db
from db.engine import init_db
from telegram.handlers.claude import init_claude_provider
from telegram.handlers.claude import init_message_queue_manager
from telegram.loader import create_bot
from telegram.loader import create_dispatcher
from utils.structured_logging import get_logger
from utils.structured_logging import setup_logging


def read_secret(secret_name: str) -> str:
    """Reads secret from Docker secrets.

    Args:
        secret_name: Name of the secret file in /run/secrets/.

    Returns:
        Secret content with whitespace stripped.

    Raises:
        FileNotFoundError: If secret file doesn't exist.
    """
    secret_path = Path(f"/run/secrets/{secret_name}")
    return secret_path.read_text(encoding='utf-8').strip()


async def main() -> None:
    """Main bot function.

    Initializes logging, database, reads secrets, creates bot and dispatcher,
    and starts polling for Telegram updates. Ensures proper cleanup on shutdown.

    Raises:
        FileNotFoundError: If required secret file is missing.
        Exception: Any other startup errors.
    """
    # Setup logging
    setup_logging(level="INFO")
    logger = get_logger(__name__)

    logger.info("bot_starting")

    try:
        # Initialize database
        database_url = get_database_url()
        init_db(database_url, echo=False)
        logger.info("database_initialized")

        # Read secrets
        bot_token = read_secret("telegram_bot_token")
        anthropic_api_key = read_secret("anthropic_api_key")
        logger.info("secrets_loaded")

        # Initialize Claude provider
        init_claude_provider(anthropic_api_key)
        logger.info("claude_provider_initialized")

        # Initialize message queue manager (Phase 1.4.3: message batching)
        init_message_queue_manager()
        logger.info("message_queue_initialized")

        # Create bot and dispatcher
        bot = create_bot(token=bot_token)
        dispatcher = create_dispatcher()

        # Start polling
        logger.info("starting_polling")
        await dispatcher.start_polling(bot)

    except FileNotFoundError as error:
        logger.error("secret_not_found", error=str(error))
        raise
    except Exception as error:
        logger.error("startup_error", error=str(error), exc_info=True)
        raise
    finally:
        # Cleanup database connections
        await dispose_db()
        logger.info("bot_stopped")


if __name__ == "__main__":
    asyncio.run(main())
