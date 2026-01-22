"""Smart truncation for streaming content.

This module provides TruncationManager for handling Telegram's 4096-char limit
while prioritizing visible text over collapsed thinking blocks.

Supports both MarkdownV2 and HTML parse modes with appropriate
length calculations for each.

NO __init__.py - use direct import:
    from telegram.streaming.truncation import TruncationManager
"""

from typing import Literal

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
            max_text = self._effective_limit - len(ellipsis)
            truncated_text = text_formatted[:max_text] + ellipsis
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
            truncated_content = ellipsis + content[-available_for_content:]
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
        >third line

        Args:
            thinking_md2: MarkdownV2-formatted thinking content.
            text_md2: MarkdownV2-formatted text content.
            text_len: Length of text content.
            ellipsis: Ellipsis character.

        Returns:
            Tuple of (truncated_thinking_md2, text_md2).
        """
        # For MD2, blockquote uses **> prefix
        # Overhead: **> on first line, > on subsequent lines
        overhead = 3 + len(ellipsis)  # "**>" + ellipsis
        available_for_content = self._effective_limit - text_len - overhead

        # If not enough space for meaningful thinking, hide it entirely
        if available_for_content <= MIN_THINKING_SPACE:
            return "", text_md2

        # Check if this is expandable blockquote format
        if thinking_md2.startswith("**>"):
            # Truncate from beginning, keep recent content
            # Take last N characters while preserving structure
            content = thinking_md2[3:]  # Remove "**>" prefix

            if len(content) <= available_for_content:
                # Fits without truncation
                return thinking_md2, text_md2

            # Truncate content from beginning
            truncated_content = ellipsis + content[-available_for_content:]

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

            return "\n".join(result_lines), text_md2

        # Fallback for non-blockquote thinking
        truncated_thinking = ellipsis + thinking_md2[-available_for_content:]
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
