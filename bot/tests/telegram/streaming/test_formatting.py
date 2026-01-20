"""Tests for streaming formatting functions."""

import pytest
from telegram.streaming.display_manager import DisplayManager
from telegram.streaming.formatting import escape_html
from telegram.streaming.formatting import format_blocks
from telegram.streaming.formatting import format_display
from telegram.streaming.formatting import format_final_text
from telegram.streaming.formatting import strip_tool_markers
from telegram.streaming.types import BlockType
from telegram.streaming.types import DisplayBlock


class TestEscapeHtml:
    """Tests for escape_html function."""

    def test_escapes_less_than(self):
        """Should escape < character."""
        assert escape_html("a < b") == "a &lt; b"

    def test_escapes_greater_than(self):
        """Should escape > character."""
        assert escape_html("a > b") == "a &gt; b"

    def test_escapes_ampersand(self):
        """Should escape & character."""
        assert escape_html("a & b") == "a &amp; b"

    def test_escapes_all_special(self):
        """Should escape all HTML special characters."""
        text = "<script>alert('xss')</script>"
        escaped = escape_html(text)
        assert "<" not in escaped
        assert ">" not in escaped


class TestStripToolMarkers:
    """Tests for strip_tool_markers function."""

    def test_strips_tool_marker(self):
        """Should remove tool marker from text."""
        text = "Hello\n[🐍 execute_python]\nWorld"
        result = strip_tool_markers(text)
        assert "[🐍" not in result
        assert "execute_python" not in result

    def test_strips_success_marker(self):
        """Should remove success marker."""
        text = "Test\n[✅ Tool completed]\nDone"
        result = strip_tool_markers(text)
        assert "[✅" not in result

    def test_strips_error_marker(self):
        """Should remove error marker."""
        text = "Test\n[❌ Tool failed]\nDone"
        result = strip_tool_markers(text)
        assert "[❌" not in result

    def test_strips_multiple_markers(self):
        """Should remove multiple markers."""
        text = "[🎨 generate_image]\nImage\n[📄 analyze_pdf]\nDone"
        result = strip_tool_markers(text)
        assert "[🎨" not in result
        assert "[📄" not in result

    def test_preserves_regular_brackets(self):
        """Should preserve regular brackets."""
        text = "This [text] has [normal] brackets"
        result = strip_tool_markers(text)
        assert "[text]" in result
        assert "[normal]" in result

    def test_cleans_multiple_newlines(self):
        """Should clean up multiple consecutive newlines."""
        text = "Line1\n\n\n\nLine2"
        result = strip_tool_markers(text)
        assert "\n\n\n" not in result


class TestFormatBlocks:
    """Tests for format_blocks function."""

    def test_formats_text_block(self):
        """Should format text block."""
        blocks = [DisplayBlock(block_type=BlockType.TEXT, content="Hello")]
        result = format_blocks(blocks, is_streaming=True)
        assert "Hello" in result

    def test_formats_thinking_with_emoji(self):
        """Should add brain emoji to thinking during streaming."""
        blocks = [DisplayBlock(block_type=BlockType.THINKING, content="test")]
        result = format_blocks(blocks, is_streaming=True)
        assert "🧠" in result
        assert "<blockquote expandable>" in result

    def test_no_emoji_for_tool_markers(self):
        """Should not add emoji to tool markers (they start with [)."""
        blocks = [
            DisplayBlock(block_type=BlockType.THINKING,
                         content="[🐍 execute_python]")
        ]
        result = format_blocks(blocks, is_streaming=True)
        # Should have only one emoji (the tool emoji), not 🧠
        assert result.count("🧠") == 0

    def test_escapes_html(self):
        """Should escape HTML in content."""
        blocks = [DisplayBlock(block_type=BlockType.TEXT, content="<script>")]
        result = format_blocks(blocks, is_streaming=True)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_thinking_at_top(self):
        """Thinking should appear at top in blockquote."""
        blocks = [
            DisplayBlock(block_type=BlockType.TEXT, content="text"),
            DisplayBlock(block_type=BlockType.THINKING, content="think"),
        ]
        result = format_blocks(blocks, is_streaming=True)
        thinking_pos = result.find("think")
        text_pos = result.find("text")
        assert thinking_pos < text_pos

    def test_empty_blocks(self):
        """Should handle empty blocks."""
        blocks = [DisplayBlock(block_type=BlockType.TEXT, content="")]
        result = format_blocks(blocks, is_streaming=True)
        assert result == ""


class TestFormatDisplay:
    """Tests for format_display function."""

    def test_formats_display_manager(self):
        """Should format DisplayManager content."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "Hello world")

        result = format_display(dm, is_streaming=True)
        assert "Hello world" in result

    def test_includes_thinking_when_streaming(self):
        """Should include thinking during streaming."""
        dm = DisplayManager()
        dm.append(BlockType.THINKING, "Let me think")
        dm.append(BlockType.TEXT, "Answer")

        result = format_display(dm, is_streaming=True)
        assert "think" in result
        assert "Answer" in result


class TestFormatFinalText:
    """Tests for format_final_text function."""

    def test_only_text_blocks(self):
        """Should include only text blocks."""
        dm = DisplayManager()
        dm.append(BlockType.THINKING, "thinking")
        dm.append(BlockType.TEXT, "answer")

        result = format_final_text(dm)
        assert "thinking" not in result
        assert "answer" in result

    def test_strips_markers(self):
        """Should strip tool markers from final text."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "Hello\n[🐍 execute_python]\nWorld")

        result = format_final_text(dm)
        assert "[🐍" not in result
