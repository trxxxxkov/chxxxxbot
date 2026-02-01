"""I18n helper functions."""

from i18n.messages import MESSAGES


def get_lang(language_code: str | None) -> str:
    """Return 'ru' if Russian, otherwise 'en'.

    Args:
        language_code: IETF language tag from Telegram (e.g., "en", "ru", "ru-RU").

    Returns:
        'ru' for Russian variants, 'en' for everything else.
    """
    if language_code and language_code.startswith("ru"):
        return "ru"
    return "en"


def get_text(key: str, lang: str, **kwargs) -> str:
    """Get translated text by key with placeholder substitution.

    Args:
        key: Message key (e.g., "balance.insufficient").
        lang: Language code ('en' or 'ru').
        **kwargs: Placeholder values for .format().

    Returns:
        Translated and formatted string. Falls back to English if key missing.
    """
    messages = MESSAGES.get(key, {})
    text = messages.get(lang) or messages.get("en", f"[Missing: {key}]")
    if kwargs:
        text = text.format(**kwargs)
    return text
