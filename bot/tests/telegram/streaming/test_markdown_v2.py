"""Tests for MarkdownV2 rendering module.

Parametrized tests for efficient coverage of escape and formatting logic.
"""

import pytest
from telegram.streaming.markdown_v2 import calculate_escaped_length
from telegram.streaming.markdown_v2 import convert_standard_markdown
from telegram.streaming.markdown_v2 import escape_markdown_v2
from telegram.streaming.markdown_v2 import EscapeContext
from telegram.streaming.markdown_v2 import format_blockquote_md2
from telegram.streaming.markdown_v2 import format_expandable_blockquote_md2
from telegram.streaming.markdown_v2 import MarkdownV2Renderer
from telegram.streaming.markdown_v2 import preprocess_unsupported_markdown
from telegram.streaming.markdown_v2 import render_streaming_safe


class TestEscapeMarkdownV2:
    """Tests for escape_markdown_v2 function."""

    @pytest.mark.parametrize(
        "input_text,expected",
        [
            # Basic special character escaping
            ("1+1=2", r"1\+1\=2"),
            ("test_var", r"test\_var"),
            ("a*b", r"a\*b"),
            ("[text](url)", r"\[text\]\(url\)"),
            ("~text~", r"\~text\~"),
            ("`code`", r"\`code\`"),
            (">quote", r"\>quote"),
            ("#heading", r"\#heading"),
            ("a+b-c=d", r"a\+b\-c\=d"),
            ("|text|", r"\|text\|"),
            ("{key}", r"\{key\}"),
            ("file.txt", r"file\.txt"),
            ("Hello!", r"Hello\!"),
            # Edge cases
            ("", ""),
            ("Hello World", "Hello World"),
            ("++--==", r"\+\+\-\-\=\="),
            ("*_[]()~`>#+-=|{}.!", r"\*\_\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!"),
            ("  spaces  ", "  spaces  "),
        ])
    def test_escapes_special_chars(self, input_text, expected):
        """Should escape MarkdownV2 special characters correctly."""
        result = escape_markdown_v2(input_text)
        assert result == expected


class TestEscapeContexts:
    """Tests for context-aware escaping."""

    @pytest.mark.parametrize(
        "input_text,context,expected",
        [
            # CODE context - only escapes ` and \
            ("1+1=2", EscapeContext.CODE, "1+1=2"),
            (r"print(`code`)", EscapeContext.CODE, r"print(\`code\`)"),
            (r"path\to\file", EscapeContext.CODE, r"path\\to\\file"),
            # URL context - only escapes ) and \
            ("https://example.com/path?q=1+1", EscapeContext.URL,
             "https://example.com/path?q=1+1"),
            ("https://example.com/path)", EscapeContext.URL,
             r"https://example.com/path\)"),
            # PRE context - no escaping
            ("_*[]()~`>#+-=|{}.!", EscapeContext.PRE, "_*[]()~`>#+-=|{}.!"),
        ])
    def test_context_aware_escaping(self, input_text, context, expected):
        """Should escape based on context rules."""
        result = escape_markdown_v2(input_text, context)
        assert result == expected


class TestMarkdownV2Renderer:
    """Tests for MarkdownV2Renderer class."""

    def test_renderer_append_and_render(self):
        """Should accumulate text and render."""
        renderer = MarkdownV2Renderer()
        renderer.append("Hello ")
        renderer.append("World")
        result = renderer.render()
        assert "Hello World" in result

    def test_renderer_clear(self):
        """Should clear accumulated text."""
        renderer = MarkdownV2Renderer()
        renderer.append("Hello")
        renderer.clear()
        result = renderer.render()
        assert result == ""

    def test_renderer_raw_length(self):
        """Should return raw text length."""
        renderer = MarkdownV2Renderer()
        renderer.append("Hello")
        assert renderer.get_raw_length() == 5

    def test_renderer_escaped_length(self):
        """Should estimate escaped length."""
        renderer = MarkdownV2Renderer()
        renderer.append("1+1=2")  # 2 special chars: + and =
        # Escaped: 1\+1\=2 = 7 chars (5 raw + 2 escapes)
        assert renderer.get_escaped_length() >= 7


class TestRenderStreamingSafe:
    """Tests for render_streaming_safe function."""

    @pytest.mark.parametrize(
        "input_text,assertion",
        [
            # Auto-closing tests
            ("Here's **bold te", lambda r: r.endswith("*") or "*bold te*" in r),
            ("Here's _italic te", lambda r: "_" in r),
            ("Here's `code", lambda r: r.endswith("`")),
            ("```python\nprint('hello'", lambda r: r.endswith("```")),
            # Nested formatting
            ("**bold _italic", lambda r: "*" in r and "_" in r),
            # Complete formatting preserved
            ("**bold** text", lambda r: "*bold*" in r or "*bold\\*" in r),
            # Special chars escaped
            ("1+1=2", lambda r: "+" not in r or r"\+" in r),
            # Empty and unicode
            ("", lambda r: r == ""),
            ("Emoji: 🚀 and text", lambda r: "🚀" in r),
            ("Line 1\n\nLine 2", lambda r: "\n\n" in r),
        ])
    def test_streaming_safe_rendering(self, input_text, assertion):
        """Should render streaming-safe MarkdownV2."""
        result = render_streaming_safe(input_text)
        assert assertion(result)


class TestConvertStandardMarkdown:
    """Tests for convert_standard_markdown function."""

    @pytest.mark.parametrize(
        "input_text,check",
        [
            # Bold conversion
            ("**bold text**",
             lambda r: "*bold text*" in r and "**" not in r.replace("\\*", "")),
            # Strikethrough conversion
            ("~~strikethrough~~", lambda r: "~strikethrough~" in r and "~~"
             not in r.replace("\\~", "")),
            # Code block preservation
            ("```python\n1+1=2\n```", lambda r: "1+1=2" in r),
            # Special char escaping
            ("Use file.txt please", lambda r: r"\." in r),
        ])
    def test_converts_standard_markdown(self, input_text, check):
        """Should convert standard Markdown to MarkdownV2."""
        result = convert_standard_markdown(input_text)
        assert check(result)


class TestFormatBlockquotes:
    """Tests for blockquote formatting functions."""

    @pytest.mark.parametrize(
        "input_text,func,checks",
        [
            # Expandable blockquote
            ("Single line", format_expandable_blockquote_md2,
             [lambda r: r.startswith("**>"), lambda r: "Single line" in r]),
            ("Line 1\nLine 2\nLine 3", format_expandable_blockquote_md2, [
                lambda r: r.split("\n")[0].startswith("**>"),
                lambda r: r.split("\n")[1].startswith(">"),
                lambda r: r.split("\n")[2].startswith(">"),
            ]),
            ("1+1=2", format_expandable_blockquote_md2,
             [lambda r: r"\+" in r, lambda r: r"\=" in r]),
            ("", format_expandable_blockquote_md2, [lambda r: r == ""]),
            # Regular blockquote
            ("Single line", format_blockquote_md2, [
                lambda r: r.startswith(">"),
                lambda r: "Single line" in r,
            ]),
            ("Line 1\nLine 2", format_blockquote_md2,
             [lambda r: all(line.startswith(">") for line in r.split("\n"))]),
            ("", format_blockquote_md2, [lambda r: r == ""]),
        ])
    def test_blockquote_formatting(self, input_text, func, checks):
        """Should format blockquotes correctly."""
        result = func(input_text)
        for check in checks:
            assert check(result)


class TestCalculateEscapedLength:
    """Tests for calculate_escaped_length function."""

    @pytest.mark.parametrize(
        "input_text,context,expected",
        [
            # Normal context
            ("1+1=2", None, 7),  # "1\+1\=2" = 7 chars
            ("Hello World", None, 11),  # No escaping needed
            # Code context
            ("1+1=2", EscapeContext.CODE, 5),  # No escaping in code
        ])
    def test_escaped_length_calculation(self, input_text, context, expected):
        """Should calculate escaped length correctly."""
        if context is None:
            result = calculate_escaped_length(input_text)
        else:
            result = calculate_escaped_length(input_text, context)
        assert result == expected


class TestMarkdownV2Integration:
    """Integration tests for MarkdownV2 rendering."""

    def test_streaming_with_partial_bold(self):
        """Should handle partial bold during streaming."""
        renderer = MarkdownV2Renderer()
        renderer.append("Hello **bold")
        result1 = renderer.render(auto_close=True)
        assert result1.endswith("*")

        renderer.clear()
        renderer.append("Hello **bold** world")
        result2 = renderer.render(auto_close=True)
        assert "*bold*" in result2 or "*bold\\*" in result2

    def test_streaming_with_code_block(self):
        """Should handle incomplete code block during streaming."""
        renderer = MarkdownV2Renderer()
        renderer.append("```python\nprint('hello'")
        result = renderer.render(auto_close=True)
        assert result.endswith("```")

    def test_link_formatting(self):
        """Should handle link formatting."""
        result = render_streaming_safe("[Google](https://google.com)")
        assert "[Google]" in result
        assert "(https://google.com)" in result

    def test_mixed_formatting(self):
        """Should handle mixed formatting types."""
        text = "Normal **bold** and `code` and _italic_"
        result = render_streaming_safe(text)
        assert "*" in result  # Bold marker
        assert "`" in result  # Code marker
        assert "_" in result  # Italic marker

    def test_complex_math_expression(self):
        """Should escape math expressions properly."""
        result = render_streaming_safe("Calculate: (a+b)*(c-d)=result")
        assert r"\+" in result
        assert r"\*" in result
        assert r"\-" in result
        assert r"\=" in result

    def test_nested_formatting_recovery(self):
        """Should recover from malformed nested formatting."""
        text = "*bold _text*"
        result = render_streaming_safe(text)
        assert result is not None


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_backslash_handling(self):
        """Should handle backslashes correctly."""
        result = escape_markdown_v2("path\\file")
        assert "path" in result
        assert "file" in result

    def test_very_long_text(self):
        """Should handle very long text."""
        long_text = "Hello World. " * 1000
        result = render_streaming_safe(long_text)
        assert len(result) > len(long_text)  # Due to escaping

    def test_tabs_handling(self):
        """Should preserve tabs."""
        result = escape_markdown_v2("col1\tcol2")
        assert "\t" in result


class TestLongMessageHandling:
    """Tests for handling messages near or exceeding Telegram's 4096 char limit."""

    def test_long_text_escaping_increases_length(self):
        """Text with many special chars can exceed limit after escaping."""
        raw_text = "1+1=2. " * 500  # 3500 raw chars
        result = render_streaming_safe(raw_text)
        assert len(result) > len(raw_text)
        assert r"\+" in result
        assert r"\=" in result
        assert r"\." in result

    def test_long_text_with_formatting_preserved(self):
        """Long text with formatting should preserve structure."""
        text = "**Bold start** " + "x" * 3000 + " **bold end**"
        result = render_streaming_safe(text)
        assert "*Bold start*" in result or "*Bold start\\*" in result
        assert "*bold end*" in result or "*bold end\\*" in result

    def test_long_code_block_preserved(self):
        """Long code blocks should be preserved without internal escaping."""
        code_content = "var x = 1+1; // 2\n" * 200
        text = f"```javascript\n{code_content}```"
        result = render_streaming_safe(text)
        assert "1+1" in result
        assert "// 2" in result
        assert result.startswith("```javascript")
        assert result.rstrip().endswith("```")

    def test_long_text_auto_closes_unclosed_formatting(self):
        """Very long text with unclosed formatting should auto-close."""
        text = "**Bold text " + "x" * 4000
        result = render_streaming_safe(text)
        assert result.endswith("*")
        star_count = result.count("*") - result.count(r"\*")
        assert star_count >= 2

    def test_long_text_with_nested_formatting(self):
        """Long text with nested formatting handles correctly."""
        text = "**Bold _and italic " + "word " * 800 + "end_**"
        result = render_streaming_safe(text)
        assert "*" in result  # Bold
        assert "_" in result  # Italic

    def test_very_long_single_word(self):
        """Single very long word without spaces."""
        long_word = "a" * 5000
        result = render_streaming_safe(long_word)
        assert len(result) == 5000

    def test_long_text_with_many_urls(self):
        """Long text with many URLs should preserve URL structure."""
        url = "[Link](https://example.com/path?q=1+1)"
        text = (url + " text ") * 100
        result = render_streaming_safe(text)
        assert "[Link]" in result
        assert "https://example.com" in result


class TestMessageSplittingEdgeCases:
    """Tests for edge cases when messages need splitting."""

    def test_truncation_at_escape_sequence(self):
        """Truncation shouldn't break in the middle of escape sequence."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        text = "x" * 3990 + r"1\+1\=2"
        thinking = "**>" + "t" * 200

        result_thinking, result_text = tm.truncate_for_display(thinking, text)
        if result_text:
            assert not result_text.rstrip().endswith("\\") or \
                   result_text.rstrip().endswith("\\\\")

    def test_truncation_preserves_valid_markdown(self):
        """Truncated text should still be valid MarkdownV2."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        text = "*Bold* " * 500
        thinking = "**>" + "t" * 100

        result_thinking, result_text = tm.truncate_for_display(thinking, text)
        if result_text:
            import re
            unescaped_stars = len(re.findall(r'(?<!\\)\*', result_text))
            assert unescaped_stars % 2 == 0 or result_text.endswith("…")

    def test_thinking_truncation_keeps_recent_content(self):
        """When thinking is truncated, recent content is preserved."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        thinking = "**>OLD_PART_" + "x" * 4000 + "_RECENT_END"
        text = "Short answer"

        result_thinking, result_text = tm.truncate_for_display(thinking, text)
        assert "_RECENT_END" in result_thinking
        assert "OLD_PART_" not in result_thinking
        assert result_thinking.startswith("**>")

    def test_text_exceeding_limit_hides_thinking(self):
        """When text exceeds limit, thinking is hidden entirely."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        text = "x" * 4000
        thinking = "**>" + "t" * 500

        result_thinking, result_text = tm.truncate_for_display(thinking, text)
        assert result_thinking == ""
        assert result_text.endswith("…")

    def test_multiline_blockquote_truncation(self):
        """Multi-line blockquote truncation preserves structure."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        thinking = "**>Line 1\n>Line 2\n>Line 3\n>" + "x" * 4000 + "\n>Final line"
        text = "Answer"

        result_thinking, result_text = tm.truncate_for_display(thinking, text)
        if result_thinking:
            assert result_thinking.startswith("**>")
            lines = result_thinking.split("\n")
            for i, line in enumerate(lines[1:], 1):
                if line:
                    assert line.startswith(
                        ">"), f"Line {i} doesn't start with >: {line}"


class TestFormattingEdgeCases:
    """Additional edge cases for formatting."""

    @pytest.mark.parametrize(
        "input_text,check",
        [
            # Empty markers
            ("Text ** here", lambda r: "Text" in r and "here" in r),
            ("Text __ here", lambda r: "Text" in r and "here" in r),
            # Single delimiter at end
            ("Text ends with *", lambda r: r"\*" in r or r.endswith("*")),
            # Delimiters surrounded by spaces
            ("a * b * c", lambda r: r.count(r"\*") >= 2 or "a * b * c" not in r
            ),
            # Code with backticks inside
            ("Use `echo \\`date\\`` for time", lambda r: "`" in r),
        ])
    def test_formatting_edge_cases(self, input_text, check):
        """Should handle formatting edge cases."""
        result = render_streaming_safe(input_text)
        assert check(result)

    def test_nested_code_blocks(self):
        """Nested code block markers handled correctly."""
        text = "```\nUse ``` for code blocks\n```"
        result = render_streaming_safe(text)
        assert "```" in result

    def test_link_with_special_chars_in_text(self):
        """Link text with special chars should be escaped."""
        result = render_streaming_safe("[Click (here)!](https://example.com)")
        assert "[" in result
        assert "](" in result
        assert "Click" in result

    def test_link_with_parentheses_in_url(self):
        """URL with parentheses should escape them properly."""
        result = render_streaming_safe(
            "[Wiki](https://en.wikipedia.org/wiki/Python_(programming_language))"
        )
        assert "wikipedia.org" in result

    def test_mixed_formatting_and_code(self):
        """Mixed formatting and code in same text."""
        text = "**Bold** then `code with + and =` then _italic_"
        result = render_streaming_safe(text)
        assert "*Bold*" in result or "*Bold\\*" in result
        assert "`code with + and =`" in result
        assert "_italic_" in result

    def test_strikethrough_conversion(self):
        """Double tilde converted to single tilde."""
        result = render_streaming_safe("~~strikethrough~~")
        assert "~strikethrough~" in result
        assert "~~" not in result.replace(r"\~", "")

    def test_spoiler_markers(self):
        """Spoiler markers should work."""
        result = render_streaming_safe("This is ||spoiler|| text")
        assert "||spoiler||" in result

    def test_underline_vs_italic(self):
        """Double underscore is underline, single is italic."""
        result = render_streaming_safe("__underline__ and _italic_")
        assert "__underline__" in result
        assert "_italic_" in result

    def test_blockquote_at_line_start(self):
        """Blockquote markers at line start."""
        result = escape_markdown_v2(">quoted text")
        assert r"\>" in result

    def test_multiple_paragraphs_with_formatting(self):
        """Multiple paragraphs with different formatting."""
        text = "**Bold para**\n\n_Italic para_\n\n`Code para`"
        result = render_streaming_safe(text)
        assert "*Bold para*" in result or "*Bold para\\*" in result
        assert "_Italic para_" in result
        assert "`Code para`" in result
        assert "\n\n" in result


class TestExpandableBlockquoteEdgeCases:
    """Edge cases for expandable blockquote formatting."""

    def test_blockquote_with_special_chars(self):
        """Blockquote content with special chars should be escaped."""
        result = format_expandable_blockquote_md2("1+1=2")
        assert "**>" in result
        assert r"\+" in result
        assert r"\=" in result

    def test_blockquote_with_newlines(self):
        """Multi-line blockquote formatting."""
        result = format_expandable_blockquote_md2("Line 1\nLine 2\nLine 3")
        lines = result.split("\n")
        assert lines[0].startswith("**>")
        assert all(line.startswith(">") for line in lines[1:])

    def test_blockquote_preserves_empty_lines(self):
        """Empty lines in blockquote should be handled."""
        result = format_expandable_blockquote_md2("Para 1\n\nPara 2")
        lines = result.split("\n")
        assert len(lines) == 3
        assert lines[1] == ">"

    def test_blockquote_with_code(self):
        """Blockquote containing code markers."""
        result = format_expandable_blockquote_md2("Use `code` here")
        assert "**>" in result
        assert "`code`" in result

    def test_blockquote_auto_closes_unclosed_formatting(self):
        """Unclosed formatting in blockquote should be auto-closed."""
        # Unclosed bold
        result = format_expandable_blockquote_md2("Starting *bold text")
        assert "**>" in result
        assert result.endswith("||")
        assert result.count("*") >= 2

        # Unclosed code block
        result = format_expandable_blockquote_md2(
            "Code: ```python\nprint('hi')")
        assert "```" in result
        assert result.count("```") >= 2

        # Unclosed inline code
        result = format_expandable_blockquote_md2("Variable `foo should close")
        assert result.count("`") >= 2

    def test_blockquote_with_markdown_syntax(self):
        """Blockquote should properly convert standard Markdown to MarkdownV2."""
        result = format_expandable_blockquote_md2("This is **bold** text")
        assert "**>" in result
        assert "*bold*" in result

    def test_very_long_single_line_blockquote(self):
        """Very long single line blockquote."""
        long_content = "x" * 5000
        result = format_expandable_blockquote_md2(long_content)
        assert result.startswith("**>")
        assert len(result) > 5000

    def test_blockquote_with_emoji(self):
        """Blockquote with emoji content."""
        result = format_expandable_blockquote_md2("🧠 Thinking about 🚀")
        assert "**>" in result
        assert "🧠" in result
        assert "🚀" in result


class TestStreamingScenarios:
    """Tests simulating real streaming scenarios."""

    def test_incremental_text_building(self):
        """Simulates incremental text building during streaming."""
        renderer = MarkdownV2Renderer()
        chunks = ["Hello ", "**world", "**! ", "This is `code", "` here."]

        for i, chunk in enumerate(chunks):
            renderer.append(chunk)
            result = renderer.render(auto_close=True)
            assert result is not None
            if i == 1:  # After "**world" - unclosed bold
                assert result.endswith("*")
            if i == 3:  # After "`code" - unclosed code
                assert result.endswith("`")

    def test_streaming_with_tool_markers(self):
        """Streaming with tool markers in thinking."""
        from telegram.streaming.formatting import format_blocks
        from telegram.streaming.types import BlockType
        from telegram.streaming.types import DisplayBlock

        blocks = [
            DisplayBlock(BlockType.THINKING, "[🐍 execute_python]"),
            DisplayBlock(BlockType.THINKING, "\n[✅ Tool completed]"),
            DisplayBlock(BlockType.TEXT, "Result: 1+1=2"),
        ]

        result = format_blocks(blocks,
                               is_streaming=True,
                               parse_mode="MarkdownV2")
        assert "**>" in result
        assert "🐍" in result
        assert r"\+" in result or "1+1=2" not in result

    def test_streaming_very_long_response(self):
        """Streaming a very long response with mixed content."""
        from telegram.streaming.formatting import format_blocks
        from telegram.streaming.types import BlockType
        from telegram.streaming.types import DisplayBlock

        thinking_content = "🧠 " + "Analysis step. " * 200
        text_content = "Here's my answer: " + "word " * 500

        blocks = [
            DisplayBlock(BlockType.THINKING, thinking_content),
            DisplayBlock(BlockType.TEXT, text_content),
        ]

        result = format_blocks(blocks,
                               is_streaming=True,
                               parse_mode="MarkdownV2")
        assert result is not None

    def test_code_block_streaming(self):
        """Streaming code block character by character."""
        renderer = MarkdownV2Renderer()
        code = "```python\nprint('hello')\n```"

        for i, char in enumerate(code):
            renderer.append(char)
            result = renderer.render(auto_close=True)
            assert result is not None
            if "```python" in renderer._raw_text and "```" not in renderer._raw_text[
                    10:]:
                assert result.rstrip().endswith("```")

    def test_rapid_format_switching(self):
        """Rapid switching between formatting types."""
        text = "*b*_i_*b*_i_`c`*b*_i_" * 100
        result = render_streaming_safe(text)
        assert result is not None
        assert result.count("`") % 2 == 0


class TestRegressionCases:
    """Regression tests for potential bugs."""

    @pytest.mark.parametrize(
        "input_text,check",
        [
            # Backslash before special char
            (r"\*", lambda r: r is not None),
            # URL with query params
            ("[Link](https://example.com?a=1&b=2)",
             lambda r: "https://example.com" in r),
            # Math expression
            ("Solve: x² + 2x + 1 = 0", lambda r: r"\+" in r and r"\=" in r),
            # File path
            ("See file: /path/to/file.txt", lambda r: r"\." in r),
            # Telegram username
            ("Contact @username for help", lambda r: "@username" in r),
            # Hashtag
            ("Use #hashtag for topics", lambda r: r"\#" in r),
            # HTML entities
            ("Use &amp; for ampersand", lambda r: "&" in r),
            # Shell command with pipes
            ("Run: ls | grep test", lambda r: r"\|" in r),
            # Bullet list
            ("List:\n- Item 1\n- Item 2", lambda r: r"\-" in r),
        ])
    def test_regression_cases(self, input_text, check):
        """Regression tests for various edge cases."""
        result = render_streaming_safe(input_text)
        assert check(result)

    def test_markdown_in_quotes_escaped(self):
        """Markdown-like text in quotes should be escaped when using escape_markdown_v2."""
        # User is talking about markdown, not using it
        result = escape_markdown_v2('Use "**bold**" for emphasis')
        # ** should be escaped (not interpreted)
        assert r"\*\*" in result

    def test_json_in_code_block(self):
        """JSON in code block should not be escaped."""
        json_code = '```json\n{"key": "value", "num": 1+1}\n```'
        result = render_streaming_safe(json_code)
        assert '"key"' in result
        assert "1+1" in result

    def test_single_tilde_not_strikethrough(self):
        """Single ~ should be escaped, not treated as strikethrough."""
        result = render_streaming_safe("Cost: ~$0.006/minute")
        assert r"\~" in result
        assert result.count("~") == 1

        result2 = render_streaming_safe("Approximately ~100 items remaining")
        assert r"\~" in result2
        assert result2.count("~") == 1

        # Double tilde SHOULD still work as strikethrough
        result3 = render_streaming_safe("This is ~~struck~~ text")
        assert "~struck~" in result3

    def test_tilde_in_technical_content(self):
        """Tilde in technical content should be escaped."""
        result = render_streaming_safe("Path: ~/Documents/file.txt")
        assert r"\~" in result

        result2 = render_streaming_safe("Latency: ~10ms for fast queries")
        assert r"\~" in result2


class TestPreprocessUnsupportedMarkdown:
    """Tests for preprocess_unsupported_markdown function."""

    @pytest.mark.parametrize("input_text,expected_check", [
        ("", lambda r: r == ""),
        ("This is plain text without special features.",
         lambda r: r == "This is plain text without special features."),
        (r"The formula \(x^2\) is simple",
         lambda r: r == "The formula `x^2` is simple"),
        ("The formula $x^2$ is simple",
         lambda r: r == "The formula `x^2` is simple"),
        (r"Formula: \[x^2 + y^2 = z^2\]",
         lambda r: "```" in r and "x^2 + y^2 = z^2" in r),
        ("Formula: $$x^2 + y^2$$", lambda r: "```" in r and "x^2 + y^2" in r),
        ("# Main Title", lambda r: r == "**Main Title**"),
        ("## Subtitle", lambda r: r == "**Subtitle**"),
        ("### Section", lambda r: r == "**Section**"),
        ("# Title\nSome text\n## Subtitle\nMore text",
         lambda r: "**Title**" in r and "**Subtitle**" in r and "Some text" in r
        ),
        ("Use the # symbol for comments", lambda r: "**" not in r),
        (r"\( x + y \)", lambda r: r == "`x + y`"),
        (r"Variables \(x\) and \(y\) are used",
         lambda r: r == "Variables `x` and `y` are used"),
    ])
    def test_preprocess_unsupported_markdown(self, input_text, expected_check):
        """Should preprocess unsupported markdown correctly."""
        result = preprocess_unsupported_markdown(input_text)
        assert expected_check(result)

    def test_complex_latex_formula(self):
        """Should handle complex LaTeX formulas."""
        text = r"Taylor series: \[f(x) = \sum_{n=0}^{\infty} \frac{f^{(n)}(a)}{n!}(x-a)^n\]"
        result = preprocess_unsupported_markdown(text)
        assert "```" in result
        assert "sum" in result
        assert "frac" in result

    def test_mixed_latex_and_headers(self):
        """Should handle text with both LaTeX and headers."""
        text = "# Math Formula\nThe equation \\(x^2\\) shows..."
        result = preprocess_unsupported_markdown(text)
        assert "**Math Formula**" in result
        assert "`x^2`" in result

    def test_render_after_preprocess(self):
        """Full flow: preprocess then render should produce valid output."""
        text = "# Formula\nThe Taylor series \\(f(x)\\) expands to..."
        result = render_streaming_safe(text)
        assert "*Formula*" in result
        assert "`f" in result or "f\\(x\\)" not in result


class TestFixTruncatedMd2:
    """Tests for fix_truncated_md2() function."""

    @pytest.mark.parametrize("input_text,expected_check", [
        ("", lambda r: r == ""),
        (r"Hello \| world", lambda r: r == r"Hello \| world"),
        ("Hello \\", lambda r: r == "Hello " and not r.endswith("\\")),
        ("*bold text", lambda r: r.endswith("*") and r.count("*") == 2),
        ("_italic text", lambda r: r.endswith("_")),
        ("```python\nprint('hello')", lambda r: r.endswith("```")),
        ("`code here", lambda r: r.endswith("`")),
        ("~struck text", lambda r: r.endswith("~")),
        ("||spoiler content", lambda r: r.endswith("||")),
        (r"\*not bold", lambda r: r == r"\*not bold"),
        (r"(formula\)", lambda r: r == r"\(formula\)"),
        ("=5", lambda r: r == r"\=5"),
        ("+1", lambda r: r == r"\+1"),
        (r"…(formula\)", lambda r: r == r"…\(formula\)"),
        ("…=5 text", lambda r: r == r"…\=5 text"),
        (r"\(formula\)", lambda r: r == r"\(formula\)"),
        (r"…\(formula\)", lambda r: r == r"…\(formula\)"),
    ])
    def test_fix_truncated_md2(self, input_text, expected_check):
        """Should fix truncated MarkdownV2 correctly."""
        from telegram.streaming.markdown_v2 import fix_truncated_md2
        result = fix_truncated_md2(input_text)
        assert expected_check(result)

    def test_multiple_trailing_backslashes(self):
        """All trailing backslashes are removed to ensure validity."""
        from telegram.streaming.markdown_v2 import fix_truncated_md2
        result = fix_truncated_md2("Text\\\\\\")
        assert result == "Text"
        assert not result.endswith("\\")

    def test_nested_formatting(self):
        """Should close multiple unclosed formatting."""
        from telegram.streaming.markdown_v2 import fix_truncated_md2
        result = fix_truncated_md2("*bold _and italic")
        assert "*" in result
        assert "_" in result

    def test_code_block_content_not_affected(self):
        """Content inside code blocks should not trigger fixes."""
        from telegram.streaming.markdown_v2 import fix_truncated_md2
        result = fix_truncated_md2("```\n*not bold*\n```")
        assert result == "```\n*not bold*\n```"

    def test_formatting_markers_not_escaped(self):
        """Formatting markers should not be escaped as leading chars."""
        from telegram.streaming.markdown_v2 import fix_truncated_md2
        result = fix_truncated_md2("*bold text")
        assert result == "*bold text*"

        result = fix_truncated_md2("_italic text")
        assert result == "_italic text_"
