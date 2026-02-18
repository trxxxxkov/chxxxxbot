"""Model selection keyboard for /model command.

This module creates inline keyboards for selecting LLM models,
grouped by provider with support for future multi-provider setup.

NO __init__.py - use direct import:
    from telegram.keyboards.model_selector import get_model_keyboard
"""

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from config import get_models_by_provider
from config import ModelConfig
from i18n import get_text


def get_model_keyboard(current: str) -> InlineKeyboardBuilder:
    """Build inline keyboard for model selection.

    Creates keyboard grouped by provider (Claude, OpenAI, Google, etc.)
    with current model marked with checkmark.

    Args:
        current: Current model full_id (e.g., "claude:sonnet").

    Returns:
        InlineKeyboardBuilder with model selection buttons.

    Examples:
        >>> keyboard = get_model_keyboard("claude:sonnet")
        >>> keyboard.as_markup()
        # Returns InlineKeyboardMarkup with buttons
    """
    builder = InlineKeyboardBuilder()

    # Claude models section (no header - info is in model display_name)
    claude_models = get_models_by_provider("claude")
    for model in claude_models:
        full_id = model.get_full_id()
        is_current = full_id == current

        # Button text with checkmark for current model
        button_text = f"{'✅ ' if is_current else ''}{model.display_name}"

        # Add pricing info
        button_text += f" (${model.pricing_input}/${model.pricing_output})"

        builder.row(
            InlineKeyboardButton(text=button_text,
                                 callback_data=f"model:{full_id}"))

    # Future: OpenAI section (Phase 3.4)
    # openai_models = get_models_by_provider("openai")
    # if openai_models:
    #     builder.row(
    #         InlineKeyboardButton(text="🔵 OpenAI Models",
    #                              callback_data="noop"))
    #     for model in openai_models:
    #         full_id = model.get_full_id()
    #         is_current = (full_id == current)
    #         button_text = f"{'✅ ' if is_current else ''}{model.display_name}"
    #         button_text += f" (${model.pricing_input}/${model.pricing_output})"
    #         builder.row(
    #             InlineKeyboardButton(text=button_text,
    #                                  callback_data=f"model:{full_id}"))

    # Future: Google section (Phase 3.4)
    # google_models = get_models_by_provider("google")
    # if google_models:
    #     builder.row(
    #         InlineKeyboardButton(text="🔴 Google Models",
    #                              callback_data="noop"))
    #     for model in google_models:
    #         full_id = model.get_full_id()
    #         is_current = (full_id == current)
    #         button_text = f"{'✅ ' if is_current else ''}{model.display_name}"
    #         button_text += f" (${model.pricing_input}/${model.pricing_output})"
    #         builder.row(
    #             InlineKeyboardButton(text=button_text,
    #                                  callback_data=f"model:{full_id}"))

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

    if key_caps:
        info += get_text("model.info_features",
                         lang,
                         features=", ".join(key_caps))

    return info
