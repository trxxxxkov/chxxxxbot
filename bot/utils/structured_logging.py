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

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to INFO.
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper()),
    )

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Gets a configured logger instance.

    Args:
        name: Logger name (usually __name__ of the calling module).

    Returns:
        Configured structlog logger with all processors applied.
    """
    return structlog.get_logger(name)
