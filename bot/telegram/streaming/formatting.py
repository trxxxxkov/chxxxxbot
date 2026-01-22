"""Formatting functions for streaming display.

This module provides functions for formatting display blocks into
Telegram-compatible markup (MarkdownV2 or HTML) and cleaning up tool markers.

Supports two parse modes:
- MarkdownV2 (default): Native Telegram markdown with full formatting
- HTML: Legacy mode with <blockquote> tags

NO __init__.py - use direct import:
    from telegram.streaming.formatting import format_blocks
"""

import html
import re
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.streaming.display_manager import DisplayManager

from telegram.streaming.markdown_v2 import escape_markdown_v2
from telegram.streaming.markdown_v2 import format_expandable_blockquote_md2
from telegram.streaming.markdown_v2 import render_streaming_safe
from telegram.streaming.truncation import TruncationManager
from telegram.streaming.types import BlockType
from telegram.streaming.types import DisplayBlock

# Type alias for parse mode
ParseMode = Literal["MarkdownV2", "HTML"]

# Default parse mode for new messages
DEFAULT_PARSE_MODE: ParseMode = "MarkdownV2"


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


def format_blocks(blocks: list[DisplayBlock],
                  is_streaming: bool = True,
                  parse_mode: ParseMode = DEFAULT_PARSE_MODE) -> str:
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
        parse_mode: "MarkdownV2" (default) or "HTML".

    Returns:
        Formatted string for Telegram (MarkdownV2 or HTML).
    """
    if parse_mode == "HTML":
        return _format_blocks_html(blocks, is_streaming)
    else:
        return _format_blocks_md2(blocks, is_streaming)


def _format_blocks_html(blocks: list[DisplayBlock], is_streaming: bool) -> str:
    """Format blocks as HTML (legacy mode).

    Args:
        blocks: List of DisplayBlock objects.
        is_streaming: Whether we're still streaming.

    Returns:
        HTML-formatted string for Telegram.
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
        truncator = TruncationManager(parse_mode="HTML")
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


def _format_blocks_md2(blocks: list[DisplayBlock], is_streaming: bool) -> str:
    """Format blocks as MarkdownV2.

    Uses expandable blockquote for thinking (collapsed by default).
    Renders text with proper Markdown formatting and escaping.

    Args:
        blocks: List of DisplayBlock objects.
        is_streaming: Whether we're still streaming.

    Returns:
        MarkdownV2-formatted string for Telegram.
    """
    thinking_parts: list[str] = []
    text_parts: list[str] = []

    for block in blocks:
        content = block.content
        if not content or not content.strip():
            continue

        if block.block_type == BlockType.THINKING:
            if is_streaming:
                # Don't add 🧠 prefix to tool markers (they start with [emoji)
                if content.strip().startswith("["):
                    thinking_parts.append(content.strip())
                else:
                    thinking_parts.append(f"🧠 {content.strip()}")
        else:  # TEXT block
            text_parts.append(content.strip())

    # Format thinking as expandable blockquote (MarkdownV2)
    thinking_md2 = ""
    if thinking_parts:
        thinking_content = "\n\n".join(thinking_parts)
        thinking_md2 = format_expandable_blockquote_md2(thinking_content)

    # Format text with MarkdownV2 rendering
    text_md2 = ""
    if text_parts:
        raw_text = "\n\n".join(text_parts)
        # Render as MarkdownV2 with auto-closing for streaming
        text_md2 = render_streaming_safe(
            raw_text) if is_streaming else render_streaming_safe(raw_text)

    # Apply smart truncation during streaming to fit Telegram's 4096 char limit
    if is_streaming and (thinking_md2 or text_md2):
        truncator = TruncationManager(parse_mode="MarkdownV2")
        thinking_md2, text_md2 = truncator.truncate_for_display(
            thinking_md2, text_md2)

    # Combine sections
    result_parts: list[str] = []
    if thinking_md2:
        result_parts.append(thinking_md2)
    if text_md2:
        result_parts.append(text_md2)

    result = "\n\n".join(result_parts) if result_parts else ""
    return re.sub(r'\n{3,}', '\n\n', result)


def format_display(display: "DisplayManager",
                   is_streaming: bool = True,
                   parse_mode: ParseMode = DEFAULT_PARSE_MODE) -> str:
    """Format DisplayManager content for Telegram.

    Convenience wrapper around format_blocks that takes DisplayManager.

    Args:
        display: DisplayManager instance.
        is_streaming: Whether we're still streaming.
        parse_mode: "MarkdownV2" (default) or "HTML".

    Returns:
        Formatted string for Telegram.
    """
    return format_blocks(display.blocks, is_streaming, parse_mode)


def format_final_text(display: "DisplayManager",
                      parse_mode: ParseMode = DEFAULT_PARSE_MODE) -> str:
    """Format only text blocks for final message (no thinking).

    Args:
        display: DisplayManager instance.
        parse_mode: "MarkdownV2" (default) or "HTML".

    Returns:
        Formatted string with tool markers stripped.
    """
    text_blocks = display.get_text_blocks()
    formatted = format_blocks(text_blocks,
                              is_streaming=False,
                              parse_mode=parse_mode)
    return strip_tool_markers(formatted)
