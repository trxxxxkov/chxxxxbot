"""Model selection keyboard for /model command.

This module creates inline keyboards for selecting LLM models,
displayed as two columns (Anthropic | Google) sorted by tier.

NO __init__.py - use direct import:
    from telegram.keyboards.model_selector import get_model_keyboard
"""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import get_models_by_provider
from config import ModelConfig
from i18n import get_text

# Button styles by pricing tier (top = expensive, bottom = cheap)
# Telegram supports: primary (blue), success (green), danger (red)
TIER_STYLES = ["success", "primary", "primary"]

# Providers that are temporarily disabled (shown in red, click triggers alert)
DISABLED_PROVIDERS: set[str] = {"claude"}


def _short_name(model: ModelConfig) -> str:
    """Strip provider prefix for compact button labels.

    "Claude Opus 4.6" → "Opus 4.6"
    "Gemini 3.1 Pro" → "Gemini 3.1 Pro" (keep as-is)
    """
    name = model.display_name
    if name.startswith("Claude "):
        return name[7:]  # Strip "Claude "
    return name


def get_model_keyboard(current: str) -> InlineKeyboardBuilder:
    """Build inline keyboard for model selection.

    Two columns: Anthropic (left) | Google (right).
    Rows sorted by tier: expensive (top) → cheap (bottom).
    Colors: premium (gold) → success (green) → primary (blue).

    Args:
        current: Current model full_id (e.g., "claude:sonnet").

    Returns:
        InlineKeyboardBuilder with model selection buttons.
    """
    builder = InlineKeyboardBuilder()

    # Get models sorted expensive → cheap (reverse of default order)
    claude_models = list(reversed(get_models_by_provider("claude")))
    google_models = list(reversed(get_models_by_provider("google")))

    # Pair models by tier (both lists should have same length)
    max_rows = max(len(claude_models), len(google_models))

    for i in range(max_rows):
        style = TIER_STYLES[i] if i < len(TIER_STYLES) else "primary"
        buttons = []

        # Left column: Claude
        if i < len(claude_models):
            model = claude_models[i]
            full_id = model.get_full_id()
            mark = "✅ " if full_id == current else ""
            is_disabled = model.provider in DISABLED_PROVIDERS
            buttons.append(
                InlineKeyboardButton(
                    text=f"{mark}{_short_name(model)}",
                    callback_data=(f"model_unavailable:{full_id}"
                                   if is_disabled else f"model:{full_id}"),
                    style=ButtonStyle.DANGER if is_disabled else style,
                ))

        # Right column: Google
        if i < len(google_models):
            model = google_models[i]
            full_id = model.get_full_id()
            mark = "✅ " if full_id == current else ""
            is_disabled = model.provider in DISABLED_PROVIDERS
            buttons.append(
                InlineKeyboardButton(
                    text=f"{mark}{_short_name(model)}",
                    callback_data=(f"model_unavailable:{full_id}"
                                   if is_disabled else f"model:{full_id}"),
                    style=ButtonStyle.DANGER if is_disabled else style,
                ))

        builder.row(*buttons)

    return builder


def format_model_info(model: ModelConfig, lang: str = "en") -> str:
    r"""Format model information for display.

    Args:
        model: ModelConfig to format.
        lang: Language code ('en' or 'ru').

    Returns:
        Formatted string with model details.

    Examples:
        >>> model = get_model("claude:sonnet")
        >>> format_model_info(model)
        'Claude Sonnet 4.6\n\nProvider: claude\nContext: 200,000 tokens...'
    """
    info = f"{model.display_name}\n\n"
    info += get_text("model.info_provider", lang, provider=model.provider)
    info += get_text("model.info_context", lang, context=model.context_window)
    info += get_text("model.info_max_output", lang, max_output=model.max_output)
    info += get_text("model.info_latency", lang, latency=model.latency_tier)

    info += get_text("model.info_pricing", lang)
    info += get_text("model.info_input", lang, price=model.pricing_input)
    info += get_text("model.info_output", lang, price=model.pricing_output)

    if model.pricing_cache_read:
        info += get_text("model.info_cache_read",
                         lang,
                         price=model.pricing_cache_read)

    # Add key capabilities
    key_caps = []
    if model.has_capability("extended_thinking"):
        key_caps.append("Extended Thinking")
    if model.has_capability("vision"):
        key_caps.append("Vision")
    if model.has_capability("effort"):
        key_caps.append("Effort Control")
    if model.has_capability("grounding"):
        key_caps.append("Google Search")
    if model.has_capability("thinking"):
        key_caps.append("Thinking")

    if key_caps:
        info += get_text("model.info_features",
                         lang,
                         features=", ".join(key_caps))

    return info
