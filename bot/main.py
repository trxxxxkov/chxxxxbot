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
from db.engine import get_pool_stats
from telegram.handlers.claude import init_claude_provider
from telegram.handlers.claude import init_message_queue_manager
from telegram.handlers.claude import get_queue_manager
from telegram.loader import create_bot
from telegram.loader import create_dispatcher
from utils.structured_logging import get_logger
from utils.structured_logging import setup_logging
from utils.metrics import start_metrics_server
from utils.metrics import set_db_pool_stats
from utils.metrics import set_queue_stats


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


def load_privileged_users() -> set[int]:
    """Load privileged user IDs from secrets file (Phase 2.1).

    Reads /run/secrets/privileged_users and parses user IDs.
    Format: one ID per line, or space/comma separated, or mixed.
    Lines starting with # are ignored (comments).

    Returns:
        Set of Telegram user IDs with admin privileges.
    """
    logger = get_logger(__name__)
    privileged_file = Path("/run/secrets/privileged_users")

    if not privileged_file.exists():
        logger.warning(
            "privileged_users_file_not_found",
            path=str(privileged_file),
            msg="No privileged users configured - admin commands disabled",
        )
        return set()

    try:
        content = privileged_file.read_text(encoding="utf-8").strip()

        # Parse comma/space/newline separated IDs, skip comments
        import re

        lines = content.split("\n")
        privileged_ids = set()

        for line in lines:
            # Strip comments
            line = line.split("#")[0].strip()
            if not line:
                continue

            # Split by comma or space
            ids_str = re.split(r'[,\s]+', line)
            for id_str in ids_str:
                id_str = id_str.strip()
                if id_str.isdigit():
                    privileged_ids.add(int(id_str))

        logger.info(
            "privileged_users_loaded",
            count=len(privileged_ids),
            user_ids=sorted(list(privileged_ids)),
        )
        return privileged_ids

    except Exception as e:
        logger.error(
            "privileged_users_load_error",
            path=str(privileged_file),
            error=str(e),
            exc_info=True,
        )
        return set()


async def collect_metrics_task(logger) -> None:
    """Background task to collect metrics every 10 seconds.

    Collects:
        - Database connection pool statistics
        - Message queue statistics
    """
    while True:
        try:
            await asyncio.sleep(10)

            # Collect database pool stats
            pool_stats = get_pool_stats()
            if pool_stats:
                set_db_pool_stats(
                    active=pool_stats.get("active", 0),
                    idle=pool_stats.get("idle", 0),
                    overflow=pool_stats.get("overflow", 0),
                )

            # Collect queue stats
            queue_manager = get_queue_manager()
            if queue_manager:
                queue_stats = queue_manager.get_stats()
                set_queue_stats(
                    total=queue_stats.get("total_threads", 0),
                    processing=queue_stats.get("processing_threads", 0),
                    waiting=queue_stats.get("waiting_threads", 0),
                )

        except asyncio.CancelledError:
            logger.info("metrics_collection_task_cancelled")
            break
        except Exception as e:
            logger.error("metrics_collection_error", error=str(e), exc_info=True)


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

        # Load privileged users (Phase 2.1: admin commands)
        import config as bot_config

        bot_config.PRIVILEGED_USERS = load_privileged_users()
        logger.info(
            "privileged_users_configured",
            count=len(bot_config.PRIVILEGED_USERS),
        )

        # Create bot and dispatcher
        bot = create_bot(token=bot_token)
        dispatcher = create_dispatcher()

        # Start metrics server (Phase 3.1: Prometheus integration)
        await start_metrics_server(host='0.0.0.0', port=8080)
        logger.info("metrics_server_started", port=8080)

        # Start background metrics collection task
        metrics_task = asyncio.create_task(collect_metrics_task(logger))
        logger.info("metrics_collection_task_started")

        # Start polling
        logger.info("starting_polling")
        try:
            await dispatcher.start_polling(bot)
        finally:
            # Cancel metrics collection on shutdown
            metrics_task.cancel()
            try:
                await metrics_task
            except asyncio.CancelledError:
                pass

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
