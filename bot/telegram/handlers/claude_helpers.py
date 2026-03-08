"""Helper utilities for Claude handler.

This module provides utility functions used by the Claude handler:
- split_text_smart: Smart text splitting for Telegram message limits
- compose_system_prompt: 3-level system prompt composition

NO __init__.py - use direct import:
    from telegram.handlers.claude_helpers import split_text_smart
    from telegram.handlers.claude_helpers import compose_system_prompt
"""

from config import MESSAGE_SPLIT_LENGTH
from config import TEXT_SPLIT_LINE_WINDOW
from config import TEXT_SPLIT_PARA_WINDOW


def split_text_smart(text: str,
                     max_length: int = MESSAGE_SPLIT_LENGTH) -> list[str]:
    """Split text into chunks using smart boundaries.

    Uses priority-based splitting:
    1. Paragraph boundaries (double newline) - preserves semantic units
    2. Single newlines - preserves line structure
    3. Hard split at max_length if no better option

    Args:
        text: Text to split.
        max_length: Maximum length per chunk (default: MESSAGE_SPLIT_LENGTH).

    Returns:
        List of text chunks.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_length:
        split_pos = max_length

        # Try paragraph boundary first
        para_pos = remaining.rfind('\n\n', 0, split_pos)
        if para_pos > split_pos - TEXT_SPLIT_PARA_WINDOW and para_pos > 0:
            split_pos = para_pos + 1

        # Fall back to single newline
        elif (newline_pos :=
              remaining.rfind('\n', 0,
                              split_pos)) > split_pos - TEXT_SPLIT_LINE_WINDOW:
            if newline_pos > 0:
                split_pos = newline_pos

        chunks.append(remaining[:split_pos].strip())
        remaining = remaining[split_pos:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def compose_system_prompt(global_prompt: str,
                          custom_prompt: str | None) -> str:
    """Compose system prompt from 2 levels (legacy single-string version).

    DEPRECATED: Use compose_system_prompt_blocks() for optimal caching.

    Args:
        global_prompt: Base system prompt (same for all users).
        custom_prompt: User's personal instructions (or None).

    Returns:
        Composed system prompt with all parts joined by double newlines.
    """
    parts = [global_prompt]

    if custom_prompt:
        parts.append(custom_prompt)

    return "\n\n".join(parts)


def compose_system_prompt_blocks(
    global_prompt: str,
    custom_prompt: str | None,
) -> list[dict]:
    """Compose system prompt as separate blocks for optimal caching.

    All blocks are static and cached:
    - GLOBAL_SYSTEM_PROMPT: cached 1h (same for all users, ~8K tokens)
    - User.custom_prompt: cached 1h (rarely changes per user)

    File context is no longer included here — it moved to the list_files
    tool to keep the system prompt fully static and cache-friendly.

    Args:
        global_prompt: Base system prompt (same for all users).
        custom_prompt: User's personal instructions (or None).

    Returns:
        List of system prompt blocks for Anthropic API.
        Each block has: {"type": "text", "text": "...", "cache_control"?: {...}}
    """
    blocks = []

    # Block 1: GLOBAL_SYSTEM_PROMPT - cached with default 5m TTL
    # System prompt + tools form the stable prefix that gets cached
    # automatically. 5m TTL (1.25x write cost) is cheaper than 1h (2x)
    # and sufficient since active users message within 5 minutes.
    blocks.append({
        "type": "text",
        "text": global_prompt,
        "cache_control": {
            "type": "ephemeral"
        }
    })

    # Block 2: User custom prompt - cached if ≥256 tokens (~1024 chars)
    if custom_prompt:
        estimated_tokens = len(custom_prompt) // 4
        if estimated_tokens >= 256:
            blocks.append({
                "type": "text",
                "text": custom_prompt,
                "cache_control": {
                    "type": "ephemeral"
                }
            })
        else:
            blocks.append({"type": "text", "text": custom_prompt})

    return blocks


def compose_system_prompt_for_provider(
    provider: str,
    global_prompt: str,
    custom_prompt: str | None,
) -> str | list[dict]:
    """Provider-aware system prompt composition.

    Claude uses multi-block format with cache_control markers.
    Other providers use simple string concatenation + current date
    (Claude gets the date from Anthropic's API automatically).

    Args:
        provider: Provider name ("claude", "google", etc.).
        global_prompt: Base system prompt (same for all users).
        custom_prompt: User's personal instructions (or None).

    Returns:
        List of blocks for Claude, plain string for other providers.
    """
    if provider == "claude":
        return compose_system_prompt_blocks(global_prompt, custom_prompt)

    # Non-Claude providers: add current date context
    from datetime import datetime, timezone  # pylint: disable=import-outside-toplevel
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_context = f"Current date: {today}."

    parts = [global_prompt, date_context]
    if custom_prompt:
        parts.append(custom_prompt)
    return "\n\n".join(parts)
