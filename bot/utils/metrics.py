"""Prometheus metrics for the Telegram bot.

This module defines and exports Prometheus metrics for monitoring bot
performance, usage, and costs. Metrics are exposed via HTTP endpoint.
"""

import asyncio

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client import Counter
from prometheus_client import Gauge
from prometheus_client import generate_latest
from prometheus_client import Histogram
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# === Message Metrics ===

MESSAGES_RECEIVED = Counter(
    'bot_messages_received_total',
    'Total number of messages received',
    ['chat_type', 'content_type']  # private/group, text/photo/voice/etc
)

MESSAGES_SENT = Counter('bot_messages_sent_total',
                        'Total number of messages sent by bot', ['chat_type'])

# === Claude API Metrics ===

CLAUDE_REQUESTS = Counter(
    'bot_claude_requests_total',
    'Total number of Claude API requests',
    ['model', 'status']  # model name, success/error
)

CLAUDE_TOKENS = Counter(
    'bot_claude_tokens_total',
    'Total Claude tokens used',
    ['model', 'type']  # values: input/output/cache_read/cache_write
)

CLAUDE_RESPONSE_TIME = Histogram('bot_claude_response_seconds',
                                 'Claude API response time in seconds',
                                 ['model'],
                                 buckets=[0.5, 1, 2, 5, 10, 20, 30, 60, 120])

# === Tool Metrics ===

TOOL_CALLS = Counter(
    'bot_tool_calls_total',
    'Total number of tool calls',
    ['tool_name', 'status']  # success/error
)

TOOL_EXECUTION_TIME = Histogram('bot_tool_execution_seconds',
                                'Tool execution time in seconds', ['tool_name'],
                                buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60])

# === Cost Metrics ===

COSTS_USD = Counter(
    'bot_costs_usd_total',
    'Total costs in USD',
    ['service']  # claude/whisper/e2b/gemini
)

# === User Metrics ===

ACTIVE_USERS = Gauge('bot_active_users', 'Number of unique users in last hour')

TOTAL_BALANCE_USD = Gauge('bot_total_balance_usd',
                          'Sum of all user balances in USD')

TOTAL_USERS = Gauge('bot_total_users', 'Total number of registered users')

TOTAL_THREADS = Gauge('bot_total_threads',
                      'Total number of conversation threads')

# === Disk Usage Metrics ===

DISK_USAGE_BYTES = Gauge(
    'bot_disk_usage_bytes',
    'Disk usage in bytes',
    ['volume']  # postgres/loki/prometheus/grafana/total
)

TOP_USER_MESSAGES = Gauge('bot_top_user_messages',
                          'Message count for top users',
                          ['user_id', 'username', 'rank'])

TOP_USER_TOKENS = Gauge('bot_top_user_tokens', 'Token usage for top users',
                        ['user_id', 'username', 'rank'])

# === Error Metrics ===

ERRORS = Counter('bot_errors_total', 'Total number of errors',
                 ['error_type', 'handler'])

# === Database Metrics ===

DB_CONNECTIONS_ACTIVE = Gauge('bot_db_connections_active',
                              'Number of active database connections')

DB_CONNECTIONS_IDLE = Gauge('bot_db_connections_idle',
                            'Number of idle database connections in pool')

DB_POOL_OVERFLOW = Gauge('bot_db_pool_overflow',
                         'Number of overflow connections')

DB_QUERY_TIME = Histogram(
    'bot_db_query_seconds',
    'Database query execution time in seconds',
    ['operation'],  # select/insert/update/delete
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1])

# === Queue Metrics ===

QUEUE_THREADS_TOTAL = Gauge('bot_queue_threads_total',
                            'Total number of threads in message queue')

QUEUE_THREADS_PROCESSING = Gauge(
    'bot_queue_threads_processing',
    'Number of threads currently processing messages')

QUEUE_THREADS_WAITING = Gauge('bot_queue_threads_waiting',
                              'Number of threads with messages waiting')

QUEUE_MESSAGES_BATCHED = Counter('bot_queue_messages_batched_total',
                                 'Total number of messages batched together')

# === Cache Metrics ===

PROMPT_CACHE_HITS = Counter('bot_prompt_cache_hits_total',
                            'Total number of prompt cache hits')

PROMPT_CACHE_MISSES = Counter(
    'bot_prompt_cache_misses_total',
    'Total number of prompt cache misses (new writes)')

PROMPT_CACHE_TOKENS_SAVED = Counter(
    'bot_prompt_cache_tokens_saved_total',
    'Total tokens saved by prompt cache (cache_read_tokens)')

# === Files API Metrics ===

FILES_API_UPLOADS = Counter(
    'bot_files_api_uploads_total',
    'Total number of files uploaded to Claude Files API',
    ['file_type']  # image/pdf/audio/video
)

FILES_API_ACTIVE = Gauge(
    'bot_files_api_active',
    'Number of active files in Claude Files API (24h TTL)')

# === Helper Functions ===


def record_message_received(chat_type: str, content_type: str) -> None:
    """Record a received message."""
    MESSAGES_RECEIVED.labels(chat_type=chat_type,
                             content_type=content_type).inc()


def record_message_sent(chat_type: str) -> None:
    """Record a sent message."""
    MESSAGES_SENT.labels(chat_type=chat_type).inc()


def record_claude_request(model: str, success: bool) -> None:
    """Record a Claude API request."""
    CLAUDE_REQUESTS.labels(model=model,
                           status='success' if success else 'error').inc()


def record_claude_tokens(model: str,
                         input_tokens: int = 0,
                         output_tokens: int = 0,
                         cache_read_tokens: int = 0,
                         cache_write_tokens: int = 0) -> None:
    """Record Claude token usage."""
    if input_tokens:
        CLAUDE_TOKENS.labels(model=model, type='input').inc(input_tokens)
    if output_tokens:
        CLAUDE_TOKENS.labels(model=model, type='output').inc(output_tokens)
    if cache_read_tokens:
        CLAUDE_TOKENS.labels(model=model,
                             type='cache_read').inc(cache_read_tokens)
    if cache_write_tokens:
        CLAUDE_TOKENS.labels(model=model,
                             type='cache_write').inc(cache_write_tokens)


def record_claude_response_time(model: str, seconds: float) -> None:
    """Record Claude API response time."""
    CLAUDE_RESPONSE_TIME.labels(model=model).observe(seconds)


def record_tool_call(tool_name: str, success: bool, duration: float) -> None:
    """Record a tool call with its execution time."""
    TOOL_CALLS.labels(tool_name=tool_name,
                      status='success' if success else 'error').inc()
    TOOL_EXECUTION_TIME.labels(tool_name=tool_name).observe(duration)


def record_cost(service: str, amount_usd: float) -> None:
    """Record a cost in USD."""
    COSTS_USD.labels(service=service).inc(amount_usd)


def record_error(error_type: str, handler: str) -> None:
    """Record an error."""
    ERRORS.labels(error_type=error_type, handler=handler).inc()


def set_active_users(count: int) -> None:
    """Set the number of active users."""
    ACTIVE_USERS.set(count)


def set_total_balance(amount_usd: float) -> None:
    """Set the total user balance."""
    TOTAL_BALANCE_USD.set(amount_usd)


def set_total_users(count: int) -> None:
    """Set the total number of users."""
    TOTAL_USERS.set(count)


def set_total_threads(count: int) -> None:
    """Set the total number of threads."""
    TOTAL_THREADS.set(count)


def set_disk_usage(volume: str, bytes_used: int) -> None:
    """Set disk usage for a volume."""
    DISK_USAGE_BYTES.labels(volume=volume).set(bytes_used)


def set_top_users(users: list[tuple[str, str, int, int]],
                  metric_type: str = "messages") -> None:
    """Set top users metrics.

    Args:
        users: List of (user_id, username, messages, tokens) tuples.
        metric_type: "messages" or "tokens".
    """
    gauge = TOP_USER_MESSAGES if metric_type == "messages" else TOP_USER_TOKENS
    value_idx = 2 if metric_type == "messages" else 3

    for rank, (user_id, username, messages, tokens) in enumerate(users, 1):
        value = messages if metric_type == "messages" else tokens
        gauge.labels(user_id=str(user_id),
                     username=username or "unknown",
                     rank=str(rank)).set(value)


def set_db_pool_stats(active: int, idle: int, overflow: int) -> None:
    """Set database connection pool statistics."""
    DB_CONNECTIONS_ACTIVE.set(active)
    DB_CONNECTIONS_IDLE.set(idle)
    DB_POOL_OVERFLOW.set(overflow)


def record_db_query_time(operation: str, seconds: float) -> None:
    """Record database query execution time."""
    DB_QUERY_TIME.labels(operation=operation).observe(seconds)


def set_queue_stats(total: int, processing: int, waiting: int) -> None:
    """Set message queue statistics."""
    QUEUE_THREADS_TOTAL.set(total)
    QUEUE_THREADS_PROCESSING.set(processing)
    QUEUE_THREADS_WAITING.set(waiting)


def record_messages_batched(count: int) -> None:
    """Record number of messages batched together."""
    QUEUE_MESSAGES_BATCHED.inc(count)


def record_cache_hit(tokens_saved: int = 0) -> None:
    """Record a prompt cache hit with tokens saved."""
    PROMPT_CACHE_HITS.inc()
    if tokens_saved > 0:
        PROMPT_CACHE_TOKENS_SAVED.inc(tokens_saved)


def record_cache_miss() -> None:
    """Record a prompt cache miss (new cache write)."""
    PROMPT_CACHE_MISSES.inc()


def record_file_upload(file_type: str) -> None:
    """Record a file upload to Claude Files API."""
    FILES_API_UPLOADS.labels(file_type=file_type).inc()


def set_active_files(count: int) -> None:
    """Set the number of active files in Files API."""
    FILES_API_ACTIVE.set(count)


# === HTTP Server ===


async def metrics_handler(request: web.Request) -> web.Response:
    """Handle /metrics endpoint for Prometheus scraping."""
    # CONTENT_TYPE_LATEST includes charset, but aiohttp doesn't allow that
    # So we set headers manually
    return web.Response(body=generate_latest(),
                        headers={'Content-Type': CONTENT_TYPE_LATEST})


async def health_handler(request: web.Request) -> web.Response:
    """Handle /health endpoint (alias for /health/live)."""
    return web.Response(text='ok')


async def health_live_handler(request: web.Request) -> web.Response:
    """Handle /health/live endpoint (liveness probe).

    Simple check that the process is alive.
    Used by container orchestrators for liveness probes.
    """
    return web.Response(text='ok')


async def health_ready_handler(request: web.Request) -> web.Response:
    """Handle /health/ready endpoint (readiness probe).

    Checks that the service is ready to accept traffic:
    - Database connection is working

    Returns 200 if ready, 503 if not.
    """
    import json
    checks = {"database": "unknown"}

    try:
        # Check database connection
        from db.engine import \
            get_session  # pylint: disable=import-outside-toplevel
        from sqlalchemy import text  # pylint: disable=import-outside-toplevel

        async with get_session() as session:
            result = await session.execute(text("SELECT 1"))
            if result.scalar() == 1:
                checks["database"] = "ok"
            else:
                checks["database"] = "error"
    except Exception as e:  # pylint: disable=broad-exception-caught
        checks["database"] = f"error: {str(e)}"

    # Determine overall status
    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    return web.Response(text=json.dumps({
        "status": "ready" if all_ok else "not_ready",
        "checks": checks
    }),
                        status=status_code,
                        content_type="application/json")


async def start_metrics_server(host: str = '0.0.0.0', port: int = 8080) -> None:
    """Start the metrics HTTP server.

    Args:
        host: Host to bind to. Defaults to all interfaces.
        port: Port to listen on. Defaults to 8080.
    """
    app = web.Application()
    app.router.add_get('/metrics', metrics_handler)
    app.router.add_get('/health', health_handler)
    app.router.add_get('/health/live', health_live_handler)
    app.router.add_get('/health/ready', health_ready_handler)

    # Disable access logging to prevent non-JSON logs polluting Loki
    # (Prometheus scrapes /metrics every 15s, these logs are noise)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info('metrics_server_started', host=host, port=port)
