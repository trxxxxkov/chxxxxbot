"""Tests for MarkdownV2 rendering module."""

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

    def test_escapes_special_chars(self):
        """Should escape all MarkdownV2 special characters."""
        result = escape_markdown_v2("1+1=2")
        assert result == r"1\+1\=2"

    def test_escapes_underscore(self):
        """Should escape underscore character."""
        result = escape_markdown_v2("test_var")
        assert result == r"test\_var"

    def test_escapes_asterisk(self):
        """Should escape asterisk character."""
        result = escape_markdown_v2("a*b")
        assert result == r"a\*b"

    def test_escapes_brackets(self):
        """Should escape brackets."""
        result = escape_markdown_v2("[text](url)")
        assert result == r"\[text\]\(url\)"

    def test_escapes_tilde(self):
        """Should escape tilde character."""
        result = escape_markdown_v2("~text~")
        assert result == r"\~text\~"

    def test_escapes_backtick(self):
        """Should escape backtick character."""
        result = escape_markdown_v2("`code`")
        assert result == r"\`code\`"

    def test_escapes_greater_than(self):
        """Should escape greater than for blockquote."""
        result = escape_markdown_v2(">quote")
        assert result == r"\>quote"

    def test_escapes_hash(self):
        """Should escape hash character."""
        result = escape_markdown_v2("#heading")
        assert result == r"\#heading"

    def test_escapes_plus_minus_equals(self):
        """Should escape +, -, = characters."""
        result = escape_markdown_v2("a+b-c=d")
        assert result == r"a\+b\-c\=d"

    def test_escapes_pipe(self):
        """Should escape pipe character (spoiler delimiter)."""
        result = escape_markdown_v2("|text|")
        assert result == r"\|text\|"

    def test_escapes_braces(self):
        """Should escape braces."""
        result = escape_markdown_v2("{key}")
        assert result == r"\{key\}"

    def test_escapes_dot(self):
        """Should escape dot character."""
        result = escape_markdown_v2("file.txt")
        assert result == r"file\.txt"

    def test_escapes_exclamation(self):
        """Should escape exclamation mark."""
        result = escape_markdown_v2("Hello!")
        assert result == r"Hello\!"

    def test_empty_string(self):
        """Should handle empty string."""
        result = escape_markdown_v2("")
        assert result == ""

    def test_preserves_normal_text(self):
        """Should preserve text without special chars."""
        result = escape_markdown_v2("Hello World")
        assert result == "Hello World"


class TestEscapeContexts:
    """Tests for context-aware escaping."""

    def test_code_context_preserves_math(self):
        """Code context should only escape ` and \\."""
        result = escape_markdown_v2("1+1=2", EscapeContext.CODE)
        assert result == "1+1=2"

    def test_code_context_escapes_backtick(self):
        """Code context should escape backtick."""
        result = escape_markdown_v2("print(`code`)", EscapeContext.CODE)
        assert result == r"print(\`code\`)"

    def test_code_context_escapes_backslash(self):
        """Code context should escape backslash."""
        result = escape_markdown_v2("path\\to\\file", EscapeContext.CODE)
        assert result == r"path\\to\\file"

    def test_url_context_preserves_special(self):
        """URL context should only escape ) and \\."""
        result = escape_markdown_v2("https://example.com/path?q=1+1",
                                    EscapeContext.URL)
        assert result == "https://example.com/path?q=1+1"

    def test_url_context_escapes_paren(self):
        """URL context should escape closing parenthesis."""
        result = escape_markdown_v2("https://example.com/path)",
                                    EscapeContext.URL)
        assert result == r"https://example.com/path\)"

    def test_pre_context_preserves_all(self):
        """PRE context should not escape anything."""
        result = escape_markdown_v2("_*[]()~`>#+-=|{}.!", EscapeContext.PRE)
        assert result == "_*[]()~`>#+-=|{}.!"


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

    def test_auto_closes_bold(self):
        """Should auto-close unclosed bold (** in standard MD)."""
        # In standard MD, ** is bold → converted to * in MarkdownV2
        result = render_streaming_safe("Here's **bold te")
        assert result.endswith("*") or "*bold te*" in result

    def test_auto_closes_italic(self):
        """Should auto-close unclosed italic."""
        result = render_streaming_safe("Here's _italic te")
        assert "_" in result  # Should have closing _

    def test_auto_closes_code(self):
        """Should auto-close unclosed inline code."""
        result = render_streaming_safe("Here's `code")
        assert result.endswith("`")

    def test_auto_closes_code_block(self):
        """Should auto-close unclosed code block."""
        result = render_streaming_safe("```python\nprint('hello'")
        assert result.endswith("```")

    def test_handles_nested_formatting(self):
        """Should handle nested formatting."""
        # Standard MD: ** is bold → * in MD2, _ is italic → _ in MD2
        result = render_streaming_safe("**bold _italic")
        # Should auto-close both
        assert "*" in result  # Bold marker
        assert "_" in result  # Italic marker

    def test_preserves_complete_formatting(self):
        """Should preserve already complete formatting."""
        # Standard MD: ** is bold → * in MD2
        result = render_streaming_safe("**bold** text")
        assert "*bold*" in result or "*bold\\*" in result

    def test_escapes_special_chars(self):
        """Should escape special characters in normal text."""
        result = render_streaming_safe("1+1=2")
        assert "+" not in result or r"\+" in result


class TestConvertStandardMarkdown:
    """Tests for convert_standard_markdown function."""

    def test_converts_double_asterisk_bold(self):
        """Should convert **bold** to *bold*."""
        result = convert_standard_markdown("**bold text**")
        # Should contain single * for bold
        assert "*bold text*" in result
        # Should not contain double **
        assert "**" not in result.replace("\\*", "")

    def test_converts_double_tilde_strikethrough(self):
        """Should convert ~~strike~~ to ~strike~."""
        result = convert_standard_markdown("~~strikethrough~~")
        # Should contain single ~ for strikethrough
        assert "~strikethrough~" in result
        # Should not contain double ~~
        assert "~~" not in result.replace("\\~", "")

    def test_preserves_code_blocks(self):
        """Should preserve code block content."""
        result = convert_standard_markdown("```python\n1+1=2\n```")
        assert "1+1=2" in result  # Not escaped inside code block

    def test_escapes_special_in_text(self):
        """Should escape special chars in normal text."""
        result = convert_standard_markdown("Use file.txt please")
        assert r"\." in result


class TestFormatExpandableBlockquoteMd2:
    """Tests for format_expandable_blockquote_md2 function."""

    def test_single_line(self):
        """Should format single line with **> prefix."""
        result = format_expandable_blockquote_md2("Single line")
        assert result.startswith("**>")
        assert "Single line" in result

    def test_multiple_lines(self):
        """Should format multiple lines with > prefix."""
        result = format_expandable_blockquote_md2("Line 1\nLine 2\nLine 3")
        lines = result.split("\n")
        assert lines[0].startswith("**>")
        assert lines[1].startswith(">")
        assert lines[2].startswith(">")

    def test_escapes_content(self):
        """Should escape special characters in content."""
        result = format_expandable_blockquote_md2("1+1=2")
        assert r"\+" in result
        assert r"\=" in result

    def test_empty_content(self):
        """Should handle empty content."""
        result = format_expandable_blockquote_md2("")
        assert result == ""


class TestFormatBlockquoteMd2:
    """Tests for format_blockquote_md2 function."""

    def test_single_line(self):
        """Should format single line with > prefix."""
        result = format_blockquote_md2("Single line")
        assert result.startswith(">")
        assert "Single line" in result

    def test_multiple_lines(self):
        """Should format all lines with > prefix."""
        result = format_blockquote_md2("Line 1\nLine 2")
        lines = result.split("\n")
        assert all(line.startswith(">") for line in lines)

    def test_empty_content(self):
        """Should handle empty content."""
        result = format_blockquote_md2("")
        assert result == ""


class TestCalculateEscapedLength:
    """Tests for calculate_escaped_length function."""

    def test_counts_escaped_chars(self):
        """Should count escaped character length correctly."""
        # "1+1=2" becomes "1\+1\=2" (7 chars: 5 original + 2 escapes)
        result = calculate_escaped_length("1+1=2")
        assert result == 7

    def test_no_escaping_needed(self):
        """Should return same length when no escaping needed."""
        result = calculate_escaped_length("Hello World")
        assert result == 11

    def test_code_context_length(self):
        """Should calculate length with code context."""
        # In code context, only ` and \ are escaped
        result = calculate_escaped_length("1+1=2", EscapeContext.CODE)
        assert result == 5  # No escaping needed


class TestMarkdownV2Integration:
    """Integration tests for MarkdownV2 rendering."""

    def test_streaming_with_partial_bold(self):
        """Should handle partial bold during streaming."""
        # Simulating streaming chunks
        # Standard MD: ** is bold → * in MD2
        renderer = MarkdownV2Renderer()
        renderer.append("Hello **bold")
        result1 = renderer.render(auto_close=True)
        assert result1.endswith("*")  # Auto-closed bold

        # Continue streaming
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
        # Standard MD: ** is bold → * in MD2, _ is italic
        text = "Normal **bold** and `code` and _italic_"
        result = render_streaming_safe(text)
        # Should preserve formatting structure
        assert "*" in result  # Bold marker
        assert "`" in result  # Code marker
        assert "_" in result  # Italic marker

    def test_complex_math_expression(self):
        """Should escape math expressions properly."""
        result = render_streaming_safe("Calculate: (a+b)*(c-d)=result")
        # All special chars should be escaped in normal text
        assert r"\(" in result or r"(" not in result
        assert r"\+" in result
        assert r"\)" in result or r")" not in result
        assert r"\*" in result
        assert r"\-" in result
        assert r"\=" in result

    def test_nested_formatting_recovery(self):
        """Should recover from malformed nested formatting."""
        # Invalid markdown: italic opened inside bold, bold closed first
        text = "*bold _text*"
        result = render_streaming_safe(text)
        # Should produce valid output
        assert result is not None

    def test_empty_input(self):
        """Should handle empty input gracefully."""
        assert render_streaming_safe("") == ""
        assert format_expandable_blockquote_md2("") == ""
        assert format_blockquote_md2("") == ""

    def test_unicode_content(self):
        """Should handle unicode content."""
        result = render_streaming_safe("Emoji: 🚀 and text")
        assert "🚀" in result

    def test_preserves_newlines(self):
        """Should preserve newlines in text."""
        result = render_streaming_safe("Line 1\n\nLine 2")
        assert "\n\n" in result


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_consecutive_special_chars(self):
        """Should escape consecutive special characters."""
        result = escape_markdown_v2("++--==")
        assert result == r"\+\+\-\-\=\="

    def test_backslash_handling(self):
        """Should handle backslashes correctly."""
        result = escape_markdown_v2("path\\file")
        # Backslash is not in ESCAPE_CHARS_NORMAL for MarkdownV2
        # Let's check the actual behavior
        assert "path" in result
        assert "file" in result

    def test_very_long_text(self):
        """Should handle very long text."""
        long_text = "Hello World. " * 1000
        result = render_streaming_safe(long_text)
        assert len(result) > len(long_text)  # Due to escaping

    def test_only_special_chars(self):
        """Should handle text with only special chars."""
        result = escape_markdown_v2("*_[]()~`>#+-=|{}.!")
        # Every char should be escaped
        assert result == r"\*\_\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!"

    def test_whitespace_handling(self):
        """Should preserve whitespace."""
        result = escape_markdown_v2("  spaces  ")
        assert result == "  spaces  "

    def test_tabs_handling(self):
        """Should preserve tabs."""
        result = escape_markdown_v2("col1\tcol2")
        assert "\t" in result


class TestLongMessageHandling:
    """Tests for handling messages near or exceeding Telegram's 4096 char limit."""

    def test_long_text_escaping_increases_length(self):
        """Text with many special chars can exceed limit after escaping."""
        # Create text with lots of special chars
        # "1+1=2. " = 7 chars raw, becomes "1\+1\=2\. " = 10 chars escaped
        raw_text = "1+1=2. " * 500  # 3500 raw chars
        result = render_streaming_safe(raw_text)
        # Escaped length should be ~5000 chars (exceeds 4096)
        assert len(result) > len(raw_text)
        # Verify escaping is correct
        assert r"\+" in result
        assert r"\=" in result
        assert r"\." in result

    def test_long_text_with_formatting_preserved(self):
        """Long text with formatting should preserve structure."""
        # Create text with formatting
        text = "**Bold start** " + "x" * 3000 + " **bold end**"
        result = render_streaming_safe(text)
        # Bold markers should be converted and preserved
        assert "*Bold start*" in result or "*Bold start\\*" in result
        assert "*bold end*" in result or "*bold end\\*" in result

    def test_long_code_block_preserved(self):
        """Long code blocks should be preserved without internal escaping."""
        code_content = "var x = 1+1; // 2\n" * 200  # ~3800 chars
        text = f"```javascript\n{code_content}```"
        result = render_streaming_safe(text)
        # Inside code block, + and = should NOT be escaped
        assert "1+1" in result
        assert "// 2" in result
        # Code block delimiters should be preserved
        assert result.startswith("```javascript")
        assert result.rstrip().endswith("```")

    def test_long_text_auto_closes_unclosed_formatting(self):
        """Very long text with unclosed formatting should auto-close."""
        # Unclosed bold at start
        text = "**Bold text " + "x" * 4000
        result = render_streaming_safe(text)
        # Should auto-close the bold
        assert result.endswith("*")
        # Count * markers - should be even (open + close)
        # In MD2, ** becomes *, so we should have 2 *
        star_count = result.count("*") - result.count(r"\*")
        assert star_count >= 2

    def test_long_text_with_nested_formatting(self):
        """Long text with nested formatting handles correctly."""
        text = "**Bold _and italic " + "word " * 800 + "end_**"
        result = render_streaming_safe(text)
        # Should have both formatting types
        assert "*" in result  # Bold
        assert "_" in result  # Italic

    def test_very_long_single_word(self):
        """Single very long word without spaces."""
        # No word breaks - single "word" of 5000 chars
        long_word = "a" * 5000
        result = render_streaming_safe(long_word)
        assert len(result) == 5000  # No escaping needed for 'a'

    def test_long_text_with_many_urls(self):
        """Long text with many URLs should preserve URL structure."""
        url = "[Link](https://example.com/path?q=1+1)"
        text = (url + " text ") * 100  # Many URLs
        result = render_streaming_safe(text)
        # URLs should be preserved (parentheses not escaped inside URL)
        assert "[Link]" in result
        assert "https://example.com" in result


class TestMessageSplittingEdgeCases:
    """Tests for edge cases when messages need splitting."""

    def test_truncation_at_escape_sequence(self):
        """Truncation shouldn't break in the middle of escape sequence."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        # Create text that might truncate mid-escape
        # "1+1" becomes "1\+1" - don't want to cut between \ and +
        text = "x" * 3990 + r"1\+1\=2"
        thinking = "**>" + "t" * 200

        result_thinking, result_text = tm.truncate_for_display(thinking, text)
        # Text should not end with lone backslash
        if result_text:
            assert not result_text.rstrip().endswith("\\") or \
                   result_text.rstrip().endswith("\\\\")

    def test_truncation_preserves_valid_markdown(self):
        """Truncated text should still be valid MarkdownV2."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        # Text with formatting
        text = "*Bold* " * 500  # Many formatted words
        thinking = "**>" + "t" * 100

        result_thinking, result_text = tm.truncate_for_display(thinking, text)
        # Result should still have balanced markers
        if result_text:
            # Count unescaped asterisks
            import re
            unescaped_stars = len(re.findall(r'(?<!\\)\*', result_text))
            # Should be even (paired)
            assert unescaped_stars % 2 == 0 or result_text.endswith("…")

    def test_thinking_truncation_keeps_recent_content(self):
        """When thinking is truncated, recent content is preserved."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        # Thinking with identifiable parts
        thinking = "**>OLD_PART_" + "x" * 4000 + "_RECENT_END"
        text = "Short answer"

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        # Recent part should be preserved
        assert "_RECENT_END" in result_thinking
        # Old part should be removed
        assert "OLD_PART_" not in result_thinking
        # Should start with blockquote marker
        assert result_thinking.startswith("**>")

    def test_text_exceeding_limit_hides_thinking(self):
        """When text exceeds limit, thinking is hidden entirely."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        text = "x" * 4000
        thinking = "**>" + "t" * 500

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        # Thinking should be empty
        assert result_thinking == ""
        # Text should have ellipsis at end
        assert result_text.endswith("…")

    def test_multiline_blockquote_truncation(self):
        """Multi-line blockquote truncation preserves structure."""
        from telegram.streaming.truncation import TruncationManager

        tm = TruncationManager(parse_mode="MarkdownV2")
        # Multi-line thinking with proper blockquote structure
        thinking = "**>Line 1\n>Line 2\n>Line 3\n>" + "x" * 4000 + "\n>Final line"
        text = "Answer"

        result_thinking, result_text = tm.truncate_for_display(thinking, text)

        if result_thinking:
            # Should start with expandable marker
            assert result_thinking.startswith("**>")
            # All lines after first should start with >
            lines = result_thinking.split("\n")
            for i, line in enumerate(lines[1:], 1):
                if line:  # Skip empty lines
                    assert line.startswith(
                        ">"), f"Line {i} doesn't start with >: {line}"


class TestFormattingEdgeCases:
    """Additional edge cases for formatting."""

    def test_empty_bold_markers(self):
        """Empty bold markers should be escaped."""
        result = render_streaming_safe("Text ** here")
        # ** without content should be escaped or handled
        assert "Text" in result
        assert "here" in result

    def test_empty_italic_markers(self):
        """Empty italic markers should be escaped."""
        result = render_streaming_safe("Text __ here")
        # __ without content handled
        assert "Text" in result
        assert "here" in result

    def test_single_delimiter_at_end(self):
        """Single delimiter at text end should be escaped."""
        result = render_streaming_safe("Text ends with *")
        # Should escape the trailing *
        assert r"\*" in result or result.endswith("*")

    def test_delimiter_surrounded_by_spaces(self):
        """Delimiters surrounded by spaces should be escaped."""
        result = render_streaming_safe("a * b * c")
        # Isolated * should be escaped
        assert result.count(r"\*") >= 2 or "a * b * c" not in result

    def test_code_with_backticks_inside(self):
        """Code containing backticks should escape them."""
        result = render_streaming_safe("Use `echo \\`date\\`` for time")
        # Backticks inside code should be escaped
        assert "`" in result

    def test_nested_code_blocks(self):
        """Nested code block markers handled correctly."""
        # Code block containing ``` as text
        text = "```\nUse ``` for code blocks\n```"
        result = render_streaming_safe(text)
        # Should produce valid output
        assert "```" in result

    def test_link_with_special_chars_in_text(self):
        """Link text with special chars should be escaped."""
        result = render_streaming_safe("[Click (here)!](https://example.com)")
        # Link structure preserved
        assert "[" in result
        assert "](" in result
        assert ")" in result
        # Text inside brackets should have escaped special chars
        assert "Click" in result

    def test_link_with_parentheses_in_url(self):
        """URL with parentheses should escape them properly."""
        result = render_streaming_safe(
            "[Wiki](https://en.wikipedia.org/wiki/Python_(programming_language))"
        )
        # URL should be preserved
        assert "wikipedia.org" in result

    def test_mixed_formatting_and_code(self):
        """Mixed formatting and code in same text."""
        text = "**Bold** then `code with + and =` then _italic_"
        result = render_streaming_safe(text)
        # Bold converted
        assert "*Bold*" in result or "*Bold\\*" in result
        # Code preserved (+ and = not escaped inside)
        assert "`code with + and =`" in result
        # Italic preserved
        assert "_italic_" in result

    def test_strikethrough_conversion(self):
        """Double tilde converted to single tilde."""
        result = render_streaming_safe("~~strikethrough~~")
        # ~~ should become ~
        assert "~strikethrough~" in result
        # Should not have ~~
        assert "~~" not in result.replace(r"\~", "")

    def test_spoiler_markers(self):
        """Spoiler markers should work."""
        result = render_streaming_safe("This is ||spoiler|| text")
        assert "||spoiler||" in result

    def test_underline_vs_italic(self):
        """Double underscore is underline, single is italic."""
        result = render_streaming_safe("__underline__ and _italic_")
        assert "__underline__" in result  # Underline preserved
        assert "_italic_" in result  # Italic preserved

    def test_blockquote_at_line_start(self):
        """Blockquote markers at line start."""
        result = escape_markdown_v2(">quoted text")
        # > at start should be escaped in normal text
        assert r"\>" in result

    def test_multiple_paragraphs_with_formatting(self):
        """Multiple paragraphs with different formatting."""
        text = "**Bold para**\n\n_Italic para_\n\n`Code para`"
        result = render_streaming_safe(text)
        # All formatting types preserved
        assert "*Bold para*" in result or "*Bold para\\*" in result
        assert "_Italic para_" in result
        assert "`Code para`" in result
        # Paragraph breaks preserved
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
        assert lines[0].startswith("**>")  # First line has expandable marker
        assert all(line.startswith(">") for line in lines[1:])  # Rest have >

    def test_blockquote_preserves_empty_lines(self):
        """Empty lines in blockquote should be handled."""
        result = format_expandable_blockquote_md2("Para 1\n\nPara 2")
        lines = result.split("\n")
        assert len(lines) == 3
        # Empty line should still have >
        assert lines[1] == ">"

    def test_blockquote_with_code(self):
        """Blockquote containing code markers."""
        result = format_expandable_blockquote_md2("Use `code` here")
        assert "**>" in result
        # Backticks are now treated as valid inline code formatting
        # (content goes through render_streaming_safe for proper MarkdownV2)
        assert "`code`" in result

    def test_blockquote_auto_closes_unclosed_formatting(self):
        """Unclosed formatting in blockquote should be auto-closed.

        This is critical for Draft API compatibility - once a draft is created
        with MarkdownV2, all subsequent text must be valid MarkdownV2. Without
        auto-closing, unclosed formatting could cause parse errors in keepalive.
        """
        # Unclosed bold
        result = format_expandable_blockquote_md2("Starting *bold text")
        assert "**>" in result
        assert result.endswith("||")
        # Bold should be auto-closed
        assert result.count("*") >= 2  # Opening and closing

        # Unclosed code block
        result = format_expandable_blockquote_md2(
            "Code: ```python\nprint('hi')")
        assert "```" in result
        # Code block should be auto-closed
        assert result.count("```") >= 2

        # Unclosed inline code
        result = format_expandable_blockquote_md2("Variable `foo should close")
        assert result.count("`") >= 2  # Opening and closing

    def test_blockquote_with_markdown_syntax(self):
        """Blockquote should properly convert standard Markdown to MarkdownV2."""
        # Standard Markdown bold (**) should convert to MarkdownV2 (*)
        result = format_expandable_blockquote_md2("This is **bold** text")
        assert "**>" in result  # Expandable marker
        # Bold content preserved (converted to single *)
        assert "*bold*" in result

    def test_very_long_single_line_blockquote(self):
        """Very long single line blockquote."""
        long_content = "x" * 5000
        result = format_expandable_blockquote_md2(long_content)
        assert result.startswith("**>")
        assert len(result) > 5000  # Has prefix

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

        # Stream chunks
        chunks = ["Hello ", "**world", "**! ", "This is `code", "` here."]

        for i, chunk in enumerate(chunks):
            renderer.append(chunk)
            result = renderer.render(auto_close=True)
            # Every intermediate result should be valid (no parse errors)
            assert result is not None
            # Check auto-closing works at each step
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

        # Should have expandable blockquote for thinking
        assert "**>" in result
        # Tool markers should be in thinking
        assert "🐍" in result
        # Text should be present with escaping
        assert r"\+" in result or "1+1=2" not in result

    def test_streaming_very_long_response(self):
        """Streaming a very long response with mixed content."""
        from telegram.streaming.formatting import format_blocks
        from telegram.streaming.types import BlockType
        from telegram.streaming.types import DisplayBlock

        # Long thinking
        thinking_content = "🧠 " + "Analysis step. " * 200
        # Long text
        text_content = "Here's my answer: " + "word " * 500

        blocks = [
            DisplayBlock(BlockType.THINKING, thinking_content),
            DisplayBlock(BlockType.TEXT, text_content),
        ]

        result = format_blocks(blocks,
                               is_streaming=True,
                               parse_mode="MarkdownV2")

        # Should produce valid output (truncated if needed)
        assert result is not None
        # Check it's not too long (truncation should have happened)
        # Note: actual limit depends on implementation

    def test_code_block_streaming(self):
        """Streaming code block character by character."""
        renderer = MarkdownV2Renderer()

        # Stream a code block character by character
        code = "```python\nprint('hello')\n```"
        for i, char in enumerate(code):
            renderer.append(char)
            result = renderer.render(auto_close=True)
            # Should always produce valid output
            assert result is not None
            # After opening ```, should auto-close
            if "```python" in renderer._raw_text and "```" not in renderer._raw_text[
                    10:]:
                assert result.rstrip().endswith("```")

    def test_rapid_format_switching(self):
        """Rapid switching between formatting types."""
        text = "*b*_i_*b*_i_`c`*b*_i_" * 100
        result = render_streaming_safe(text)
        # Should handle rapid switching
        assert result is not None
        # Count markers should be balanced
        assert result.count("`") % 2 == 0


class TestRegressionCases:
    """Regression tests for potential bugs."""

    def test_backslash_before_special_char(self):
        """Backslash before special char shouldn't double-escape."""
        # User writes literal \* meaning escaped asterisk
        result = escape_markdown_v2(r"\*")
        # Should escape backslash and asterisk separately
        assert result is not None

    def test_url_with_query_params(self):
        """URL with query parameters."""
        result = render_streaming_safe("[Link](https://example.com?a=1&b=2)")
        # URL should be preserved
        assert "https://example.com" in result

    def test_math_expression_in_text(self):
        """Math expression should be fully escaped."""
        result = render_streaming_safe("Solve: x² + 2x + 1 = 0")
        # + and = should be escaped
        assert r"\+" in result
        assert r"\=" in result

    def test_file_path_in_text(self):
        """File path with dots and slashes."""
        result = render_streaming_safe("See file: /path/to/file.txt")
        # Dot should be escaped
        assert r"\." in result

    def test_markdown_in_quotes(self):
        """Markdown-like text in quotes shouldn't be formatted."""
        # User is talking about markdown, not using it
        result = escape_markdown_v2('Use "**bold**" for emphasis')
        # ** should be escaped (not interpreted)
        assert r"\*\*" in result

    def test_telegram_username_mention(self):
        """Telegram @username should work."""
        result = render_streaming_safe("Contact @username for help")
        # @ is not a special char in MarkdownV2
        assert "@username" in result

    def test_hashtag_handling(self):
        """Hashtag should be escaped."""
        result = render_streaming_safe("Use #hashtag for topics")
        # # should be escaped
        assert r"\#" in result

    def test_html_entities_in_text(self):
        """HTML entities should be preserved (not interpreted)."""
        result = render_streaming_safe("Use &amp; for ampersand")
        # & is not a MarkdownV2 special char, should be preserved
        assert "&amp;" in result or "&" in result

    def test_json_in_code_block(self):
        """JSON in code block should not be escaped."""
        json_code = '```json\n{"key": "value", "num": 1+1}\n```'
        result = render_streaming_safe(json_code)
        # Inside code block, quotes and + should not be escaped
        assert '"key"' in result
        assert "1+1" in result

    def test_shell_command_with_pipes(self):
        """Shell command with pipes should escape | in text."""
        result = render_streaming_safe("Run: ls | grep test")
        # | should be escaped
        assert r"\|" in result

    def test_bullet_list_formatting(self):
        """Bullet list with - should escape dashes."""
        result = render_streaming_safe("List:\n- Item 1\n- Item 2")
        # - should be escaped
        assert r"\-" in result

    def test_single_tilde_not_strikethrough(self):
        """Single ~ should be escaped, not treated as strikethrough.

        Bug fix regression test: Single ~ followed by text was incorrectly
        opening a strikethrough context, causing text to be struck through.
        Only ~~ should be treated as strikethrough (standard Markdown).
        """
        # Cost with tilde - should NOT create strikethrough
        result = render_streaming_safe("Cost: ~$0.006/minute")
        # Single ~ should be escaped (backslash before tilde)
        assert r"\~" in result
        # The entire text after tilde should NOT be struck through
        # If strikethrough was opened, everything would be in strikethrough
        # With proper escaping, we get \~$0\.006/minute
        assert result.count("~") == 1  # Only one ~ (escaped)

        # Text with tilde at various positions
        result2 = render_streaming_safe("Approximately ~100 items remaining")
        assert r"\~" in result2
        assert result2.count("~") == 1  # Only one ~ (escaped)

        # Double tilde SHOULD still work as strikethrough
        result3 = render_streaming_safe("This is ~~struck~~ text")
        assert "~struck~" in result3  # Converted to single ~ for MarkdownV2

    def test_tilde_in_technical_content(self):
        """Tilde in technical content should be escaped.

        Common cases: home directories (~user), approximate values (~10ms).
        """
        # Unix home directory
        result = render_streaming_safe("Path: ~/Documents/file.txt")
        assert r"\~" in result

        # Latency with approximate
        result2 = render_streaming_safe("Latency: ~10ms for fast queries")
        assert r"\~" in result2


class TestPreprocessUnsupportedMarkdown:
    """Tests for preprocess_unsupported_markdown function."""

    def test_empty_string(self):
        """Should handle empty string."""
        assert preprocess_unsupported_markdown("") == ""

    def test_plain_text_unchanged(self):
        """Plain text without LaTeX or headers should be unchanged."""
        text = "This is plain text without special features."
        assert preprocess_unsupported_markdown(text) == text

    def test_latex_inline_parentheses(self):
        """Should convert LaTeX inline math \\(...\\) to code."""
        result = preprocess_unsupported_markdown(
            r"The formula \(x^2\) is simple")
        assert result == "The formula `x^2` is simple"

    def test_latex_inline_dollar(self):
        """Should convert LaTeX inline math $...$ to code."""
        result = preprocess_unsupported_markdown("The formula $x^2$ is simple")
        assert result == "The formula `x^2` is simple"

    def test_latex_display_brackets(self):
        """Should convert LaTeX display math \\[...\\] to code block."""
        result = preprocess_unsupported_markdown(
            r"Formula: \[x^2 + y^2 = z^2\]")
        assert "```" in result
        assert "x^2 + y^2 = z^2" in result

    def test_latex_display_double_dollar(self):
        """Should convert LaTeX display math $$...$$ to code block."""
        result = preprocess_unsupported_markdown("Formula: $$x^2 + y^2$$")
        assert "```" in result
        assert "x^2 + y^2" in result

    def test_header_h1(self):
        """Should convert # Header to bold."""
        result = preprocess_unsupported_markdown("# Main Title")
        assert result == "**Main Title**"

    def test_header_h2(self):
        """Should convert ## Header to bold."""
        result = preprocess_unsupported_markdown("## Subtitle")
        assert result == "**Subtitle**"

    def test_header_h3(self):
        """Should convert ### Header to bold."""
        result = preprocess_unsupported_markdown("### Section")
        assert result == "**Section**"

    def test_multiple_headers(self):
        """Should convert multiple headers."""
        text = "# Title\nSome text\n## Subtitle\nMore text"
        result = preprocess_unsupported_markdown(text)
        assert "**Title**" in result
        assert "**Subtitle**" in result
        assert "Some text" in result

    def test_header_not_at_line_start(self):
        """Should not convert # that's not at line start."""
        text = "Use the # symbol for comments"
        result = preprocess_unsupported_markdown(text)
        # # in the middle should not be converted
        assert "**" not in result

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

    def test_latex_with_spaces(self):
        """Should handle LaTeX with spaces around content."""
        result = preprocess_unsupported_markdown(r"\( x + y \)")
        assert result == "`x + y`"

    def test_multiple_inline_latex(self):
        """Should convert multiple inline LaTeX expressions."""
        text = r"Variables \(x\) and \(y\) are used"
        result = preprocess_unsupported_markdown(text)
        assert result == "Variables `x` and `y` are used"

    def test_render_after_preprocess(self):
        """Full flow: preprocess then render should produce valid output."""
        text = "# Formula\nThe Taylor series \\(f(x)\\) expands to..."
        result = render_streaming_safe(text)
        # Should have bold for header (after preprocessing converts # to **)
        # and then ** is converted to * in MarkdownV2
        assert "*Formula*" in result
        # Should have code for LaTeX
        assert "`f" in result or "f\\(x\\)" not in result
