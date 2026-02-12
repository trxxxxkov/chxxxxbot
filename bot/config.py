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

# Message limits (Telegram)
MAX_MESSAGE_LENGTH = 4096  # Telegram hard limit
MAX_CAPTION_LENGTH = 1024  # Telegram caption limit
MESSAGE_SPLIT_LENGTH = 3800  # Safe limit for splitting (buffer for HTML escape)
MESSAGE_TRUNCATE_LENGTH = 3900  # Safe limit for truncation during streaming

# Text splitting parameters
TEXT_SPLIT_PARA_WINDOW = 1000  # Search window for paragraph boundary
TEXT_SPLIT_LINE_WINDOW = 500  # Search window for line boundary

# Bot settings
BOT_NAME = "LLM Bot"
BOT_DESCRIPTION = "Telegram bot with LLM access"
BOT_ID: Optional[int] = None  # Set at runtime in main.py
BOT_USERNAME: Optional[str] = None  # Set at runtime in main.py

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

# Files API settings (Phase 1.5)
FILES_API_TTL_HOURS = int(os.getenv("FILES_API_TTL_HOURS", "24"))

# Database settings
MAX_QUERY_LIMIT = 1000  # Hard cap for get_all() queries to prevent memory issues

# Streaming settings
# With sendMessageDraft (Bot API 9.3), no flood control - update immediately
DRAFT_KEEPALIVE_INTERVAL = 5.0  # Keep draft visible during long operations (seconds)
TOOL_LOOP_MAX_ITERATIONS = 100  # Max tool calls per request
TOOL_COST_PRECHECK_ENABLED = True  # Pre-check balance before paid tools

# Concurrency limits (per user)
MAX_CONCURRENT_GENERATIONS_PER_USER = 5  # Max parallel Claude API calls per user
CONCURRENCY_QUEUE_TIMEOUT = 300.0  # Max seconds to wait in queue (5 minutes)

# Topic naming settings (Bot API 9.3: topics in private chats)
# Automatically generates topic names using LLM after first bot response
TOPIC_NAMING_ENABLED = True
TOPIC_NAMING_MODEL = "claude-haiku-4-5-20251001"  # Haiku is cheap (~$0.0003/title)
TOPIC_NAMING_MAX_TOKENS = 30  # Title is short (2-6 words)

# Topic routing (Bot API 9.4: auto-topic management)
TOPIC_ROUTING_ENABLED = True
TOPIC_SWITCH_MIN_GAP_MINUTES = 5  # Min gap before checking relevance in existing topic
TOPIC_SWITCH_RECENT_TOPICS = 5  # Number of recent topics to check
TOPIC_SWITCH_RECENT_MESSAGES = 5  # User messages per topic for context
TOPIC_SWITCH_MSG_TRUNCATE = 200  # Max chars per message in prompt
TOPIC_ROUTING_MODEL = TOPIC_NAMING_MODEL  # Haiku
TOPIC_ROUTING_MAX_TOKENS = 60  # JSON response with optional title
TOPIC_TEMP_NAME_MAX_LENGTH = 30  # Max chars for temp name from General

# Vision model IDs for tool API calls (analyze_image, analyze_pdf, preview_file)
VISION_MODEL_ID = "claude-opus-4-6"  # Full analysis (image, PDF)
VISION_MODEL_ID_LITE = "claude-sonnet-4-5-20250929"  # Lighter preview analysis


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
            model_id="claude-opus-4-6",
            alias="opus",
            display_name="Claude Opus 4.6",
            context_window=
            200_000,  # 1M beta available, keep 200K for cost safety
            max_output=128_000,
            pricing_input=5.0,
            pricing_output=25.0,
            pricing_cache_write_5m=6.25,  # 1.25x multiplier
            pricing_cache_write_1h=10.0,  # 2x multiplier
            pricing_cache_read=0.50,  # 0.1x multiplier
            latency_tier="moderate",
            capabilities={
                "extended_thinking": True,
                "interleaved_thinking": True,
                "adaptive_thinking": True,
                "effort": True,
                "effort_max": True,
                "compaction": True,
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
# Phase 1.4.2 implements 3-level system prompt composition:
#
# 1. GLOBAL_SYSTEM_PROMPT (from prompts/system_prompt.py) - Always cached
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

# Import system prompt from separate module for better maintainability
# pylint: disable=wrong-import-position
from prompts.system_prompt import GLOBAL_SYSTEM_PROMPT  # noqa: E402, F401

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
         ('claude:opus', 'Claude Opus 4.6'),
         ('claude:sonnet', 'Claude Sonnet 4.5')]
    """
    items = [(full_id, model.display_name)
             for full_id, model in MODEL_REGISTRY.items()]
    return sorted(items, key=lambda x: x[0])


# ============================================================================
# Payment System Configuration (Phase 2.1)
# ============================================================================

# Stars to USD conversion rate (market rate, BEFORE commissions)
STARS_TO_USD_RATE: float = 0.013  # $0.013 per Star (~$13 per 1000 Stars)

# ============================================================================
# External API Pricing (Phase 2.1: Cost Tracking)
# ============================================================================

# E2B Code Interpreter pricing
# Based on E2B pricing: https://e2b.dev/pricing
# Standard tier: $0.00005 per second (~$0.18 per hour) of sandbox runtime
E2B_COST_PER_SECOND: float = 0.00005  # $0.00005 per second

# OpenAI Whisper API pricing
# Already tracked in transcribe_audio tool: $0.006 per minute
# Reference: https://openai.com/api/pricing/
WHISPER_COST_PER_MINUTE: float = 0.006  # $0.006 per minute

# Google Gemini Image Generation pricing
# Already tracked in generate_image tool
# 1K/2K: $0.134 per image, 4K: $0.240 per image
# Reference: https://ai.google.dev/pricing
GEMINI_IMAGE_COST_1K: float = 0.134  # $0.134 per 1K/2K image
GEMINI_IMAGE_COST_4K: float = 0.240  # $0.240 per 4K image

# Commission rates for formula: y = x * (1 - k1 - k2 - k3)
TELEGRAM_WITHDRAWAL_FEE: float = 0.35  # k1: 35% Telegram withdrawal commission
TELEGRAM_TOPICS_FEE: float = 0.15  # k2: 15% Topics in private chats commission
DEFAULT_OWNER_MARGIN: float = 0.0  # k3: 0% Default owner margin (configurable)

# Cache write cost subsidy
# When True, users pay for cache writes (default behavior)
# When False, owner absorbs cache write costs (subsidy mode)
CHARGE_USERS_FOR_CACHE_WRITE: bool = True

# Balance settings
STARTER_BALANCE_USD: float = 0.10  # New users get $0.10 starter balance
MINIMUM_BALANCE_FOR_REQUEST: float = 0.0  # Allow requests while balance > 0

# Refund settings
REFUND_PERIOD_DAYS: int = 30  # Maximum days for refund eligibility

# Predefined Stars packages (for /pay command)
STARS_PACKAGES: list[dict[str, int | str]] = [
    {
        "stars": 10,
        "label": "Micro"
    },
    {
        "stars": 50,
        "label": "Starter"
    },
    {
        "stars": 100,
        "label": "Basic"
    },
    {
        "stars": 250,
        "label": "Standard"
    },
    {
        "stars": 500,
        "label": "Premium"
    },
]

# Custom amount range
MIN_CUSTOM_STARS: int = 1
MAX_CUSTOM_STARS: int = 2500

# Payment invoice customization
PAYMENT_INVOICE_TITLE: str = "Bot Balance Top-up"
PAYMENT_INVOICE_DESCRIPTION_TEMPLATE: str = (
    "Pay {stars_amount}⭐ to add ${usd_amount:.2f} to your balance.\n\n"
    "💡 After payment, you'll receive a transaction ID for refunds.")

# Privileged users (loaded from secrets at startup)
PRIVILEGED_USERS: set[int] = set(
)  # Populated from secrets/privileged_users.txt

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
