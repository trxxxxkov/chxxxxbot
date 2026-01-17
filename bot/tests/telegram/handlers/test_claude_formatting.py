"""Tests for Claude handler formatting functions.

Tests for:
- format_thinking_display(): Thinking block formatting
- _strip_html(): HTML fallback stripping
- strip_tool_markers(): Remove tool markers from final response
- get_tool_system_message(): Tool execution system messages (from registry)
- _update_telegram_message_formatted(): Message update with fallback
"""

from core.tools.registry import get_tool_system_message
import pytest
from telegram.handlers.claude import _strip_html
from telegram.handlers.claude import format_interleaved_content
from telegram.handlers.claude import format_thinking_display
from telegram.handlers.claude import strip_tool_markers


class TestFormatThinkingDisplay:
    """Tests for format_thinking_display function."""

    def test_thinking_only_streaming(self):
        """Test display with only thinking text during streaming."""
        result = format_thinking_display(
            thinking_text="I need to analyze this...",
            response_text="",
            is_streaming=True)
        assert "🧠" in result
        assert "<i>" in result
        assert "I need to analyze this..." in result
        assert "blockquote" not in result

    def test_thinking_only_final(self):
        """Test display with only thinking text in final mode."""
        result = format_thinking_display(
            thinking_text="I need to analyze this...",
            response_text="",
            is_streaming=False)
        assert "🧠" in result
        assert "<blockquote expandable>" in result
        assert "</blockquote>" in result
        assert "<i>" not in result

    def test_thinking_and_response_streaming(self):
        """Test display with thinking and response during streaming."""
        result = format_thinking_display(thinking_text="Let me think...",
                                         response_text="Here is the answer.",
                                         is_streaming=True)
        assert "🧠" in result
        assert "<i>" in result
        assert "Let me think..." in result
        assert "Here is the answer." in result
        # Parts should be separated
        assert "\n\n" in result

    def test_thinking_and_response_final(self):
        """Test display with thinking and response in final mode."""
        result = format_thinking_display(thinking_text="Let me think...",
                                         response_text="Here is the answer.",
                                         is_streaming=False)
        assert "<blockquote expandable>" in result
        assert "Let me think..." in result
        assert "Here is the answer." in result

    def test_response_only(self):
        """Test display with only response text."""
        result = format_thinking_display(thinking_text="",
                                         response_text="Here is the answer.",
                                         is_streaming=True)
        assert "🧠" not in result
        assert "<i>" not in result
        assert "Here is the answer." in result

    def test_empty_inputs(self):
        """Test display with empty inputs."""
        result = format_thinking_display(thinking_text="",
                                         response_text="",
                                         is_streaming=True)
        assert result == ""

    def test_html_escaping_in_thinking(self):
        """Test that HTML characters are escaped in thinking text."""
        result = format_thinking_display(
            thinking_text="Check if x < y && y > z",
            response_text="",
            is_streaming=True)
        assert "&lt;" in result  # < escaped
        assert "&gt;" in result  # > escaped
        assert "&amp;" in result  # & escaped

    def test_html_escaping_in_response(self):
        """Test that HTML characters are escaped in response text."""
        result = format_thinking_display(
            thinking_text="",
            response_text="Use <code> for code & > for greater",
            is_streaming=True)
        assert "&lt;code&gt;" in result
        assert "&amp;" in result


class TestFormatInterleavedContent:
    """Tests for format_interleaved_content function."""

    def test_thinking_then_text(self):
        """Test thinking followed by text preserves order."""
        blocks = [
            {
                "type": "thinking",
                "content": "Let me think..."
            },
            {
                "type": "text",
                "content": "Here is my answer."
            },
        ]
        result = format_interleaved_content(blocks, is_streaming=True)
        thinking_pos = result.find("🧠")
        answer_pos = result.find("Here is my answer")
        assert thinking_pos < answer_pos

    def test_text_then_thinking_then_text(self):
        """Test interleaved blocks preserve order."""
        blocks = [
            {
                "type": "text",
                "content": "First text."
            },
            {
                "type": "thinking",
                "content": "Now thinking..."
            },
            {
                "type": "text",
                "content": "Second text."
            },
        ]
        result = format_interleaved_content(blocks, is_streaming=True)
        first_pos = result.find("First text")
        thinking_pos = result.find("🧠")
        second_pos = result.find("Second text")
        assert first_pos < thinking_pos < second_pos

    def test_streaming_uses_italics(self):
        """Test streaming mode uses italics for thinking."""
        blocks = [{"type": "thinking", "content": "Thinking..."}]
        result = format_interleaved_content(blocks, is_streaming=True)
        assert "<i>" in result
        assert "</i>" in result
        assert "blockquote" not in result

    def test_final_uses_blockquote(self):
        """Test final mode uses blockquote for thinking."""
        blocks = [{"type": "thinking", "content": "Thinking..."}]
        result = format_interleaved_content(blocks, is_streaming=False)
        assert "<blockquote" in result
        assert "</blockquote>" in result
        assert "<i>" not in result

    def test_empty_blocks(self):
        """Test empty blocks list returns empty string."""
        result = format_interleaved_content([], is_streaming=True)
        assert result == ""

    def test_empty_content_skipped(self):
        """Test blocks with empty content are skipped."""
        blocks = [
            {
                "type": "thinking",
                "content": ""
            },
            {
                "type": "text",
                "content": "Only text."
            },
        ]
        result = format_interleaved_content(blocks, is_streaming=True)
        assert "🧠" not in result
        assert "Only text" in result

    def test_whitespace_only_content_skipped(self):
        """Test blocks with whitespace-only content are skipped."""
        blocks = [
            {
                "type": "text",
                "content": "   \n\n  "
            },
            {
                "type": "text",
                "content": "Real text."
            },
        ]
        result = format_interleaved_content(blocks, is_streaming=True)
        assert result == "Real text."

    def test_no_triple_newlines(self):
        """Test that content with surrounding newlines doesn't create triple newlines."""
        blocks = [
            {
                "type": "text",
                "content": "First."
            },
            {
                "type": "text",
                "content": "\n\n[tool marker]\n\n"
            },
            {
                "type": "text",
                "content": "Second."
            },
        ]
        result = format_interleaved_content(blocks, is_streaming=True)
        # Should have at most double newlines between parts
        assert "\n\n\n" not in result
        assert "First." in result
        assert "[tool marker]" in result
        assert "Second." in result


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


class TestStripToolMarkers:
    """Tests for strip_tool_markers function."""

    def test_strip_tool_marker_analyze_pdf(self):
        """Test stripping analyze_pdf marker."""
        text = "Here is my analysis:\n[📄 analyze_pdf]\nThe document contains..."
        result = strip_tool_markers(text)
        assert "[📄" not in result
        assert "Here is my analysis:" in result
        assert "The document contains..." in result

    def test_strip_tool_marker_execute_python(self):
        """Test stripping execute_python marker."""
        text = "Let me run this code:\n[🐍 execute_python]\nThe result is 42."
        result = strip_tool_markers(text)
        assert "[🐍" not in result
        assert "Let me run this code:" in result
        assert "The result is 42." in result

    def test_strip_system_message_success(self):
        """Test stripping success system message."""
        text = "Done!\n[✅ Код выполнен: output]\nHere is the result."
        result = strip_tool_markers(text)
        assert "[✅" not in result
        assert "Done!" in result
        assert "Here is the result." in result

    def test_strip_system_message_error(self):
        """Test stripping error system message."""
        text = "Trying:\n[❌ Ошибка выполнения: error]\nLet me fix this."
        result = strip_tool_markers(text)
        assert "[❌" not in result

    def test_strip_file_sent_marker(self):
        """Test stripping file sent marker."""
        text = "Generated image:\n[📤 Отправлен файл: image.png]\nHere it is."
        result = strip_tool_markers(text)
        assert "[📤" not in result
        assert "Generated image:" in result

    def test_strip_multiple_markers(self):
        """Test stripping multiple markers."""
        text = ("First step:\n[📄 analyze_pdf]\n"
                "Analysis complete.\n[✅ Анализ выполнен]\n"
                "Now searching:\n[🔍 web_search]\n"
                "Found results.")
        result = strip_tool_markers(text)
        assert "[📄" not in result
        assert "[✅" not in result
        assert "[🔍" not in result
        assert "First step:" in result
        assert "Analysis complete." in result
        assert "Found results." in result

    def test_no_markers(self):
        """Test text without any markers."""
        text = "This is plain text without any tool markers."
        result = strip_tool_markers(text)
        assert result == text

    def test_empty_input(self):
        """Test with empty input."""
        result = strip_tool_markers("")
        assert result == ""

    def test_cleans_multiple_newlines(self):
        """Test that multiple newlines are reduced."""
        text = "Before\n[📄 tool]\n\n\n\nAfter"
        result = strip_tool_markers(text)
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in result

    def test_strip_tool_marker_analyze_image(self):
        """Test stripping analyze_image marker (🖼️)."""
        text = "Let me analyze this image:\n[🖼️ analyze_image]\nI see a cat."
        result = strip_tool_markers(text)
        assert "[🖼️" not in result
        assert "Let me analyze this image:" in result
        assert "I see a cat." in result

    def test_strip_tool_marker_transcribe_audio(self):
        """Test stripping transcribe_audio marker (🎤)."""
        text = "Transcribing audio:\n[🎤 transcribe_audio]\nThe speaker says..."
        result = strip_tool_markers(text)
        assert "[🎤" not in result
        assert "Transcribing audio:" in result
        assert "The speaker says..." in result

    def test_strip_tool_marker_generate_image(self):
        """Test stripping generate_image marker (🎨)."""
        text = "Generating image:\n[🎨 generate_image]\nHere's your image."
        result = strip_tool_markers(text)
        assert "[🎨" not in result
        assert "Generating image:" in result
        assert "Here's your image." in result

    def test_strip_tool_marker_web_fetch(self):
        """Test stripping web_fetch marker (🌐)."""
        text = "Fetching webpage:\n[🌐 web_fetch]\nThe page contains..."
        result = strip_tool_markers(text)
        assert "[🌐" not in result
        assert "Fetching webpage:" in result
        assert "The page contains..." in result

    def test_strip_all_tool_markers_combined(self):
        """Test stripping all possible tool markers in one text.

        This is a regression test for the bug where 🖼️ and 🎤 markers
        were not being stripped from final user messages.
        """
        text = (
            "Starting analysis:\n"
            "[🖼️ analyze_image]\n"  # Was missing from pattern
            "Image analyzed.\n"
            "[📄 analyze_pdf]\n"
            "PDF analyzed.\n"
            "[🎤 transcribe_audio]\n"  # Was missing from pattern
            "Audio transcribed.\n"
            "[🎨 generate_image]\n"
            "Image generated.\n"
            "[🐍 execute_python]\n"
            "Code executed.\n"
            "[🔍 web_search]\n"
            "Search done.\n"
            "[🌐 web_fetch]\n"
            "Page fetched.\n"
            "[📤 Отправлен файл: result.png]\n"
            "File sent.\n"
            "[✅ Success]\n"
            "[❌ Error]\n"
            "All done.")
        result = strip_tool_markers(text)
        # All markers should be stripped
        assert "[🖼️" not in result
        assert "[📄" not in result
        assert "[🎤" not in result
        assert "[🎨" not in result
        assert "[🐍" not in result
        assert "[🔍" not in result
        assert "[🌐" not in result
        assert "[📤" not in result
        assert "[✅" not in result
        assert "[❌" not in result
        # Content should be preserved
        assert "Starting analysis:" in result
        assert "Image analyzed." in result
        assert "PDF analyzed." in result
        assert "Audio transcribed." in result
        assert "All done." in result


class TestGetToolSystemMessage:
    """Tests for get_tool_system_message function."""

    def test_execute_python_success_with_output(self):
        """Test execute_python success with stdout output."""
        result = get_tool_system_message(tool_name="execute_python",
                                         tool_input={"code": "print('hello')"},
                                         result={
                                             "success": "true",
                                             "stdout": "hello world",
                                             "stderr": ""
                                         })
        assert "✅" in result
        assert "Код выполнен" in result
        assert "hello world" in result

    def test_execute_python_success_no_output(self):
        """Test execute_python success without stdout output."""
        result = get_tool_system_message(tool_name="execute_python",
                                         tool_input={"code": "x = 1"},
                                         result={
                                             "success": "true",
                                             "stdout": "",
                                             "stderr": ""
                                         })
        assert "✅" in result
        assert "успешно" in result

    def test_execute_python_success_long_output_truncated(self):
        """Test execute_python truncates long output."""
        long_output = "x" * 200
        result = get_tool_system_message(
            tool_name="execute_python",
            tool_input={"code": "print('x' * 200)"},
            result={
                "success": "true",
                "stdout": long_output,
                "stderr": ""
            })
        assert "..." in result
        assert len(result) < 200  # Should be truncated

    def test_execute_python_failure(self):
        """Test execute_python failure message."""
        result = get_tool_system_message(
            tool_name="execute_python",
            tool_input={"code": "raise Error"},
            result={
                "success": "false",
                "error": "NameError: name 'Error' not defined"
            })
        assert "❌" in result
        assert "Ошибка" in result
        assert "NameError" in result

    def test_transcribe_audio(self):
        """Test transcribe_audio system message."""
        result = get_tool_system_message(tool_name="transcribe_audio",
                                         tool_input={"file_id": "abc123"},
                                         result={
                                             "transcript": "Hello",
                                             "duration": 15.5,
                                             "language": "en"
                                         })
        assert "🎤" in result
        assert "Транскрибировано" in result
        assert "15s" in result or "16s" in result  # Rounded
        assert "en" in result

    def test_transcribe_audio_no_language(self):
        """Test transcribe_audio without detected language."""
        result = get_tool_system_message(tool_name="transcribe_audio",
                                         tool_input={"file_id": "abc123"},
                                         result={
                                             "transcript": "Hello",
                                             "duration": 10.0,
                                             "language": ""
                                         })
        assert "🎤" in result
        assert "10s" in result
        # Should not have extra comma for empty language
        assert ", ," not in result

    def test_generate_image(self):
        """Test generate_image system message."""
        result = get_tool_system_message(tool_name="generate_image",
                                         tool_input={"prompt": "a cat"},
                                         result={
                                             "success": "true",
                                             "parameters_used": {
                                                 "image_size": "4K",
                                                 "aspect_ratio": "16:9"
                                             }
                                         })
        assert "🎨" in result
        assert "Изображение создано" in result
        assert "4K" in result
        assert "16:9" in result

    def test_generate_image_default_params(self):
        """Test generate_image with default parameters."""
        result = get_tool_system_message(tool_name="generate_image",
                                         tool_input={"prompt": "a dog"},
                                         result={
                                             "success": "true",
                                             "parameters_used": {}
                                         })
        assert "🎨" in result
        assert "2K" in result  # Default resolution

    def test_analyze_image_no_message(self):
        """Test analyze_image returns empty string (internal tool)."""
        result = get_tool_system_message(
            tool_name="analyze_image",
            tool_input={"claude_file_id": "file_123"},
            result={"analysis": "This is a cat."})
        assert result == ""

    def test_analyze_pdf_no_message(self):
        """Test analyze_pdf returns empty string (internal tool)."""
        result = get_tool_system_message(
            tool_name="analyze_pdf",
            tool_input={"claude_file_id": "file_456"},
            result={"analysis": "Document content."})
        assert result == ""

    def test_web_search_no_message(self):
        """Test web_search returns empty string (server-side tool)."""
        result = get_tool_system_message(tool_name="web_search",
                                         tool_input={"query": "weather today"},
                                         result={})
        assert result == ""

    def test_unknown_tool_no_message(self):
        """Test unknown tool returns empty string."""
        result = get_tool_system_message(tool_name="unknown_tool",
                                         tool_input={},
                                         result={})
        assert result == ""
