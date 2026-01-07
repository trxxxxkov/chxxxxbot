"""Application configuration and constants.

This module contains all configuration constants used throughout the bot
application. No secrets should be stored here - they are read from Docker
secrets in main.py.
"""

import os
from pathlib import Path

# Timeouts
REQUEST_TIMEOUT = 30  # seconds
POLLING_TIMEOUT = 60  # seconds

# Message limits
MAX_MESSAGE_LENGTH = 4096  # Telegram limit
MAX_CAPTION_LENGTH = 1024  # Telegram limit

# Bot settings
BOT_NAME = "LLM Bot"
BOT_DESCRIPTION = "Telegram bot with LLM access"

# Database settings
DATABASE_POOL_SIZE = 5  # Base connection pool size
DATABASE_MAX_OVERFLOW = 10  # Additional connections during load spikes
DATABASE_POOL_TIMEOUT = 30  # seconds
DATABASE_POOL_RECYCLE = 3600  # Recycle connections after 1 hour
DATABASE_ECHO = False  # Set True for SQL debugging


def get_database_url() -> str:
    """Construct PostgreSQL connection URL from environment and secrets.

    Reads password from Docker secret and constructs async PostgreSQL URL
    for use with SQLAlchemy and asyncpg.

    Connection parameters are read from environment variables with defaults:
    - DATABASE_HOST: postgres (default)
    - DATABASE_PORT: 5432 (default)
    - DATABASE_USER: postgres (default)
    - DATABASE_NAME: postgres (default)

    Returns:
        Connection URL in format:
            postgresql+asyncpg://user:pass@host:port/database

    Raises:
        FileNotFoundError: If postgres_password secret not found.
    """
    # Read password from Docker secret
    secret_path = Path("/run/secrets/postgres_password")
    password = secret_path.read_text(encoding='utf-8').strip()

    # Connection parameters (from environment or defaults)
    host = os.getenv("DATABASE_HOST", "postgres")
    port = os.getenv("DATABASE_PORT", "5432")
    user = os.getenv("DATABASE_USER", "postgres")
    database = os.getenv("DATABASE_NAME", "postgres")

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
