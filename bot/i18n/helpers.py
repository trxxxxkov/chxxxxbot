"""I18n helper functions."""

from i18n.messages import MESSAGES
from utils.structured_logging import get_logger

logger = get_logger(__name__)


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


def get_user_lang(
    telegram_language_code: str | None,
    stored_language_code: str | None = None,
) -> str:
    """Get user language with fallback to stored value.

    Telegram may not always send language_code (can be None). This function
    uses stored language_code from DB/cache as fallback when fresh value
    is unavailable.

    Priority:
    1. Fresh telegram_language_code (if not None)
    2. stored_language_code from DB/cache (if not None)
    3. Default to 'en'

    Args:
        telegram_language_code: Fresh IETF language tag from Telegram message.
        stored_language_code: Previously stored language code from DB/cache.

    Returns:
        'ru' for Russian variants, 'en' for everything else.
    """
    # Use fresh value if available
    effective_code = telegram_language_code or stored_language_code

    result = get_lang(effective_code)

    # Log only when using fallback (helps debug language detection issues)
    if telegram_language_code is None and stored_language_code:
        logger.debug(
            "i18n.get_user_lang.fallback",
            telegram_language_code=telegram_language_code,
            stored_language_code=stored_language_code,
            result=result,
        )

    return result


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
