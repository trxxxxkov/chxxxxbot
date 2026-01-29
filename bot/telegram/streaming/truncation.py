"""Smart truncation for streaming content.

This module provides TruncationManager for handling Telegram's 4096-char limit
while prioritizing visible text over collapsed thinking blocks.

Supports both MarkdownV2 and HTML parse modes with appropriate
length calculations for each.

NO __init__.py - use direct import:
    from telegram.streaming.truncation import TruncationManager
"""

from typing import Literal

from telegram.streaming.markdown_v2 import fix_truncated_md2

# Telegram message limit
TELEGRAM_LIMIT = 4096

# Safety margin for formatting overhead
# MarkdownV2 needs larger margin due to escaping overhead
SAFETY_MARGIN_HTML = 46
SAFETY_MARGIN_MD2 = 100  # More margin for escaping overhead

# Minimum space to keep for thinking (if less, hide it entirely)
MIN_THINKING_SPACE = 100

# Type alias for parse mode
ParseMode = Literal["MarkdownV2", "HTML"]


def _safe_truncate_start_md2(content: str, available_chars: int) -> str:
    r"""Safely truncate MarkdownV2 content from the beginning.

    When truncating from the start, we may cut in the middle of an escape
    sequence (e.g., \. becomes just .). This function adjusts the cut point
    to avoid breaking escape sequences.

    Args:
        content: MarkdownV2-formatted content to truncate.
        available_chars: Maximum characters to keep from the end.

    Returns:
        Truncated content (without ellipsis - caller adds it).
    """
    if len(content) <= available_chars:
        return content

    start_idx = len(content) - available_chars

    # Don't cut in the middle of an escape sequence (\x)
    # If the character just before our cut point is a backslash,
    # we need to include it to preserve the escape sequence
    if start_idx > 0 and content[start_idx - 1] == "\\":
        # Check if it's an escaped backslash (\\) or escape sequence (\x)
        # For \\, the first \ escapes the second, so cutting after \\ is OK
        # For \x (where x is special char), we need to include the \
        if start_idx >= 2 and content[start_idx - 2] == "\\":
            # It's \\, safe to cut here (the \\ is complete)
            pass
        else:
            # It's \x, include the backslash
            start_idx -= 1

    return content[start_idx:]


class TruncationManager:
    """Manages smart truncation of streaming content.

    Prioritizes text content over thinking content since:
    - Text is visible to users immediately
    - Thinking is shown in blockquote
    - Users see text first, thinking is supplementary

    Supports both MarkdownV2 and HTML parse modes:
    - HTML: Uses <blockquote expandable> tags
    - MarkdownV2: Uses **> prefix for expandable blockquotes

    Algorithm:
    1. If total fits in limit, return as-is
    2. Calculate available space for thinking after text
    3. If not enough space for meaningful thinking, hide it
    4. Otherwise truncate thinking from beginning (keep recent)

    Example:
        >>> tm = TruncationManager(parse_mode="MarkdownV2")
        >>> thinking, text = tm.truncate_for_display(
        ...     "**>Long thinking content...",
        ...     "Short answer"
        ... )
    """

    def __init__(self, parse_mode: ParseMode = "MarkdownV2") -> None:
        """Initialize truncation manager.

        Args:
            parse_mode: "MarkdownV2" (default) or "HTML".
        """
        self._parse_mode = parse_mode
        self._safety_margin = (SAFETY_MARGIN_MD2 if parse_mode == "MarkdownV2"
                               else SAFETY_MARGIN_HTML)
        self._effective_limit = TELEGRAM_LIMIT - self._safety_margin

    @property
    def effective_limit(self) -> int:
        """Get effective character limit after safety margin."""
        return self._effective_limit

    def truncate_for_display(
        self,
        thinking_formatted: str,
        text_formatted: str,
    ) -> tuple[str, str]:
        """Truncate content to fit Telegram limit.

        Priority: Text > Thinking (users see text, thinking is collapsed).

        Algorithm:
        1. If everything fits, return as-is
        2. If text alone exceeds limit, hide thinking and truncate text
        3. Otherwise, truncate thinking to fit remaining space

        Args:
            thinking_formatted: Formatted thinking content (with blockquote).
            text_formatted: Formatted text content.

        Returns:
            Tuple of (truncated_thinking, truncated_text).

        Examples:
            >>> tm = TruncationManager(parse_mode="MarkdownV2")
            >>> thinking, text = tm.truncate_for_display(
            ...     "**>Long thinking...",
            ...     "Short answer"
            ... )
            >>> # thinking content may be truncated, structure preserved
        """
        ellipsis = "…"
        text_len = len(text_formatted)
        thinking_len = len(thinking_formatted)
        total = text_len + thinking_len

        # If everything fits, return as-is
        if total <= self._effective_limit:
            return thinking_formatted, text_formatted

        # If text alone exceeds limit, hide thinking and truncate text
        if text_len >= self._effective_limit:
            # Truncate from end (user sees beginning during streaming)
            # Reserve space for ellipsis and potential formatting fixes
            fix_safety = 20 if self._parse_mode == "MarkdownV2" else 0
            max_text = self._effective_limit - len(ellipsis) - fix_safety
            truncated_text = text_formatted[:max_text] + ellipsis
            # Fix broken formatting for MarkdownV2
            if self._parse_mode == "MarkdownV2":
                truncated_text = fix_truncated_md2(truncated_text)
            return "", truncated_text

        # Calculate available space for thinking
        if self._parse_mode == "MarkdownV2":
            return self._truncate_thinking_md2(thinking_formatted,
                                               text_formatted, text_len,
                                               ellipsis)
        else:
            return self._truncate_thinking_html(thinking_formatted,
                                                text_formatted, text_len,
                                                ellipsis)

    def _truncate_thinking_html(
        self,
        thinking_html: str,
        text_html: str,
        text_len: int,
        ellipsis: str,
    ) -> tuple[str, str]:
        """Truncate thinking for HTML mode.

        Args:
            thinking_html: HTML-formatted thinking content.
            text_html: HTML-formatted text content.
            text_len: Length of text content.
            ellipsis: Ellipsis character.

        Returns:
            Tuple of (truncated_thinking_html, text_html).
        """
        blockquote_open = "<blockquote expandable>"
        blockquote_close = "</blockquote>"
        tag_overhead = len(blockquote_open) + len(blockquote_close) + len(
            ellipsis)
        available_for_content = self._effective_limit - text_len - tag_overhead

        # If not enough space for meaningful thinking, hide it entirely
        if available_for_content <= MIN_THINKING_SPACE:
            return "", text_html

        # Extract content from blockquote (preserve tags, truncate content)
        # thinking_html format: "<blockquote expandable>content</blockquote>"
        if thinking_html.startswith(blockquote_open) and thinking_html.endswith(
                blockquote_close):
            content = thinking_html[len(blockquote_open):-len(blockquote_close)]
            # Truncate content from beginning (keep recent, most relevant)
            start_idx = len(content) - available_for_content
            truncated_content = ellipsis + content[start_idx:]
            return f"{blockquote_open}{truncated_content}{blockquote_close}", text_html

        # Fallback: truncate raw string (shouldn't happen with proper formatting)
        truncated_thinking = ellipsis + thinking_html[-available_for_content:]
        return truncated_thinking, text_html

    def _truncate_thinking_md2(
        self,
        thinking_md2: str,
        text_md2: str,
        text_len: int,
        ellipsis: str,
    ) -> tuple[str, str]:
        """Truncate thinking for MarkdownV2 mode.

        MarkdownV2 expandable blockquote format:
        **>first line
        >second line
        >third line||

        After truncation, applies fix_truncated_md2() to close any
        unclosed formatting that may have been cut mid-marker.

        Args:
            thinking_md2: MarkdownV2-formatted thinking content.
            text_md2: MarkdownV2-formatted text content.
            text_len: Length of text content.
            ellipsis: Ellipsis character.

        Returns:
            Tuple of (truncated_thinking_md2, text_md2).
        """
        # For MD2, blockquote uses **> prefix and || suffix
        # Overhead: **> on first line, || at end, + ellipsis + safety for fix
        # Extra safety margin for potential formatting closures
        fix_safety = 20
        overhead = 3 + 2 + len(ellipsis) + fix_safety  # "**>" + "||" + fixes
        available_for_content = self._effective_limit - text_len - overhead

        # If not enough space for meaningful thinking, hide it entirely
        if available_for_content <= MIN_THINKING_SPACE:
            return "", text_md2

        # Check if this is expandable blockquote format
        if thinking_md2.startswith("**>"):
            # Remove **> prefix and || suffix for content extraction
            content = thinking_md2[3:]  # Remove "**>" prefix
            if content.endswith("||"):
                content = content[:-2]  # Remove "||" suffix

            if len(content) <= available_for_content:
                # Fits without truncation
                return thinking_md2, text_md2

            # Truncate content from beginning (safely, avoiding broken escapes)
            truncated_content = ellipsis + _safe_truncate_start_md2(
                content, available_for_content)

            # Fix any broken formatting from truncation
            truncated_content = fix_truncated_md2(truncated_content)

            # Ensure proper blockquote structure (each line starts with >)
            lines = truncated_content.split("\n")
            result_lines: list[str] = []
            for i, line in enumerate(lines):
                if i == 0:
                    # First line uses **> (expandable marker)
                    result_lines.append(f"**>{line.lstrip('>')}")
                else:
                    # Other lines use >
                    if not line.startswith(">"):
                        result_lines.append(f">{line}")
                    else:
                        result_lines.append(line)

            # Add || end marker
            return "\n".join(result_lines) + "||", text_md2

        # Fallback for non-blockquote thinking
        truncated_thinking = ellipsis + thinking_md2[-available_for_content:]
        truncated_thinking = fix_truncated_md2(truncated_thinking)
        return truncated_thinking, text_md2

    def calculate_available_space(self, text_length: int) -> int:
        """Calculate how much space is available for thinking.

        Args:
            text_length: Length of text content.

        Returns:
            Available characters for thinking content.
        """
        available = self._effective_limit - text_length
        return max(0, available)

    def needs_truncation(self, thinking_length: int, text_length: int) -> bool:
        """Check if content needs truncation.

        Args:
            thinking_length: Length of thinking content.
            text_length: Length of text content.

        Returns:
            True if total exceeds effective limit.
        """
        return thinking_length + text_length > self._effective_limit

    def should_split(self, thinking_formatted: str, text_length: int) -> bool:
        """Check if message should be split into multiple parts.

        Split is needed when:
        - Text exceeds split threshold
        - Thinking is already empty (fully truncated away)

        This allows gradual thinking truncation before resorting to splitting.

        Args:
            thinking_formatted: Current thinking (empty string if truncated away).
            text_length: Length of text content.

        Returns:
            True if message should be split.
        """
        # Only split if thinking is already gone and text is large
        return not thinking_formatted and text_length >= self._effective_limit
