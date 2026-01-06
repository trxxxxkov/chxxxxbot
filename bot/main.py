"""Bot entry point"""

import asyncio
from pathlib import Path

from telegram.loader import create_bot, create_dispatcher
from utils.logging import setup_logging, get_logger


def read_secret(secret_name: str) -> str:
    """Read secret from Docker secrets

    Args:
        secret_name: Name of the secret file

    Returns:
        Secret content (stripped)

    Raises:
        FileNotFoundError: If secret file doesn't exist
    """
    secret_path = Path(f"/run/secrets/{secret_name}")
    return secret_path.read_text().strip()


async def main() -> None:
    """Main bot function"""
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
        dp = create_dispatcher()

        # Start polling
        logger.info("starting_polling")
        await dp.start_polling(bot)

    except FileNotFoundError as e:
        logger.error("secret_not_found", error=str(e))
        raise
    except Exception as e:
        logger.error("startup_error", error=str(e), exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
