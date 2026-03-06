"""Tests for claude_helpers module.

Tests helper functions for Claude handler including text splitting
and system prompt composition.
"""

from telegram.handlers.claude_helpers import compose_system_prompt
from telegram.handlers.claude_helpers import compose_system_prompt_blocks
from telegram.handlers.claude_helpers import split_text_smart


class TestSplitTextSmart:
    """Tests for split_text_smart function."""

    def test_short_text_no_split(self):
        """Test short text returns as single chunk."""
        text = "Short text"
        result = split_text_smart(text, max_length=100)

        assert len(result) == 1
        assert result[0] == "Short text"

    def test_split_at_paragraph_boundary(self):
        """Test splitting prefers paragraph boundaries."""
        text = "First paragraph.\n\nSecond paragraph."
        result = split_text_smart(text, max_length=25)

        assert len(result) == 2
        assert "First paragraph" in result[0]
        assert "Second paragraph" in result[1]

    def test_split_at_line_boundary(self):
        """Test falls back to line boundaries."""
        text = "Line one.\nLine two.\nLine three."
        result = split_text_smart(text, max_length=20)

        assert len(result) >= 2


class TestComposeSystemPrompt:
    """Tests for legacy compose_system_prompt function."""

    def test_global_only(self):
        """Test with only global prompt."""
        result = compose_system_prompt(
            global_prompt="Global instructions",
            custom_prompt=None,
        )

        assert result == "Global instructions"

    def test_with_custom_prompt(self):
        """Test with global and custom prompt."""
        result = compose_system_prompt(
            global_prompt="Global",
            custom_prompt="Custom user preferences",
        )

        assert "Global" in result
        assert "Custom user preferences" in result
        assert "\n\n" in result


class TestComposeSystemPromptBlocks:
    """Tests for multi-block compose_system_prompt_blocks function."""

    def test_global_only_cached(self):
        """Test global prompt is cached."""
        result = compose_system_prompt_blocks(
            global_prompt="Global instructions " * 500,
            custom_prompt=None,
        )

        assert len(result) == 1
        assert result[0]["type"] == "text"
        assert "cache_control" in result[0]
        assert result[0]["cache_control"]["type"] == "ephemeral"

    def test_custom_prompt_large_cached(self):
        """Test large custom prompt is cached (>=256 tokens)."""
        result = compose_system_prompt_blocks(
            global_prompt="Global " * 500,
            custom_prompt="Custom " * 200,  # ~1400 chars = 350 tokens
        )

        assert len(result) == 2
        assert "cache_control" in result[0]  # Global cached
        assert "cache_control" in result[1]  # Custom cached (>=256 tokens)

    def test_custom_prompt_small_not_cached(self):
        """Test small custom prompt is NOT cached (<256 tokens)."""
        result = compose_system_prompt_blocks(
            global_prompt="Global " * 500,
            custom_prompt="Small custom",
        )

        assert len(result) == 2
        assert "cache_control" in result[0]  # Global cached
        assert "cache_control" not in result[1]  # Custom NOT cached (small)

    def test_two_level_composition(self):
        """Test both levels with proper caching."""
        result = compose_system_prompt_blocks(
            global_prompt="Global " * 500,
            custom_prompt="Custom preferences",
        )

        assert len(result) == 2
        assert "cache_control" in result[0]  # Global cached
        assert "cache_control" not in result[1]  # Custom small, not cached

    def test_block_content_preserved(self):
        """Test text content is preserved in blocks."""
        result = compose_system_prompt_blocks(
            global_prompt="GLOBAL_TEXT",
            custom_prompt="CUSTOM_TEXT",
        )

        texts = [block["text"] for block in result]
        assert "GLOBAL_TEXT" in texts
        assert "CUSTOM_TEXT" in texts
