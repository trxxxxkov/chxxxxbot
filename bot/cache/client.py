"""Redis client singleton for caching.

This module provides async Redis client with connection pooling and automatic
reconnection. Implements singleton pattern for efficient connection reuse.

Key features:
- Async operations via redis-py
- Connection pooling with hiredis speedups
- Graceful degradation on connection failures
- Automatic reconnection
- Circuit breaker pattern (stops retries when Redis is down)

NO __init__.py - use direct import:
    from cache.client import get_redis, close_redis
"""

import os
import time
from typing import Optional

# isort: off
import redis.asyncio as redis  # type: ignore[import-untyped]
from redis.asyncio.connection import ConnectionPool  # type: ignore[import-untyped]
# isort: on
from utils.metrics import set_redis_circuit_state
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Global client instance (singleton)
_redis_client: Optional[redis.Redis] = None
_connection_pool: Optional[ConnectionPool] = None

# Circuit breaker state
# After CIRCUIT_FAILURE_THRESHOLD consecutive failures, circuit opens
# Circuit stays open for CIRCUIT_RESET_TIMEOUT seconds before trying again
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_RESET_TIMEOUT = 30.0  # seconds

_circuit_failure_count: int = 0
_circuit_open_until: float = 0.0  # timestamp when circuit should close


def _read_redis_password() -> Optional[str]:
    """Read Redis password from secrets file.

    Returns:
        Password string or None if not configured.
    """
    secret_path = "/run/secrets/redis_password"
    try:
        with open(secret_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.debug("redis.no_password_file", path=secret_path)
        return None
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("redis.password_read_error", error=str(e))
        return None


def get_redis_url() -> str:
    """Get Redis connection URL from environment.

    Returns:
        Redis URL string (e.g., "redis://:password@redis:6379/0").
    """
    host = os.environ.get("REDIS_HOST", "redis")
    port = os.environ.get("REDIS_PORT", "6379")
    db = os.environ.get("REDIS_DB", "0")
    password = _read_redis_password()

    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


def _sanitize_url(url: str) -> str:
    """Remove password from URL for logging.

    Args:
        url: Redis URL that may contain password.

    Returns:
        URL with password masked.
    """
    # redis://:password@host:port/db -> redis://:***@host:port/db
    if "@" in url and ":" in url.split("@")[0]:
        prefix = url.split("@")[0]
        suffix = url.split("@")[1]
        if prefix.count(":") >= 2:  # Has password
            return f"redis://:***@{suffix}"
    return url


async def init_redis() -> redis.Redis:
    """Initialize Redis client with connection pool.

    Creates a singleton Redis client with connection pooling.
    Call this once at application startup.

    Returns:
        Redis client instance.

    Raises:
        redis.ConnectionError: If initial connection fails.
    """
    global _redis_client, _connection_pool  # pylint: disable=global-statement

    if _redis_client is not None:
        return _redis_client

    redis_url = get_redis_url()
    safe_url = _sanitize_url(redis_url)

    logger.info("redis.connecting", url=safe_url)

    # Create connection pool with reasonable defaults
    _connection_pool = ConnectionPool.from_url(
        redis_url,
        max_connections=20,
        decode_responses=False,  # We handle bytes manually for binary data
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=True,
    )

    _redis_client = redis.Redis(connection_pool=_connection_pool)

    # Test connection
    try:
        await _redis_client.ping()
        logger.info("redis.connected", url=safe_url)
    except redis.ConnectionError as e:
        logger.error("redis.connection_failed", url=safe_url, error=str(e))
        raise

    return _redis_client


def _is_circuit_open() -> bool:
    """Check if circuit breaker is open (Redis unavailable).

    Returns:
        True if circuit is open (should skip Redis), False otherwise.
    """
    global _circuit_open_until  # pylint: disable=global-statement
    if _circuit_open_until <= 0:
        return False
    if time.time() >= _circuit_open_until:
        # Timeout expired, reset to half-open (try once)
        _circuit_open_until = 0.0
        logger.info("redis.circuit_half_open",
                    msg="Circuit breaker timeout expired, will try Redis")
        return False
    return True


def _record_success() -> None:
    """Record successful Redis operation, close circuit if needed."""
    global _circuit_failure_count  # pylint: disable=global-statement
    global _circuit_open_until  # pylint: disable=global-statement
    if _circuit_failure_count > 0 or _circuit_open_until > 0:
        logger.info("redis.circuit_closed",
                    previous_failures=_circuit_failure_count)
        _circuit_failure_count = 0
        _circuit_open_until = 0.0
        set_redis_circuit_state(is_open=False)


def _record_failure() -> None:
    """Record failed Redis operation, open circuit if threshold reached."""
    global _circuit_failure_count  # pylint: disable=global-statement
    global _circuit_open_until  # pylint: disable=global-statement
    _circuit_failure_count += 1

    if _circuit_failure_count >= CIRCUIT_FAILURE_THRESHOLD:
        _circuit_open_until = time.time() + CIRCUIT_RESET_TIMEOUT
        set_redis_circuit_state(is_open=True)
        logger.warning(
            "redis.circuit_opened",
            failures=_circuit_failure_count,
            retry_after_seconds=CIRCUIT_RESET_TIMEOUT,
            msg=f"Circuit breaker opened after {_circuit_failure_count} failures"
        )


async def get_redis() -> Optional[redis.Redis]:
    """Get the Redis client instance.

    Returns initialized client or None if not connected.
    Does NOT raise exceptions - returns None for graceful degradation.

    Uses circuit breaker pattern to avoid repeated slow failures:
    - After 3 consecutive failures, stops trying for 30 seconds
    - After timeout, tries once (half-open state)
    - On success, closes circuit and resumes normal operation

    Returns:
        Redis client or None if not available.
    """
    # Check circuit breaker first (fast path when Redis is down)
    if _is_circuit_open():
        return None

    if _redis_client is None:
        logger.warning("redis.client_not_initialized")
        _record_failure()
        return None

    # Check if connection is alive
    try:
        await _redis_client.ping()
        _record_success()
        return _redis_client
    except redis.ConnectionError:
        logger.warning("redis.connection_lost")
        _record_failure()
        return None
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("redis.ping_failed", error=str(e))
        _record_failure()
        return None


def reset_circuit_breaker() -> None:
    """Reset circuit breaker to closed state.

    Useful for manual recovery or testing.
    """
    global _circuit_failure_count  # pylint: disable=global-statement
    global _circuit_open_until  # pylint: disable=global-statement
    _circuit_failure_count = 0
    _circuit_open_until = 0.0
    logger.info("redis.circuit_reset", msg="Circuit breaker manually reset")


def get_circuit_breaker_state() -> dict:
    """Get current circuit breaker state.

    Returns:
        Dict with 'is_open', 'failure_count', 'open_until'.
    """
    return {
        "is_open":
            _is_circuit_open(),
        "failure_count":
            _circuit_failure_count,
        "open_until":
            _circuit_open_until,
        "seconds_until_retry":
            max(0, _circuit_open_until -
                time.time()) if _circuit_open_until > 0 else 0,
    }


async def close_redis() -> None:
    """Close Redis connection pool.

    Call this at application shutdown to clean up connections.
    Safe to call multiple times.
    """
    global _redis_client, _connection_pool  # pylint: disable=global-statement

    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("redis.closed")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("redis.close_error", error=str(e))
        finally:
            _redis_client = None

    if _connection_pool is not None:
        try:
            await _connection_pool.disconnect()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("redis.pool_disconnect_error", error=str(e))
        finally:
            _connection_pool = None


async def redis_health_check() -> dict:
    """Check Redis health status.

    Returns:
        Dict with 'status' ('ok', 'degraded', 'error') and 'info'.
    """
    client = await get_redis()

    if client is None:
        return {"status": "error", "info": "Client not initialized"}

    try:
        server_info = await client.info("server")
        memory_info = await client.info("memory")
        clients_info = await client.info("clients")

        return {
            "status": "ok",
            "info": {
                "redis_version": server_info.get("redis_version"),
                "uptime_seconds": server_info.get("uptime_in_seconds", 0),
                "connected_clients": clients_info.get("connected_clients", 0),
                "used_memory_human": memory_info.get("used_memory_human", "0B"),
                "maxmemory_human": memory_info.get("maxmemory_human", "0B"),
            }
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"status": "error", "info": str(e)}
