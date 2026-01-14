"""Tests for Claude handler formatting functions.

Tests for:
- format_thinking_display(): Thinking block formatting
- _strip_html(): HTML fallback stripping
- _format_tool_system_message(): Tool execution system messages
- _update_telegram_message_formatted(): Message update with fallback
"""

import pytest
from telegram.handlers.claude import format_thinking_display
from telegram.handlers.claude import _strip_html
from telegram.handlers.claude import _format_tool_system_message


class TestFormatThinkingDisplay:
    """Tests for format_thinking_display function."""

    def test_thinking_only_streaming(self):
        """Test display with only thinking text during streaming."""
        result = format_thinking_display(
            thinking_text="I need to analyze this...",
            response_text="",
            is_streaming=True
        )
        assert "🧠" in result
        assert "<i>" in result
        assert "I need to analyze this..." in result
        assert "blockquote" not in result

    def test_thinking_only_final(self):
        """Test display with only thinking text in final mode."""
        result = format_thinking_display(
            thinking_text="I need to analyze this...",
            response_text="",
            is_streaming=False
        )
        assert "🧠" in result
        assert "<blockquote expandable>" in result
        assert "</blockquote>" in result
        assert "<i>" not in result

    def test_thinking_and_response_streaming(self):
        """Test display with thinking and response during streaming."""
        result = format_thinking_display(
            thinking_text="Let me think...",
            response_text="Here is the answer.",
            is_streaming=True
        )
        assert "🧠" in result
        assert "<i>" in result
        assert "Let me think..." in result
        assert "Here is the answer." in result
        # Parts should be separated
        assert "\n\n" in result

    def test_thinking_and_response_final(self):
        """Test display with thinking and response in final mode."""
        result = format_thinking_display(
            thinking_text="Let me think...",
            response_text="Here is the answer.",
            is_streaming=False
        )
        assert "<blockquote expandable>" in result
        assert "Let me think..." in result
        assert "Here is the answer." in result

    def test_response_only(self):
        """Test display with only response text."""
        result = format_thinking_display(
            thinking_text="",
            response_text="Here is the answer.",
            is_streaming=True
        )
        assert "🧠" not in result
        assert "<i>" not in result
        assert "Here is the answer." in result

    def test_empty_inputs(self):
        """Test display with empty inputs."""
        result = format_thinking_display(
            thinking_text="",
            response_text="",
            is_streaming=True
        )
        assert result == ""

    def test_html_escaping_in_thinking(self):
        """Test that HTML characters are escaped in thinking text."""
        result = format_thinking_display(
            thinking_text="Check if x < y && y > z",
            response_text="",
            is_streaming=True
        )
        assert "&lt;" in result  # < escaped
        assert "&gt;" in result  # > escaped
        assert "&amp;" in result  # & escaped

    def test_html_escaping_in_response(self):
        """Test that HTML characters are escaped in response text."""
        result = format_thinking_display(
            thinking_text="",
            response_text="Use <code> for code & > for greater",
            is_streaming=True
        )
        assert "&lt;code&gt;" in result
        assert "&amp;" in result


class TestStripHtml:
    """Tests for _strip_html fallback function."""

    def test_strip_simple_tags(self):
        """Test stripping simple HTML tags."""
        result = _strip_html("<b>bold</b> text")
        assert result == "bold text"

    def test_strip_nested_tags(self):
        """Test stripping nested HTML tags."""
        result = _strip_html("<div><span>nested</span></div>")
        assert result == "nested"

    def test_strip_blockquote(self):
        """Test stripping blockquote tags."""
        result = _strip_html("<blockquote expandable>quoted text</blockquote>")
        assert result == "quoted text"

    def test_strip_italics(self):
        """Test stripping italic tags."""
        result = _strip_html("<i>italic text</i>")
        assert result == "italic text"

    def test_unescape_entities(self):
        """Test unescaping HTML entities."""
        result = _strip_html("x &lt; y &amp;&amp; y &gt; z")
        assert result == "x < y && y > z"

    def test_mixed_tags_and_entities(self):
        """Test stripping tags and unescaping entities together."""
        result = _strip_html("<i>🧠 x &lt; y</i>")
        assert result == "🧠 x < y"

    def test_empty_input(self):
        """Test with empty input."""
        result = _strip_html("")
        assert result == ""

    def test_no_tags(self):
        """Test with plain text (no tags)."""
        result = _strip_html("plain text here")
        assert result == "plain text here"


class TestFormatToolSystemMessage:
    """Tests for _format_tool_system_message function."""

    def test_execute_python_success_with_output(self):
        """Test execute_python success with stdout output."""
        result = _format_tool_system_message(
            tool_name="execute_python",
            tool_input={"code": "print('hello')"},
            result={"success": "true", "stdout": "hello world", "stderr": ""}
        )
        assert "✅" in result
        assert "Код выполнен" in result
        assert "hello world" in result

    def test_execute_python_success_no_output(self):
        """Test execute_python success without stdout output."""
        result = _format_tool_system_message(
            tool_name="execute_python",
            tool_input={"code": "x = 1"},
            result={"success": "true", "stdout": "", "stderr": ""}
        )
        assert "✅" in result
        assert "успешно" in result

    def test_execute_python_success_long_output_truncated(self):
        """Test execute_python truncates long output."""
        long_output = "x" * 200
        result = _format_tool_system_message(
            tool_name="execute_python",
            tool_input={"code": "print('x' * 200)"},
            result={"success": "true", "stdout": long_output, "stderr": ""}
        )
        assert "..." in result
        assert len(result) < 200  # Should be truncated

    def test_execute_python_failure(self):
        """Test execute_python failure message."""
        result = _format_tool_system_message(
            tool_name="execute_python",
            tool_input={"code": "raise Error"},
            result={"success": "false", "error": "NameError: name 'Error' not defined"}
        )
        assert "❌" in result
        assert "Ошибка" in result
        assert "NameError" in result

    def test_transcribe_audio(self):
        """Test transcribe_audio system message."""
        result = _format_tool_system_message(
            tool_name="transcribe_audio",
            tool_input={"file_id": "abc123"},
            result={"transcript": "Hello", "duration": 15.5, "language": "en"}
        )
        assert "🎤" in result
        assert "Транскрибировано" in result
        assert "15s" in result or "16s" in result  # Rounded
        assert "en" in result

    def test_transcribe_audio_no_language(self):
        """Test transcribe_audio without detected language."""
        result = _format_tool_system_message(
            tool_name="transcribe_audio",
            tool_input={"file_id": "abc123"},
            result={"transcript": "Hello", "duration": 10.0, "language": ""}
        )
        assert "🎤" in result
        assert "10s" in result
        # Should not have extra comma for empty language
        assert ", ," not in result

    def test_generate_image(self):
        """Test generate_image system message."""
        result = _format_tool_system_message(
            tool_name="generate_image",
            tool_input={"prompt": "a cat"},
            result={
                "success": "true",
                "parameters_used": {"output_resolution": "4K", "aspect_ratio": "16:9"}
            }
        )
        assert "🎨" in result
        assert "Изображение создано" in result
        assert "4K" in result
        assert "16:9" in result

    def test_generate_image_default_params(self):
        """Test generate_image with default parameters."""
        result = _format_tool_system_message(
            tool_name="generate_image",
            tool_input={"prompt": "a dog"},
            result={"success": "true", "parameters_used": {}}
        )
        assert "🎨" in result
        assert "2K" in result  # Default resolution

    def test_analyze_image_no_message(self):
        """Test analyze_image returns empty string (internal tool)."""
        result = _format_tool_system_message(
            tool_name="analyze_image",
            tool_input={"claude_file_id": "file_123"},
            result={"analysis": "This is a cat."}
        )
        assert result == ""

    def test_analyze_pdf_no_message(self):
        """Test analyze_pdf returns empty string (internal tool)."""
        result = _format_tool_system_message(
            tool_name="analyze_pdf",
            tool_input={"claude_file_id": "file_456"},
            result={"analysis": "Document content."}
        )
        assert result == ""

    def test_web_search_no_message(self):
        """Test web_search returns empty string (server-side tool)."""
        result = _format_tool_system_message(
            tool_name="web_search",
            tool_input={"query": "weather today"},
            result={}
        )
        assert result == ""

    def test_unknown_tool_no_message(self):
        """Test unknown tool returns empty string."""
        result = _format_tool_system_message(
            tool_name="unknown_tool",
            tool_input={},
            result={}
        )
        assert result == ""
