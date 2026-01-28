"""Bot entry point.

This module serves as the application entry point. It reads secrets from
Docker secrets, initializes logging and database, creates bot and dispatcher
instances, and starts polling for updates from Telegram.
"""

import asyncio
from pathlib import Path

from cache.client import close_redis
from cache.client import init_redis
from config import get_database_url
from db.engine import dispose_db
from db.engine import get_pool_stats
from db.engine import get_session
from db.engine import init_db
from telegram.handlers.claude import init_claude_provider
from telegram.loader import create_bot
from telegram.loader import create_dispatcher
from telegram.pipeline.handler import get_queue
from utils.metrics import set_active_files
from utils.metrics import set_active_users
from utils.metrics import set_db_pool_stats
from utils.metrics import set_disk_usage
from utils.metrics import set_queue_stats
from utils.metrics import set_redis_stats
from utils.metrics import set_top_users
from utils.metrics import set_total_balance
from utils.metrics import set_total_threads
from utils.metrics import set_total_users
from utils.metrics import start_metrics_server
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
        # Expected if admin commands not needed
        logger.info(
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

        logger.debug(
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


def get_directory_size(path: str) -> int:
    """Get total size of directory in bytes.

    Args:
        path: Directory path to measure.

    Returns:
        Total size in bytes, or 0 if path doesn't exist.
    """
    import os
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    total += os.path.getsize(filepath)
                except (OSError, IOError):
                    pass
    except (OSError, IOError):
        pass
    return total


def _parse_memory(memory_str: str) -> int:
    """Parse Redis memory string to bytes.

    Args:
        memory_str: Memory string like "1.5M", "512K", "100B".

    Returns:
        Memory size in bytes.
    """
    import re
    match = re.match(r'([\d.]+)([KMGB])?', memory_str.upper())
    if not match:
        return 0

    value = float(match.group(1))
    unit = match.group(2) or 'B'

    multipliers = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3}
    return int(value * multipliers.get(unit, 1))


async def warm_user_cache(logger) -> int:
    """Warm user cache with recently active users.

    Loads users who were active in the last 24 hours and caches their
    balance and model_id. This ensures the first request from these
    users hits the cache instead of the database.

    Args:
        logger: Logger instance.

    Returns:
        Number of users cached.
    """
    from cache.user_cache import \
        cache_user  # pylint: disable=import-outside-toplevel
    from db.engine import \
        get_session  # pylint: disable=import-outside-toplevel
    from db.repositories.user_repository import \
        UserRepository  # pylint: disable=import-outside-toplevel

    try:
        async with get_session() as session:
            user_repo = UserRepository(session)

            # Get users active in last 24 hours
            active_users = await user_repo.get_active_users(hours=24)

            cached_count = 0
            for user in active_users:
                success = await cache_user(
                    user_id=user.id,
                    balance=user.balance,
                    model_id=user.model_id or "claude-sonnet-4-5-20250929",
                    first_name=user.first_name or "",
                    username=user.username,
                )
                if success:
                    cached_count += 1

            logger.debug(
                "cache_warming.completed",
                total_active=len(active_users),
                cached=cached_count,
            )
            return cached_count

    except Exception as e:  # pylint: disable=broad-exception-caught
        # Optimization failure - system continues without pre-warmed cache
        logger.info("cache_warming.failed", error=str(e))
        return 0


async def collect_metrics_task(logger) -> None:
    """Background task to collect metrics periodically.

    Collects every 10 seconds:
        - Database connection pool statistics
        - Message queue statistics
        - Redis cache statistics

    Collects every 60 seconds:
        - Active users count
        - Total balance
        - Total users
        - Top users by messages/tokens
    """
    iteration = 0

    while True:
        try:
            await asyncio.sleep(10)
            iteration += 1

            # Collect database pool stats (every 10s)
            pool_stats = get_pool_stats()
            if pool_stats:
                set_db_pool_stats(
                    active=pool_stats.get("active", 0),
                    idle=pool_stats.get("idle", 0),
                    overflow=pool_stats.get("overflow", 0),
                )

            # Collect queue stats (every 10s)
            pipeline_queue = get_queue()
            if pipeline_queue:
                queue_stats = pipeline_queue.get_stats()
                set_queue_stats(
                    total=queue_stats.get("total_threads", 0),
                    processing=queue_stats.get("processing_threads", 0),
                    waiting=queue_stats.get("waiting_threads", 0),
                )

            # Collect Redis stats (every 10s)
            try:
                from cache.client import \
                    redis_health_check  # pylint: disable=import-outside-toplevel
                redis_health = await redis_health_check()
                if redis_health.get("status") == "ok":
                    info = redis_health.get("info", {})
                    set_redis_stats(
                        connected_clients=info.get("connected_clients", 0),
                        used_memory=_parse_memory(
                            info.get("used_memory_human", "0B")),
                        uptime=info.get("uptime_seconds", 0),
                    )
            except Exception as redis_err:  # pylint: disable=broad-exception-caught
                logger.debug("metrics.redis_stats_error", error=str(redis_err))

            # Collect user metrics (every 60s = 6 iterations)
            if iteration % 6 == 0:
                try:
                    # Import here to avoid circular imports
                    from db.repositories.user_repository import \
                        UserRepository  # pylint: disable=import-outside-toplevel

                    async with get_session() as session:
                        user_repo = UserRepository(session)

                        # Active users (last hour)
                        active_count = await user_repo.get_active_users_count(
                            hours=1)
                        set_active_users(active_count)

                        # Total balance
                        total_balance = await user_repo.get_total_balance()
                        set_total_balance(float(total_balance))

                        # Total users
                        total_users = await user_repo.get_users_count()
                        set_total_users(total_users)

                        # Top users by messages
                        top_by_messages = await user_repo.get_top_users(
                            limit=10, by="messages")
                        users_data = [(str(u.id), u.username, u.message_count,
                                       u.total_tokens_used)
                                      for u in top_by_messages]
                        set_top_users(users_data, metric_type="messages")

                        # Top users by tokens
                        top_by_tokens = await user_repo.get_top_users(
                            limit=10, by="tokens")
                        users_data = [(str(u.id), u.username, u.message_count,
                                       u.total_tokens_used)
                                      for u in top_by_tokens]
                        set_top_users(users_data, metric_type="tokens")

                        # Active files in Files API
                        from db.repositories.user_file_repository import \
                            UserFileRepository  # pylint: disable=import-outside-toplevel
                        user_file_repo = UserFileRepository(session)
                        active_files = await user_file_repo.get_active_files_count(
                        )
                        set_active_files(active_files)

                        # Total threads
                        from db.repositories.thread_repository import \
                            ThreadRepository  # pylint: disable=import-outside-toplevel
                        thread_repo = ThreadRepository(session)
                        total_threads = await thread_repo.get_threads_count()
                        set_total_threads(total_threads)

                        # Disk usage by volume
                        volumes = {
                            'postgres': '/mnt/volumes/postgres',
                            'loki': '/mnt/volumes/loki',
                            'prometheus': '/mnt/volumes/prometheus',
                            'grafana': '/mnt/volumes/grafana',
                        }
                        total_disk = 0
                        for vol_name, vol_path in volumes.items():
                            vol_size = get_directory_size(vol_path)
                            set_disk_usage(vol_name, vol_size)
                            total_disk += vol_size
                        set_disk_usage('total', total_disk)

                        logger.debug("metrics.user_stats_collected",
                                     active_users=active_count,
                                     total_users=total_users,
                                     total_balance=float(total_balance),
                                     active_files=active_files,
                                     total_threads=total_threads,
                                     total_disk_bytes=total_disk)

                except Exception as user_err:  # pylint: disable=broad-exception-caught
                    logger.error("metrics.user_stats_error",
                                 error=str(user_err),
                                 exc_info=True)

        except asyncio.CancelledError:
            logger.debug("metrics_collection_task_cancelled")
            break
        except Exception as e:
            logger.error("metrics_collection_error",
                         error=str(e),
                         exc_info=True)


async def main() -> None:
    """Main bot function.

    Initializes logging, database, reads secrets, creates bot and dispatcher,
    and starts polling for Telegram updates. Ensures proper cleanup on shutdown.

    Raises:
        FileNotFoundError: If required secret file is missing.
        Exception: Any other startup errors.
    """
    # Setup logging
    setup_logging(level="DEBUG")
    logger = get_logger(__name__)

    logger.debug("bot_starting")

    try:
        # Initialize database
        database_url = get_database_url()
        init_db(database_url, echo=False)
        logger.debug("database_initialized")

        # Initialize Redis cache (Phase 3.2)
        try:
            await init_redis()
            logger.debug("redis_initialized")

            # Warm user cache with recently active users
            await warm_user_cache(logger)
        except Exception as redis_err:  # pylint: disable=broad-exception-caught
            logger.warning("redis_init_failed",
                           error=str(redis_err),
                           msg="Continuing without Redis cache")

        # Read secrets
        bot_token = read_secret("telegram_bot_token")
        anthropic_api_key = read_secret("anthropic_api_key")
        logger.debug("secrets_loaded")

        # Initialize Claude provider
        init_claude_provider(anthropic_api_key)
        logger.debug("claude_provider_initialized")

        # Load privileged users (Phase 2.1: admin commands)
        import config as bot_config

        bot_config.PRIVILEGED_USERS = load_privileged_users()
        logger.debug(
            "privileged_users_configured",
            count=len(bot_config.PRIVILEGED_USERS),
        )

        # Create bot and dispatcher
        bot = create_bot(token=bot_token)
        dispatcher = create_dispatcher()

        # Get bot info and store globally for logging
        bot_info = await bot.get_me()
        bot_config.BOT_ID = bot_info.id
        bot_config.BOT_USERNAME = bot_info.username
        logger.debug("bot_info_loaded",
                     bot_id=bot_info.id,
                     bot_username=bot_info.username)

        # Start metrics server (Phase 3.1: Prometheus integration)
        await start_metrics_server(host='0.0.0.0', port=8080)
        logger.debug("metrics_server_started", port=8080)

        # Start background metrics collection task
        metrics_task = asyncio.create_task(collect_metrics_task(logger))
        logger.debug("metrics_collection_task_started")

        # Start write-behind background task (Phase 3.3: Cache-first)
        from cache.write_behind import \
            write_behind_task  # pylint: disable=import-outside-toplevel
        write_behind_handle = asyncio.create_task(write_behind_task(logger))
        logger.debug("write_behind_task_started")

        # Start polling
        logger.debug("starting_polling")
        try:
            await dispatcher.start_polling(bot)
        finally:
            # Cancel background tasks on shutdown
            metrics_task.cancel()
            write_behind_handle.cancel()

            # Wait for graceful shutdown (write-behind flushes pending writes)
            try:
                await metrics_task
            except asyncio.CancelledError:
                pass

            try:
                await write_behind_handle
            except asyncio.CancelledError:
                pass

    except FileNotFoundError as error:
        logger.error("secret_not_found", error=str(error))
        raise
    except Exception as error:
        logger.error("startup_error", error=str(error), exc_info=True)
        raise
    finally:
        # Cleanup Redis connections
        await close_redis()
        logger.debug("redis_closed")

        # Cleanup database connections
        await dispose_db()
        logger.debug("bot_stopped")


if __name__ == "__main__":
    asyncio.run(main())
