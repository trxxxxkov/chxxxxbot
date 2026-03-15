"""Shared constants for streaming and formatting modules.

Single source of truth for Telegram limits, safety margins, and type aliases
used across formatting, truncation, and draft streaming.

NO __init__.py - use direct import:
    from telegram.streaming.constants import TELEGRAM_LIMIT, ParseMode
"""

from typing import Literal

# Type alias for parse mode
ParseMode = Literal["MarkdownV2", "HTML"]

# Default parse mode for new messages
DEFAULT_PARSE_MODE: ParseMode = "MarkdownV2"

# Telegram message character limit
TELEGRAM_LIMIT = 4096

# Safety margin for formatting overhead
# MarkdownV2 needs larger margin due to escaping overhead
SAFETY_MARGIN_HTML = 46
SAFETY_MARGIN_MD2 = 100

# Minimum space to keep for thinking (if less, hide it entirely)
MIN_THINKING_SPACE = 100
