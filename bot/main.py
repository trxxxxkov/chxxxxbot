"""Bot entry point.

This module serves as the application entry point. It reads secrets from
Docker secrets, initializes logging, creates bot and dispatcher instances,
and starts polling for updates from Telegram.
"""

import asyncio
from pathlib import Path

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

    Initializes logging, reads secrets, creates bot and dispatcher,
    and starts polling for Telegram updates.

    Raises:
        FileNotFoundError: If required secret file is missing.
        Exception: Any other startup errors.
    """
    # Setup logging
    setup_logging(level="INFO")
    logger = get_logger(__name__)

    logger.info("bot_starting")

    try:
        # Read secrets
        bot_token = read_secret("telegram_bot_token")
        logger.info("secrets_loaded")

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


if __name__ == "__main__":
    asyncio.run(main())
