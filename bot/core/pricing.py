"""Centralized pricing constants and cost calculation utilities.

Single source of truth for all API pricing.

NO __init__.py - use direct import:
    from core.pricing import calculate_whisper_cost, WHISPER_COST_PER_MINUTE
"""

from decimal import Decimal
from typing import Optional

from utils.structured_logging import get_logger

logger = get_logger(__name__)

# =============================================================================
# OpenAI Whisper Pricing
# =============================================================================

# Whisper API: $0.006 per minute
WHISPER_COST_PER_MINUTE = Decimal("0.006")


def calculate_whisper_cost(duration_seconds: float) -> Decimal:
    """Calculate Whisper transcription cost.

    Args:
        duration_seconds: Audio duration in seconds.

    Returns:
        Cost in USD as Decimal.
    """
    duration_minutes = Decimal(str(duration_seconds)) / Decimal("60")
    return duration_minutes * WHISPER_COST_PER_MINUTE


# =============================================================================
# E2B Sandbox Pricing
# =============================================================================

# E2B Code Interpreter: $0.00005 per second
E2B_COST_PER_SECOND = Decimal("0.00005")


def calculate_e2b_cost(duration_seconds: float) -> Decimal:
    """Calculate E2B sandbox cost.

    Args:
        duration_seconds: Sandbox execution time in seconds.

    Returns:
        Cost in USD as Decimal.
    """
    return Decimal(str(duration_seconds)) * E2B_COST_PER_SECOND


# =============================================================================
# Google Gemini Image Generation Pricing
# =============================================================================

# Nano Banana Pro pricing per image
GEMINI_IMAGE_COST_STANDARD = Decimal("0.134")  # 1K/2K resolution
GEMINI_IMAGE_COST_4K = Decimal("0.240")  # 4K resolution


def calculate_gemini_image_cost(resolution: str = "2048x2048") -> Decimal:
    """Calculate Gemini image generation cost.

    Args:
        resolution: Image resolution string (e.g., "2048x2048", "4096x4096").

    Returns:
        Cost in USD as Decimal.
    """
    if "4096" in resolution:
        return GEMINI_IMAGE_COST_4K
    return GEMINI_IMAGE_COST_STANDARD


# =============================================================================
# Claude API Pricing (per 1M tokens)
# =============================================================================

# Claude model pricing - imported from config.py MODEL_REGISTRY
# This module provides calculation utilities


def calculate_claude_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    thinking_tokens: int = 0,
) -> Decimal:
    """Calculate Claude API cost.

    Args:
        model_id: Model identifier (e.g., 'claude-sonnet-4-5-20250929').
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        cache_read_tokens: Number of cache read tokens.
        cache_creation_tokens: Number of cache creation tokens.
        thinking_tokens: Number of thinking tokens (billed as output).

    Returns:
        Cost in USD as Decimal.
    """
    # Import here to avoid circular dependency
    from config import \
        MODEL_REGISTRY  # pylint: disable=import-outside-toplevel

    # Find model by model_id (ModelConfig is a dataclass, use attribute access)
    model_config = None
    for model in MODEL_REGISTRY.values():
        if model.model_id == model_id:
            model_config = model
            break

    if not model_config:
        logger.warning("pricing.model_not_found", model_id=model_id)
        return Decimal("0")

    # Calculate costs per million tokens
    input_cost = (Decimal(str(input_tokens)) / Decimal("1000000") *
                  Decimal(str(model_config.pricing_input)))

    output_cost = (Decimal(str(output_tokens)) / Decimal("1000000") *
                   Decimal(str(model_config.pricing_output)))

    # Thinking tokens are billed as output tokens
    thinking_cost = (Decimal(str(thinking_tokens)) / Decimal("1000000") *
                     Decimal(str(model_config.pricing_output)))

    # Cache costs
    cache_read_cost = Decimal("0")
    cache_creation_cost = Decimal("0")

    if model_config.pricing_cache_read and cache_read_tokens > 0:
        cache_read_cost = (Decimal(str(cache_read_tokens)) /
                           Decimal("1000000") *
                           Decimal(str(model_config.pricing_cache_read)))

    if model_config.pricing_cache_write_5m and cache_creation_tokens > 0:
        cache_creation_cost = (
            Decimal(str(cache_creation_tokens)) / Decimal("1000000") *
            Decimal(str(model_config.pricing_cache_write_5m)))

    total = (input_cost + output_cost + thinking_cost + cache_read_cost +
             cache_creation_cost)

    return total


# =============================================================================
# Web Search Pricing
# =============================================================================

# Anthropic web search: $10 per 1000 requests
WEB_SEARCH_COST_PER_REQUEST = Decimal("0.01")


def calculate_web_search_cost(request_count: int) -> Decimal:
    """Calculate web search cost.

    Args:
        request_count: Number of web search requests.

    Returns:
        Cost in USD as Decimal.
    """
    return Decimal(str(request_count)) * WEB_SEARCH_COST_PER_REQUEST


# =============================================================================
# Utility Functions
# =============================================================================


def format_cost(cost: Decimal, precision: int = 6) -> str:
    """Format cost for display.

    Args:
        cost: Cost in USD.
        precision: Decimal places to show.

    Returns:
        Formatted cost string (e.g., "$0.001234").
    """
    return f"${cost:.{precision}f}"


def cost_to_float(cost: Decimal) -> float:
    """Convert Decimal cost to float for JSON serialization.

    Args:
        cost: Cost as Decimal.

    Returns:
        Cost as float.
    """
    return float(cost)
