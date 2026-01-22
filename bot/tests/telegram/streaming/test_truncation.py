"""Tests for smart truncation manager.

Tests the TruncationManager class which handles Telegram's 4096-char limit
by prioritizing text content over thinking content.
"""

import pytest
from telegram.streaming.truncation import MIN_THINKING_SPACE
from telegram.streaming.truncation import SAFETY_MARGIN_HTML
from telegram.streaming.truncation import TELEGRAM_LIMIT
from telegram.streaming.truncation import TruncationManager

# Use HTML effective limit for backward compatibility in tests
EFFECTIVE_LIMIT = TELEGRAM_LIMIT - SAFETY_MARGIN_HTML


class TestTruncationManager:
    """Tests for TruncationManager class."""

    def test_no_truncation_when_fits(self):
        """Content that fits in limit is returned unchanged."""
        tm = TruncationManager(parse_mode="HTML")
        thinking = "<blockquote expandable>Short thinking</blockquote>"
        text = "Short answer"

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        assert result_thinking == thinking
        assert result_text == text

    def test_text_never_truncated(self):
        """Text content is never truncated, even if very long."""
        tm = TruncationManager(parse_mode="HTML")
        # Create text that takes up most of the limit and thinking that exceeds
        text = "x" * 3500
        thinking = "<blockquote expandable>" + "t" * 1000 + "</blockquote>"
        # Total: 3500 + 1036 = 4536 > 4050 (EFFECTIVE_LIMIT)

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        # Text should be completely unchanged
        assert result_text == text
        # Thinking should be truncated or hidden
        assert len(result_thinking) < len(thinking) or result_thinking == ""

    def test_thinking_truncated_from_beginning(self):
        """Thinking is truncated from beginning, keeping recent content."""
        tm = TruncationManager(parse_mode="HTML")
        # Create content that exceeds EFFECTIVE_LIMIT (4050)
        # thinking = 4500 chars, text = 100 chars, total = 4600 > 4050
        thinking = "old_part_" + "a" * 4480 + "_recent_part"
        text = "x" * 100

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        # Text unchanged
        assert result_text == text
        # Thinking should start with ellipsis
        assert result_thinking.startswith("…")
        # Recent part should be preserved
        assert "_recent_part" in result_thinking
        # Old part should be removed
        assert "old_part_" not in result_thinking

    def test_thinking_hidden_when_no_space(self):
        """Thinking is hidden entirely when text takes up most of limit."""
        tm = TruncationManager(parse_mode="HTML")
        # Create text that leaves less than MIN_THINKING_SPACE (100)
        # Text = EFFECTIVE_LIMIT - 50 = 4000, thinking = 200
        # Total = 4200 > 4050, available for thinking = 4050 - 4000 - overhead < 100
        text = "x" * (EFFECTIVE_LIMIT - 50)
        thinking = "t" * 200

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        # Text unchanged
        assert result_text == text
        # Thinking should be empty (not enough space)
        assert result_thinking == ""

    def test_empty_content_handled(self):
        """Empty content is handled gracefully."""
        tm = TruncationManager(parse_mode="HTML")

        # Both empty
        result_thinking, result_text = tm.truncate_for_display("", "")
        assert result_thinking == ""
        assert result_text == ""

        # Only thinking
        result_thinking, result_text = tm.truncate_for_display("thinking", "")
        assert result_thinking == "thinking"
        assert result_text == ""

        # Only text
        result_thinking, result_text = tm.truncate_for_display("", "text")
        assert result_thinking == ""
        assert result_text == "text"

    def test_calculate_available_space(self):
        """Available space is calculated correctly."""
        tm = TruncationManager(parse_mode="HTML")

        # Short text leaves more space
        assert tm.calculate_available_space(100) == tm.effective_limit - 100

        # Long text leaves less space
        assert tm.calculate_available_space(tm.effective_limit - 50) == 50

        # Very long text results in zero space
        assert tm.calculate_available_space(tm.effective_limit + 100) == 0

    def test_needs_truncation(self):
        """Truncation detection works correctly."""
        tm = TruncationManager(parse_mode="HTML")

        # Under limit - no truncation
        assert not tm.needs_truncation(1000, 2000)

        # At limit - no truncation
        assert not tm.needs_truncation(tm.effective_limit // 2,
                                       tm.effective_limit // 2)

        # Over limit - needs truncation
        assert tm.needs_truncation(tm.effective_limit, 100)

    def test_exact_limit_boundary(self):
        """Content exactly at limit is not truncated."""
        tm = TruncationManager(parse_mode="HTML")
        # Create content exactly at limit
        total_needed = tm.effective_limit
        text_len = 500
        thinking_len = total_needed - text_len

        thinking = "t" * thinking_len
        text = "x" * text_len

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        assert result_thinking == thinking
        assert result_text == text

    def test_one_char_over_limit(self):
        """Content one char over limit is truncated."""
        tm = TruncationManager(parse_mode="HTML")
        # Create content one char over limit
        total_needed = tm.effective_limit + 1
        text_len = 500
        thinking_len = total_needed - text_len

        thinking = "t" * thinking_len
        text = "x" * text_len

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        # Text unchanged
        assert result_text == text
        # Thinking truncated
        assert len(result_thinking) < len(thinking)
        assert result_thinking.startswith("…")

    def test_preserves_thinking_end(self):
        """Truncation keeps the end of thinking (most recent)."""
        tm = TruncationManager(parse_mode="HTML")
        # Create thinking with identifiable end that exceeds limit
        # Total: 18 + 4200 + 11 = 4229 > 4050
        thinking = "old_content_" + "x" * 4200 + "_end_marker"
        text = "Some text response"

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        # End marker should be preserved
        assert "_end_marker" in result_thinking
        # Old content should be removed
        assert "old_content_" not in result_thinking


class TestTruncationManagerMarkdownV2:
    """Tests for TruncationManager with MarkdownV2 mode."""

    def test_md2_no_truncation_when_fits(self):
        """MarkdownV2 content that fits is returned unchanged."""
        tm = TruncationManager(parse_mode="MarkdownV2")
        thinking = "**>Short thinking"
        text = "Short answer"

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        assert result_thinking == thinking
        assert result_text == text

    def test_md2_effective_limit_smaller(self):
        """MarkdownV2 has smaller effective limit due to escaping overhead."""
        tm_html = TruncationManager(parse_mode="HTML")
        tm_md2 = TruncationManager(parse_mode="MarkdownV2")

        # MarkdownV2 should have smaller effective limit
        assert tm_md2.effective_limit < tm_html.effective_limit

    def test_md2_truncates_blockquote(self):
        """MarkdownV2 properly truncates expandable blockquote."""
        tm = TruncationManager(parse_mode="MarkdownV2")
        # Create thinking that exceeds limit
        thinking = "**>old_part_" + "x" * 4100 + "_recent_part"
        text = "Short text"

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        # Text unchanged
        assert result_text == text
        # Thinking should be truncated
        assert len(result_thinking) < len(thinking)
        # Recent part preserved
        assert "_recent_part" in result_thinking
        # Should still start with blockquote marker
        assert result_thinking.startswith("**>")
