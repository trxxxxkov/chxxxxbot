"""Provider factory for LLM providers.

Manages lazy singleton creation of LLM providers based on model config.

NO __init__.py - use direct import:
    from core.provider_factory import get_provider, init_providers
"""

from core.base import LLMProvider
from core.exceptions import InvalidModelError
from core.secrets import read_secret
from config import get_model
from utils.structured_logging import get_logger

logger = get_logger(__name__)

_providers: dict[str, LLMProvider] = {}

# Within-provider degradation chain for graceful 503/timeout fallback.
# Google Pro preview endpoints are intentionally excluded from normal routing:
# live smoke tests showed persistent 503/504/ReadTimeout. The working 3.x chain
# starts with the strongest reliable model and degrades to cheaper siblings.
_FALLBACK_CHAIN: dict[str, str] = {
    "google:pro": "google:flash",
    "google:flash": "google:flash-lite",
    "google:flash-lite": "google:flash-lite-preview",
    "claude:opus": "claude:sonnet",
    "claude:sonnet": "claude:haiku",
}


def get_provider(model_full_id: str) -> LLMProvider:
    """Get or create provider for model. Lazy singleton per provider type.

    Args:
        model_full_id: Full model ID like "claude:sonnet" or "google:flash".

    Returns:
        LLMProvider instance for the model's provider.

    Raises:
        InvalidModelError: If provider is unknown.
    """
    model_config = get_model(model_full_id)
    provider_name = model_config.provider

    if provider_name not in _providers:
        if provider_name == "claude":
            from core.claude.client import ClaudeProvider  # pylint: disable=import-outside-toplevel
            api_key = read_secret("anthropic_api_key")
            _providers["claude"] = ClaudeProvider(api_key=api_key)
            logger.info("provider_factory.created", provider="claude")
        elif provider_name == "google":
            from core.google.client import GeminiProvider  # pylint: disable=import-outside-toplevel
            _providers["google"] = GeminiProvider()
            logger.info("provider_factory.created", provider="google")
        else:
            raise InvalidModelError(f"Unknown provider: {provider_name}")

    return _providers[provider_name]


def init_providers() -> None:
    """Pre-initialize default provider (Google). Others initialized lazily."""
    get_provider("google:flash-lite")


def clear_providers() -> None:
    """Clear all cached providers. Useful for testing."""
    _providers.clear()


def get_fallback_model(model_full_id: str) -> str | None:
    """Return the next-cheaper model in the same provider, or None.

    Used by the message handler to transparently degrade on transient
    capacity errors (503 UNAVAILABLE on overloaded preview models).
    Same-provider chain keeps message format, tools, and pricing
    semantics consistent — no cross-provider format conversion needed.

    Args:
        model_full_id: Full model ID like "google:pro" or "claude:opus".

    Returns:
        Fallback model ID, or None if at the end of the chain.
    """
    return _FALLBACK_CHAIN.get(model_full_id)
