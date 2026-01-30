"""Structured logging configuration using structlog.

This module provides structured logging setup for the bot application.
All logs are formatted as JSON for easy parsing by log aggregation systems
like Loki.
"""

import logging
import sys

import structlog


class AiogramLogFilter(logging.Filter):
    """Filter to downgrade routine aiogram events to INFO level.

    Certain aiogram messages are logged at WARNING/ERROR but are actually
    normal operational events:
    - Network errors during polling (reconnection events)
    - SIGTERM/SIGINT signals (normal container shutdown)

    This filter changes their level to INFO.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Check and optionally modify log record level.

        Args:
            record: The log record to filter.

        Returns:
            True to emit the record (always returns True, just modifies level).
        """
        msg = str(record.msg)

        # Network errors during polling - normal reconnection
        # BUT: multiple bot instances conflict should remain a warning
        if record.levelno == logging.ERROR and "Failed to fetch updates" in msg:
            if "terminated by other getUpdates request" in msg:
                # Multiple bot instances running - this is a serious issue
                record.levelno = logging.WARNING
                record.levelname = "WARNING"
            else:
                # Normal network errors (timeout, connection reset)
                record.levelno = logging.INFO
                record.levelname = "INFO"

        # SIGTERM/SIGINT - normal container shutdown
        if record.levelno == logging.WARNING and "signal" in msg.lower():
            record.levelno = logging.INFO
            record.levelname = "INFO"

        return True


class E2BLogFilter(logging.Filter):
    """Filter to downgrade routine E2B sandbox events to INFO level.

    E2B SDK logs 404 errors when trying to reconnect to expired sandboxes.
    This is normal behavior - the system automatically creates a new sandbox.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Check and optionally modify log record level.

        Args:
            record: The log record to filter.

        Returns:
            True to emit the record (always returns True, just modifies level).
        """
        msg = str(record.msg)

        # 404 errors when sandbox expired - normal, we create a new one
        if record.levelno == logging.ERROR and "Response 404" in msg:
            record.levelno = logging.INFO
            record.levelname = "INFO"

        # Also handle "not found" messages
        if record.levelno == logging.ERROR and "not found" in msg.lower():
            record.levelno = logging.INFO
            record.levelname = "INFO"

        return True


def _downgrade_404_errors(_logger: str, method_name: str,
                          event_dict: dict) -> dict:
    """Structlog processor to downgrade 404 sandbox errors to info level.

    E2B SDK logs 404 errors when trying to reconnect to expired sandboxes.
    This is normal behavior - we automatically create a new sandbox.
    """
    event = event_dict.get("event", "")
    level = event_dict.get("level", "")

    # Downgrade "Response 404" errors to info
    if level == "error" and "Response 404" in str(event):
        event_dict["level"] = "info"

    # Also downgrade "not found" messages
    if level == "error" and "not found" in str(event).lower():
        event_dict["level"] = "info"

    return event_dict


def setup_logging(level: str = "INFO") -> None:
    """Configures structlog for JSON logging.

    Sets up both standard library logging and structlog with processors
    for structured logging output in JSON format. Includes context
    variables, timestamps, and exception information.

    This configuration ensures ALL logs (including third-party libraries
    like aiogram, aiohttp) are formatted as JSON for Loki compatibility.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
    """
    # Shared processors for both structlog and stdlib logging
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        _downgrade_404_errors,  # Downgrade E2B 404 errors to info
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors + [structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging to output JSON
    # This catches all third-party library logs (aiogram, aiohttp, etc.)
    formatter = structlog.stdlib.ProcessorFormatter(
        # These processors run on ALL log entries (stdlib + structlog)
        foreign_pre_chain=shared_processors,
        # Final processor for stdlib logs
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper()))
    # Add E2B filter to root to catch 404 from any source
    root_logger.addFilter(E2BLogFilter())

    # Aiogram dispatcher: only show actual errors, not routine retries
    dispatcher_logger = logging.getLogger("aiogram.dispatcher")
    dispatcher_logger.setLevel(logging.ERROR)
    dispatcher_logger.addFilter(AiogramLogFilter())

    # Suppress verbose debug logs from HTTP libraries (contain full request bodies)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.INFO)

    # E2B sandbox: 404 on reconnect is normal (sandbox expired)
    # Apply filter to all E2B-related loggers including HTTP clients
    for logger_name in ["e2b", "e2b_code_interpreter", "httpx", "httpcore"]:
        e2b_related_logger = logging.getLogger(logger_name)
        e2b_related_logger.addFilter(E2BLogFilter())


def get_logger(name: str) -> structlog.BoundLogger:
    """Gets a configured logger instance.

    Args:
        name: Logger name (usually __name__ of the calling module).

    Returns:
        Configured structlog logger with all processors applied.
    """
    return structlog.get_logger(name)
