"""Formatting functions for streaming display.

This module provides functions for formatting display blocks into
Telegram-compatible HTML and cleaning up tool markers.
"""

import html
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.streaming.display_manager import DisplayManager

from telegram.streaming.truncation import TruncationManager
from telegram.streaming.types import BlockType
from telegram.streaming.types import DisplayBlock


def escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram parse_mode=HTML.

    Prevents "can't parse entities" errors when Claude response contains
    <, >, & symbols (e.g., in code, math, comparisons).

    Args:
        text: Raw text from Claude.

    Returns:
        HTML-escaped text safe for Telegram.
    """
    return html.escape(text)


def strip_tool_markers(text: str) -> str:
    """Remove tool markers and system messages from final response.

    During streaming, markers like [📄 analyze_pdf] are shown in thinking.
    The final answer should be clean text without these markers.

    Patterns removed:
    - Tool markers: [📄 analyze_pdf], [🐍 execute_python], etc.
    - System messages: [✅ ...], [❌ ...], [🎨 ...], [📤 ...]

    Args:
        text: Response text with possible markers.

    Returns:
        Clean text without tool markers.
    """
    # Pattern matches: newline + [emoji + text] + newline
    # Also handles markers at start/end of text
    # Emojis: 📄 analyze_pdf, 🐍 execute_python, 🎨 generate_image,
    #         🔍 web_search, 🌐 web_fetch, 🖼️ analyze_image, 🎤 transcribe_audio
    #         📤 file sent, ✅/❌ status, 📎 document
    pattern = r'\n?\[(?:📄|🐍|🎨|🔍|📤|✅|❌|🌐|📎|🖼️|🎤)[^\]]*\]\n?'
    cleaned = re.sub(pattern, '\n', text)
    # Clean up multiple newlines
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def format_blocks(blocks: list[DisplayBlock], is_streaming: bool = True) -> str:
    """Format display blocks for Telegram display.

    Structure during streaming:
    - All thinking/tool blocks collected at TOP in one blockquote
    - All text blocks concatenated below

    Final display: only text (thinking filtered out before calling).

    During streaming, applies smart truncation to fit Telegram's 4096 char limit:
    - Text content is NEVER truncated (users see it immediately)
    - Thinking content is truncated from beginning (keeps recent parts)
    - If not enough space for thinking, it's hidden entirely

    Args:
        blocks: List of DisplayBlock objects.
        is_streaming: Whether we're still streaming.

    Returns:
        Formatted HTML string for Telegram.
    """
    thinking_parts: list[str] = []
    text_parts: list[str] = []

    for block in blocks:
        content = block.content
        if not content or not content.strip():
            continue

        escaped = escape_html(content.strip())

        if block.block_type == BlockType.THINKING:
            if is_streaming:
                # Don't add 🧠 prefix to tool markers (they start with [emoji)
                if escaped.startswith("["):
                    thinking_parts.append(escaped)
                else:
                    thinking_parts.append(f"🧠 {escaped}")
        else:  # TEXT block
            text_parts.append(escaped)

    # Build HTML for each section
    # Use expandable blockquote so thinking is collapsed by default
    thinking_html = ""
    if thinking_parts:
        thinking_content = "\n\n".join(thinking_parts)
        thinking_html = f"<blockquote expandable>{thinking_content}</blockquote>"

    text_html = ""
    if text_parts:
        text_html = "\n\n".join(text_parts)

    # Apply smart truncation during streaming to fit Telegram's 4096 char limit
    # Prioritizes text over thinking (text visible, thinking collapsed)
    if is_streaming and (thinking_html or text_html):
        truncator = TruncationManager()
        thinking_html, text_html = truncator.truncate_for_display(
            thinking_html, text_html)

    # Combine sections
    result_parts: list[str] = []
    if thinking_html:
        result_parts.append(thinking_html)
    if text_html:
        result_parts.append(text_html)

    result = "\n\n".join(result_parts) if result_parts else ""
    return re.sub(r'\n{3,}', '\n\n', result)


def format_display(display: "DisplayManager", is_streaming: bool = True) -> str:
    """Format DisplayManager content for Telegram.

    Convenience wrapper around format_blocks that takes DisplayManager.

    Args:
        display: DisplayManager instance.
        is_streaming: Whether we're still streaming.

    Returns:
        Formatted HTML string for Telegram.
    """
    return format_blocks(display.blocks, is_streaming)


def format_final_text(display: "DisplayManager") -> str:
    """Format only text blocks for final message (no thinking).

    Args:
        display: DisplayManager instance.

    Returns:
        Formatted HTML string with tool markers stripped.
    """
    text_blocks = display.get_text_blocks()
    formatted = format_blocks(text_blocks, is_streaming=False)
    return strip_tool_markers(formatted)
