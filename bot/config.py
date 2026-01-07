"""Application configuration and constants.

This module contains all configuration constants used throughout the bot
application. No secrets should be stored here - they are read from Docker
secrets in main.py.
"""

from dataclasses import dataclass
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

# Claude API settings
CLAUDE_DEFAULT_MODEL = "claude-sonnet-4-5-20250929"  # Phase 1.3: hardcoded
CLAUDE_MAX_TOKENS = 4096  # Max tokens to generate per response
CLAUDE_TEMPERATURE = 1.0  # Sampling temperature (0.0-2.0)
CLAUDE_TIMEOUT = 60  # API request timeout in seconds
CLAUDE_TOKEN_BUFFER_PERCENT = 0.10  # Safety buffer for token counting


@dataclass
class ModelConfig:
    """Configuration for a Claude model.

    Contains all model-specific parameters including context window size,
    output limits, and pricing per million tokens.

    Attributes:
        name: Official model name from Anthropic API.
        display_name: Human-readable model name.
        context_window: Maximum input tokens (context window size).
        max_output_tokens: Maximum tokens that can be generated.
        input_price_per_mtok: Price per million input tokens (USD).
        output_price_per_mtok: Price per million output tokens (USD).
    """

    name: str
    display_name: str
    context_window: int
    max_output_tokens: int
    input_price_per_mtok: float
    output_price_per_mtok: float


# Global model registry
# Pricing verified from https://platform.claude.com/docs/en/about-claude/models/overview
CLAUDE_MODELS = {
    "claude-sonnet-4.5":
        ModelConfig(
            name="claude-sonnet-4-5-20250929",
            display_name="Claude Sonnet 4.5",
            context_window=200_000,  # 200K tokens (1M with beta header)
            max_output_tokens=64_000,  # 64K tokens
            input_price_per_mtok=3.0,  # $3 / MTok (official pricing)
            output_price_per_mtok=15.0  # $15 / MTok (official pricing)
        ),
}

# Default model key (for looking up in CLAUDE_MODELS)
DEFAULT_MODEL = "claude-sonnet-4.5"

# Global system prompt (same for all users in Phase 1.3)
# Phase 1.4 will support per-thread system prompts from database
GLOBAL_SYSTEM_PROMPT = (
    "You are a helpful AI assistant powered by Claude. "
    "You provide clear, accurate, and helpful responses to user questions.\n\n"
    "Key behaviors:\n"
    "- Be concise but thorough in your responses\n"
    "- Use formatting (markdown) to improve readability\n"
    "- If you're uncertain about something, be honest about it\n"
    "- Break down complex topics into understandable parts\n"
    "- Ask clarifying questions when needed")


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
