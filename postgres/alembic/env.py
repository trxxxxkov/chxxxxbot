"""Alembic environment configuration for async migrations.

This module configures Alembic to work with async SQLAlchemy and
imports all models directly (no __init__.py).
"""
# pylint: disable=duplicate-code

import asyncio
import os
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Add bot/ directory to Python path for imports
# In Docker: ./bot mounted at /app, ./postgres mounted at /postgres
bot_path = Path("/app")
sys.path.insert(0, str(bot_path))

# Setup JSON logging BEFORE any other imports that might log
# pylint: disable=wrong-import-position
from utils.structured_logging import setup_logging  # noqa: E402

setup_logging("INFO")

# Import Base and all models (NO __init__.py - direct imports)
# pylint: disable=unused-import
from db.models.balance_operation import BalanceOperation  # noqa: E402,F401
from db.models.base import Base  # noqa: E402
from db.models.chat import Chat  # noqa: E402
from db.models.message import Message  # noqa: E402
from db.models.payment import Payment  # noqa: E402
from db.models.thread import Thread  # noqa: E402
from db.models.tool_call import ToolCall  # noqa: E402
from db.models.user import User  # noqa: E402
from db.models.user_file import UserFile  # noqa: E402

# Alembic Config object
config = context.config

# Note: We don't use fileConfig() anymore - setup_logging() handles all logging

# Target metadata for autogenerate
target_metadata = Base.metadata


def get_database_url() -> str:
    """Get database URL from environment variables.

    Returns:
        PostgreSQL connection URL for asyncpg.
    """
    password_file = Path("/run/secrets/postgres_password")
    if password_file.exists():
        password = password_file.read_text(encoding='utf-8').strip()
    else:
        password = os.getenv("POSTGRES_PASSWORD", "postgres")

    host = os.getenv("DATABASE_HOST", "postgres")
    port = os.getenv("DATABASE_PORT", "5432")
    user = os.getenv("DATABASE_USER", "postgres")
    database = os.getenv("DATABASE_NAME", "postgres")

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async mode."""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
