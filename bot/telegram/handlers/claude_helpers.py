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


def compose_system_prompt(global_prompt: str, custom_prompt: str | None,
                          files_context: str | None) -> str:
    """Compose system prompt from 3 levels (legacy single-string version).

    DEPRECATED: Use compose_system_prompt_blocks() for optimal caching.

    Args:
        global_prompt: Base system prompt (same for all users).
        custom_prompt: User's personal instructions (or None).
        files_context: List of files in thread (or None).

    Returns:
        Composed system prompt with all parts joined by double newlines.
    """
    parts = [global_prompt]

    if custom_prompt:
        parts.append(custom_prompt)

    if files_context:
        parts.append(files_context)

    return "\n\n".join(parts)


def compose_system_prompt_blocks(
    global_prompt: str,
    custom_prompt: str | None,
    files_context: str | None,
) -> list[dict]:
    """Compose system prompt as separate blocks for optimal caching.

    Multi-block caching strategy:
    - GLOBAL_SYSTEM_PROMPT: cached (same for all users, ~8K tokens)
    - User.custom_prompt: cached (rarely changes per user)
    - Thread.files_context: NOT cached (changes per request)

    This allows Anthropic to cache static parts while dynamic parts
    (files list) can change without invalidating the cache.

    Args:
        global_prompt: Base system prompt (same for all users).
        custom_prompt: User's personal instructions (or None).
        files_context: List of files in thread (or None).

    Returns:
        List of system prompt blocks for Anthropic API.
        Each block has: {"type": "text", "text": "...", "cache_control"?: {...}}
    """
    blocks = []

    # Block 1: GLOBAL_SYSTEM_PROMPT - always cached (≥1024 tokens)
    blocks.append({
        "type": "text",
        "text": global_prompt,
        "cache_control": {
            "type": "ephemeral"
        }
    })

    # Block 2: User custom prompt - cached if ≥1024 tokens
    if custom_prompt:
        estimated_tokens = len(custom_prompt) // 4
        if estimated_tokens >= 1024:
            blocks.append({
                "type": "text",
                "text": custom_prompt,
                "cache_control": {
                    "type": "ephemeral"
                }
            })
        else:
            blocks.append({"type": "text", "text": custom_prompt})

    # Block 3: Files context - NEVER cached (dynamic per request)
    if files_context:
        blocks.append({"type": "text", "text": files_context})

    return blocks
