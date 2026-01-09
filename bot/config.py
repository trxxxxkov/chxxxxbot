"""Application configuration and constants.

This module contains all configuration constants used throughout the bot
application. No secrets should be stored here - they are read from Docker
secrets in main.py.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional

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
CLAUDE_MAX_TOKENS = 4096  # Max tokens to generate per response
CLAUDE_TEMPERATURE = 1.0  # Sampling temperature (0.0-2.0)
CLAUDE_TIMEOUT = 60  # API request timeout in seconds
CLAUDE_TOKEN_BUFFER_PERCENT = 0.10  # Safety buffer for token counting


@dataclass
class ModelConfig:  # pylint: disable=too-many-instance-attributes
    """Universal model configuration for any LLM provider.

    Designed to support Claude, OpenAI, Google, and future providers.
    Uses flexible capabilities dict for provider-specific features.

    Attributes:
        provider: Provider name ("claude", "openai", "google").
        model_id: Provider-specific model ID for API calls.
        alias: Short alias within provider ("sonnet", "haiku", "opus").
        display_name: Human-readable name for UI.

        context_window: Maximum input tokens.
        max_output: Maximum output tokens.

        pricing_input: Input token cost per million tokens (USD).
        pricing_output: Output token cost per million tokens (USD).
        pricing_cache_write_5m: 5-minute cache write cost (or None).
        pricing_cache_write_1h: 1-hour cache write cost (or None).
        pricing_cache_read: Cache read cost (or None).

        latency_tier: "fastest" | "fast" | "moderate" | "slow"

        capabilities: Dict with boolean flags for provider-specific features.
            Claude: {"extended_thinking", "effort", "vision", "streaming"}
            OpenAI: {"function_calling", "vision", "json_mode"}
            Google: {"grounding", "code_execution", "vision"}
    """

    # Identity
    provider: str
    model_id: str
    alias: str
    display_name: str

    # Technical specs
    context_window: int
    max_output: int

    # Pricing (None if not supported by provider)
    pricing_input: float
    pricing_output: float
    pricing_cache_write_5m: Optional[float]
    pricing_cache_write_1h: Optional[float]
    pricing_cache_read: Optional[float]

    # Performance
    latency_tier: str

    # Provider-specific capabilities (flexible)
    capabilities: dict[str, bool]

    def get_full_id(self) -> str:
        """Get full model identifier: 'provider:alias'.

        Examples:
            - claude:sonnet
            - openai:gpt4
            - google:gemini

        Returns:
            Composite identifier string.
        """
        return f"{self.provider}:{self.alias}"

    def has_capability(self, capability: str) -> bool:
        """Check if model supports specific capability.

        Args:
            capability: Capability name to check.

        Returns:
            True if capability supported, False otherwise.
        """
        return self.capabilities.get(capability, False)


# ============================================================================
# Model Registry (Universal - supports Claude, OpenAI, Google, and future)
# ============================================================================
# Key format: "provider:alias" (e.g., "claude:sonnet", "openai:gpt4")
# Pricing verified: https://platform.claude.com/docs/en/about-claude/pricing

MODEL_REGISTRY: dict[str, ModelConfig] = {
    # ============ Claude 4.5 Models (Phase 1.4.1) ============
    # Ordered by capability: Haiku (fastest) -> Sonnet (balanced) -> Opus (most capable)
    "claude:haiku":
        ModelConfig(
            provider="claude",
            model_id="claude-haiku-4-5-20251001",
            alias="haiku",
            display_name="Claude Haiku 4.5",
            context_window=200_000,
            max_output=64_000,
            pricing_input=1.0,
            pricing_output=5.0,
            pricing_cache_write_5m=1.25,  # 1.25x multiplier
            pricing_cache_write_1h=2.0,  # 2x multiplier
            pricing_cache_read=0.10,  # 0.1x multiplier
            latency_tier="fastest",
            capabilities={
                "extended_thinking": True,
                "interleaved_thinking": True,
                "effort": False,
                "context_awareness": True,
                "vision": True,
                "streaming": True,
                "prompt_caching": True,
            },
        ),
    "claude:sonnet":
        ModelConfig(
            provider="claude",
            model_id="claude-sonnet-4-5-20250929",
            alias="sonnet",
            display_name="Claude Sonnet 4.5",
            context_window=200_000,  # 200K (1M with beta, but we use 200K)
            max_output=64_000,
            pricing_input=3.0,
            pricing_output=15.0,
            pricing_cache_write_5m=3.75,  # 1.25x multiplier
            pricing_cache_write_1h=6.0,  # 2x multiplier
            pricing_cache_read=0.30,  # 0.1x multiplier
            latency_tier="fast",
            capabilities={
                "extended_thinking": True,
                "interleaved_thinking": True,
                "effort": False,
                "context_awareness": True,
                "vision": True,
                "streaming": True,
                "prompt_caching": True,
            },
        ),
    "claude:opus":
        ModelConfig(
            provider="claude",
            model_id="claude-opus-4-5-20251101",
            alias="opus",
            display_name="Claude Opus 4.5",
            context_window=200_000,
            max_output=64_000,
            pricing_input=5.0,
            pricing_output=25.0,
            pricing_cache_write_5m=6.25,  # 1.25x multiplier
            pricing_cache_write_1h=10.0,  # 2x multiplier
            pricing_cache_read=0.50,  # 0.1x multiplier
            latency_tier="moderate",
            capabilities={
                "extended_thinking": True,
                "interleaved_thinking": True,
                "effort": True,  # Only Opus 4.5 supports effort parameter!
                "context_awareness": True,
                "vision": True,
                "streaming": True,
                "prompt_caching": True,
            },
        ),
    # ============ Future: OpenAI Models (Phase 3.4) ============
    # "openai:gpt4": ModelConfig(
    #     provider="openai",
    #     model_id="gpt-4-turbo-2024-04-09",
    #     alias="gpt4",
    #     display_name="GPT-4 Turbo",
    #     context_window=128_000,
    #     max_output=4_096,
    #     pricing_input=10.0,
    #     pricing_output=30.0,
    #     pricing_cache_write_5m=None,  # OpenAI doesn't have prompt caching
    #     pricing_cache_write_1h=None,
    #     pricing_cache_read=None,
    #     latency_tier="fast",
    #     capabilities={
    #         "function_calling": True,
    #         "vision": True,
    #         "json_mode": True,
    #         "streaming": True,
    #     },
    # ),
    # ============ Future: Google Models (Phase 3.4) ============
    # "google:gemini": ModelConfig(
    #     provider="google",
    #     model_id="gemini-1.5-pro",
    #     alias="gemini",
    #     display_name="Gemini 1.5 Pro",
    #     context_window=1_000_000,
    #     max_output=8_192,
    #     pricing_input=3.5,
    #     pricing_output=10.5,
    #     pricing_cache_write_5m=None,
    #     pricing_cache_write_1h=None,
    #     pricing_cache_read=None,
    #     latency_tier="moderate",
    #     capabilities={
    #         "grounding": True,
    #         "code_execution": True,
    #         "vision": True,
    #         "streaming": True,
    #     },
    # ),
}

# Default model (Claude Sonnet 4.5 - best balance of intelligence, speed, cost)
DEFAULT_MODEL_ID = "claude:sonnet"

# ============================================================================
# System Prompt Architecture
# ============================================================================
# Phase 1.4.2 will implement 3-level system prompt composition:
#
# 1. GLOBAL_SYSTEM_PROMPT (below) - Always cached, same for all users
#    - Base instructions for Claude
#    - Tool descriptions (code execution, image generation, etc.)
#    - General behavior guidelines
#
# 2. User.custom_prompt (per user) - Rarely changes, can be cached
#    - Personal preferences (language, tone, style)
#    - User-specific instructions
#
# 3. Thread.files_context (per thread) - Dynamic, NOT cached
#    - List of files available in current thread
#    - Auto-generated when files are added
#
# Final prompt = GLOBAL + User.custom_prompt + Thread.files_context
# ============================================================================

GLOBAL_SYSTEM_PROMPT = (
    "You are a helpful AI assistant powered by Claude. "
    "You provide clear, accurate, and helpful responses to user questions.\n\n"
    "Key behaviors:\n"
    "- Be concise but thorough in your responses\n"
    "- Use formatting (markdown) to improve readability\n"
    "- If you're uncertain about something, be honest about it\n"
    "- Break down complex topics into understandable parts\n"
    "- Ask clarifying questions when needed")

# ============================================================================
# Model Registry Helper Functions
# ============================================================================


def get_model(full_id: str) -> ModelConfig:
    """Get model by full ID (provider:alias).

    Args:
        full_id: Composite identifier like "claude:sonnet" or "openai:gpt4".

    Returns:
        ModelConfig for requested model.

    Raises:
        KeyError: If model not found in registry.

    Examples:
        >>> model = get_model("claude:sonnet")
        >>> model.display_name
        'Claude Sonnet 4.5'
    """
    if full_id not in MODEL_REGISTRY:
        available = list(MODEL_REGISTRY.keys())
        raise KeyError(f"Model '{full_id}' not found in registry. "
                       f"Available models: {available}")
    return MODEL_REGISTRY[full_id]


def get_model_by_provider_id(provider: str, model_id: str) -> ModelConfig:
    """Get model by provider and exact model_id.

    Useful for reverse lookup from API responses.

    Args:
        provider: Provider name ("claude", "openai", "google").
        model_id: Exact model ID (e.g., "claude-sonnet-4-5-20250929").

    Returns:
        ModelConfig for requested model.

    Raises:
        ValueError: If model not found.

    Examples:
        >>> model = get_model_by_provider_id("claude",
        ...                                  "claude-sonnet-4-5-20250929")
        >>> model.alias
        'sonnet'
    """
    for model in MODEL_REGISTRY.values():
        if model.provider == provider and model.model_id == model_id:
            return model

    raise ValueError(f"Model with provider='{provider}' and "
                     f"model_id='{model_id}' not found in registry.")


def get_models_by_provider(provider: str) -> list[ModelConfig]:
    """Get all models for specific provider.

    Args:
        provider: Provider name ("claude", "openai", "google").

    Returns:
        List of ModelConfig objects for this provider, in registry order
        (Haiku -> Sonnet -> Opus for Claude).

    Examples:
        >>> claude_models = get_models_by_provider("claude")
        >>> len(claude_models)
        3
    """
    # Preserve order from MODEL_REGISTRY (dict preserves insertion order in Python 3.7+)
    models = [
        model for model in MODEL_REGISTRY.values() if model.provider == provider
    ]
    return models


def get_default_model() -> ModelConfig:
    """Get default model (Claude Sonnet 4.5).

    Returns:
        Default ModelConfig.
    """
    return MODEL_REGISTRY[DEFAULT_MODEL_ID]


def list_all_models() -> list[tuple[str, str]]:
    """List all available models (id, display_name).

    Returns:
        List of tuples (full_id, display_name) sorted by provider and alias.

    Examples:
        >>> models = list_all_models()
        >>> models
        [('claude:haiku', 'Claude Haiku 4.5'),
         ('claude:opus', 'Claude Opus 4.5'),
         ('claude:sonnet', 'Claude Sonnet 4.5')]
    """
    items = [(full_id, model.display_name)
             for full_id, model in MODEL_REGISTRY.items()]
    return sorted(items, key=lambda x: x[0])


# ============================================================================
# Database Configuration
# ============================================================================


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
