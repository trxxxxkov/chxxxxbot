"""Structured logging configuration using structlog.

This module provides structured logging setup for the bot application.
All logs are formatted as JSON for easy parsing by log aggregation systems
like Loki.
"""

import logging
import sys

import structlog


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
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors + [
            structlog.processors.JSONRenderer()
        ],
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

    # Suppress aiogram dispatcher warnings (SIGTERM logged as warning)
    logging.getLogger("aiogram.dispatcher").setLevel(logging.ERROR)


def get_logger(name: str) -> structlog.BoundLogger:
    """Gets a configured logger instance.

    Args:
        name: Logger name (usually __name__ of the calling module).

    Returns:
        Configured structlog logger with all processors applied.
    """
    return structlog.get_logger(name)
