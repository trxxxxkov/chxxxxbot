"""Smart truncation for streaming content.

This module provides TruncationManager for handling Telegram's 4096-char limit
while prioritizing visible text over collapsed thinking blocks.

NO __init__.py - use direct import:
    from telegram.streaming.truncation import TruncationManager
"""

# Telegram message limit
TELEGRAM_LIMIT = 4096

# Safety margin for formatting overhead
SAFETY_MARGIN = 46

# Effective limit after safety margin
EFFECTIVE_LIMIT = TELEGRAM_LIMIT - SAFETY_MARGIN  # 4050

# Minimum space to keep for thinking (if less, hide it entirely)
MIN_THINKING_SPACE = 100

# Threshold for splitting messages
# When text exceeds this and thinking is empty, split into new message
SPLIT_THRESHOLD = EFFECTIVE_LIMIT  # 4050


class TruncationManager:
    """Manages smart truncation of streaming content.

    Prioritizes text content over thinking content since:
    - Text is visible to users immediately
    - Thinking is shown in blockquote
    - Users see text first, thinking is supplementary

    Algorithm:
    1. If total fits in limit, return as-is
    2. Calculate available space for thinking after text
    3. If not enough space for meaningful thinking, hide it
    4. Otherwise truncate thinking from beginning (keep recent)
    """

    def truncate_for_display(
        self,
        thinking_html: str,
        text_html: str,
    ) -> tuple[str, str]:
        """Truncate content to fit Telegram limit.

        Priority: Text > Thinking (users see text, thinking is collapsed).

        Algorithm:
        1. If everything fits, return as-is
        2. If text alone exceeds limit, hide thinking and truncate text
        3. Otherwise, truncate thinking to fit remaining space

        Args:
            thinking_html: HTML-formatted thinking content (with blockquote tags).
            text_html: HTML-formatted text content (escaped, no HTML tags).

        Returns:
            Tuple of (truncated_thinking_html, truncated_text_html).

        Examples:
            >>> tm = TruncationManager()
            >>> thinking, text = tm.truncate_for_display(
            ...     "<blockquote expandable>long thinking...</blockquote>",
            ...     "Short answer"
            ... )
            >>> # thinking content may be truncated, tags preserved
        """
        ellipsis = "…"
        text_len = len(text_html)
        thinking_len = len(thinking_html)
        total = text_len + thinking_len

        # If everything fits, return as-is
        if total <= EFFECTIVE_LIMIT:
            return thinking_html, text_html

        # If text alone exceeds limit, hide thinking and truncate text
        # text_html has no HTML tags (only escaped content), safe to truncate
        if text_len >= EFFECTIVE_LIMIT:
            # Truncate from end (user sees beginning during streaming)
            max_text = EFFECTIVE_LIMIT - len(ellipsis)
            truncated_text = text_html[:max_text] + ellipsis
            return "", truncated_text

        # Calculate available space for thinking after reserving for text
        # Also reserve space for truncation indicator and blockquote tags
        blockquote_open = "<blockquote expandable>"
        blockquote_close = "</blockquote>"
        tag_overhead = len(blockquote_open) + len(blockquote_close) + len(
            ellipsis)
        available_for_content = EFFECTIVE_LIMIT - text_len - tag_overhead

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

    def calculate_available_space(self, text_length: int) -> int:
        """Calculate how much space is available for thinking.

        Args:
            text_length: Length of text content.

        Returns:
            Available characters for thinking content.
        """
        available = EFFECTIVE_LIMIT - text_length
        return max(0, available)

    def needs_truncation(self, thinking_length: int, text_length: int) -> bool:
        """Check if content needs truncation.

        Args:
            thinking_length: Length of thinking content.
            text_length: Length of text content.

        Returns:
            True if total exceeds effective limit.
        """
        return thinking_length + text_length > EFFECTIVE_LIMIT

    def should_split(self, thinking_html: str, text_length: int) -> bool:
        """Check if message should be split into multiple parts.

        Split is needed when:
        - Text exceeds SPLIT_THRESHOLD
        - Thinking is already empty (fully truncated away)

        This allows gradual thinking truncation before resorting to splitting.

        Args:
            thinking_html: Current thinking HTML (empty string if truncated away).
            text_length: Length of text content.

        Returns:
            True if message should be split.
        """
        # Only split if thinking is already gone and text is large
        return not thinking_html and text_length >= SPLIT_THRESHOLD
