"""MarkdownV2 rendering for Telegram streaming.

This module provides MarkdownV2 rendering with:
- Context-aware escaping (normal text vs code vs URL)
- Incremental parsing with stack-based context tracking
- Auto-closing of unclosed formatting during streaming
- Conversion from standard Markdown to Telegram MarkdownV2

NO __init__.py - use direct import:
    from telegram.streaming.markdown_v2 import escape_markdown_v2
    from telegram.streaming.markdown_v2 import MarkdownV2Renderer
"""

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
import re
from typing import Optional


class EscapeContext(str, Enum):
    """Context for escaping special characters.

    Different contexts require different escaping rules:
    - NORMAL: Full escaping of all special chars
    - CODE: Only escape ` and \
    - URL: Only escape ) and \
    - PRE: Inside code block, no escaping needed (handled by ```)
    """

    NORMAL = "normal"
    CODE = "code"
    URL = "url"
    PRE = "pre"


# Characters that need escaping in MarkdownV2 (normal context)
# Reference: https://core.telegram.org/bots/api#markdownv2-style
ESCAPE_CHARS_NORMAL = r"_*[]()~`>#+-=|{}.!"

# Characters that need escaping inside inline code (` context)
ESCAPE_CHARS_CODE = r"`\\"

# Characters that need escaping inside URLs
ESCAPE_CHARS_URL = r")\\"


def preprocess_unsupported_markdown(text: str) -> str:
    r"""Preprocess text to convert unsupported Markdown features.

    Telegram MarkdownV2 doesn't support LaTeX math or headers.
    This function converts them to readable alternatives BEFORE
    the main MarkdownV2 rendering.

    Conversions:
    - LaTeX inline: \\(formula\\) or $formula$ → `formula`
    - LaTeX display: \\[formula\\] or $$formula$$ → ```formula```
    - Headers: # Title → *Title* (bold)

    Args:
        text: Raw text possibly containing LaTeX or headers.

    Returns:
        Text with unsupported features converted.
    """
    if not text:
        return ""

    result = text

    # Convert LaTeX display math: \[...\] or $$...$$ to code block
    # Must be done before inline math (longer patterns first)
    result = re.sub(r'\\\[(.*?)\\\]',
                    lambda m: f"```\n{m.group(1).strip()}\n```",
                    result,
                    flags=re.DOTALL)
    result = re.sub(r'\$\$(.*?)\$\$',
                    lambda m: f"```\n{m.group(1).strip()}\n```",
                    result,
                    flags=re.DOTALL)

    # Convert LaTeX inline math: \(...\) or $...$ to inline code
    result = re.sub(r'\\\((.*?)\\\)', lambda m: f"`{m.group(1).strip()}`",
                    result)
    result = re.sub(r'(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)',
                    lambda m: f"`{m.group(1).strip()}`", result)

    # Convert headers to bold (must be at line start)
    # # Title → *Title*
    # ## Title → *Title*
    # ### Title → *Title*
    result = re.sub(r'^(#{1,6})\s+(.+?)$',
                    r'**\2**',
                    result,
                    flags=re.MULTILINE)

    return result


def escape_markdown_v2(text: str,
                       context: EscapeContext = EscapeContext.NORMAL) -> str:
    r"""Escape special characters for Telegram MarkdownV2.

    Context-aware escaping:
    - NORMAL: Escape all MarkdownV2 special chars
    - CODE: Only escape ` and \\ (inside inline code)
    - URL: Only escape ) and \\ (inside link URLs)
    - PRE: No escaping (inside code blocks)

    Args:
        text: Raw text to escape.
        context: Escaping context (affects which chars are escaped).

    Returns:
        Escaped text safe for Telegram MarkdownV2.

    Examples:
        >>> escape_markdown_v2("1+1=2")
        '1\\+1\\=2'
        >>> escape_markdown_v2("print('hello')", EscapeContext.CODE)
        "print('hello')"
        >>> escape_markdown_v2("https://example.com/path?q=1", EscapeContext.URL)
        'https://example.com/path?q=1'
    """
    if not text:
        return ""

    if context == EscapeContext.PRE:
        # Inside code blocks, no escaping needed
        return text

    if context == EscapeContext.CODE:
        # Inside inline code: only escape ` and \
        result = text.replace("\\", "\\\\")
        result = result.replace("`", "\\`")
        return result

    if context == EscapeContext.URL:
        # Inside URLs: only escape ) and \
        result = text.replace("\\", "\\\\")
        result = result.replace(")", "\\)")
        return result

    # Normal context: escape all special characters
    chars: list[str] = []
    for char in text:
        if char in ESCAPE_CHARS_NORMAL:
            chars.append("\\")
        chars.append(char)
    return "".join(chars)


class FormattingType(str, Enum):
    """Types of formatting that can be open during parsing."""

    BOLD = "bold"  # *text*
    ITALIC = "italic"  # _text_
    UNDERLINE = "underline"  # __text__
    STRIKETHROUGH = "strikethrough"  # ~text~
    SPOILER = "spoiler"  # ||text||
    CODE = "code"  # `code`
    CODE_BLOCK = "code_block"  # ```code```
    LINK_TEXT = "link_text"  # [text
    LINK_URL = "link_url"  # ](url


@dataclass
class FormattingContext:
    """Tracks an open formatting marker.

    Attributes:
        format_type: Type of formatting.
        start_pos: Position in raw text where opened.
        delimiter: Opening delimiter string.
        language: For code blocks, the language (may be empty).
        paren_depth: For LINK_URL, tracks nested parentheses depth.
    """

    format_type: FormattingType
    start_pos: int
    delimiter: str
    language: str = ""
    paren_depth: int = 0


@dataclass
class MarkdownV2Renderer:
    """Incremental MarkdownV2 renderer for streaming.

    Tracks open formatting markers and can auto-close them for
    valid MarkdownV2 output during streaming.

    The renderer parses standard Markdown (as Claude outputs) and
    converts it to Telegram MarkdownV2 format:
    - **bold** -> *bold*
    - *italic* or _italic_ -> _italic_
    - ~~strike~~ -> ~strike~
    - ```code``` -> ```code```

    Example:
        renderer = MarkdownV2Renderer()
        renderer.append("Here's some *bold and _italic")
        output = renderer.render()  # Returns valid MarkdownV2 with auto-closed markers
    """

    _raw_text: str = ""
    _context_stack: list[FormattingContext] = field(default_factory=list)

    def append(self, text: str) -> None:
        """Append raw text (accumulate during streaming).

        Args:
            text: Raw text chunk from Claude response.
        """
        self._raw_text += text

    def clear(self) -> None:
        """Clear accumulated text and context."""
        self._raw_text = ""
        self._context_stack.clear()

    def render(self, auto_close: bool = True) -> str:
        """Render accumulated text as valid MarkdownV2.

        Parses the raw text, converts standard Markdown to MarkdownV2,
        escapes special characters, and optionally auto-closes unclosed
        formatting.

        Args:
            auto_close: If True, auto-close unclosed formatting markers.

        Returns:
            Valid MarkdownV2 string for Telegram.
        """
        if not self._raw_text:
            return ""

        return _render_markdown_v2(self._raw_text, auto_close)

    def get_raw_length(self) -> int:
        """Get length of raw (unescaped) text.

        Returns:
            Length of accumulated raw text.
        """
        return len(self._raw_text)

    def get_escaped_length(self) -> int:
        """Get estimated length after escaping.

        This is an estimate since full rendering is expensive.
        Uses worst-case assumption of 2x for special chars.

        Returns:
            Estimated length after escaping.
        """
        # Count special characters that would be escaped
        special_count = sum(
            1 for c in self._raw_text if c in ESCAPE_CHARS_NORMAL)
        return len(self._raw_text) + special_count


def _render_markdown_v2(text: str, auto_close: bool = True) -> str:
    """Render text as valid MarkdownV2.

    Internal function that does the actual parsing and rendering.

    Algorithm:
    0. Preprocess unsupported features (LaTeX, headers)
    1. Parse text character by character
    2. Track open formatting contexts in a stack
    3. Convert standard Markdown delimiters to MarkdownV2
    4. Escape special characters based on context
    5. Auto-close unclosed formatting if requested

    Args:
        text: Raw text to render.
        auto_close: Whether to auto-close unclosed formatting.

    Returns:
        Valid MarkdownV2 string.
    """
    # Preprocess unsupported markdown features (LaTeX, headers)
    text = preprocess_unsupported_markdown(text)

    result: list[str] = []
    context_stack: list[FormattingContext] = []
    i = 0
    n = len(text)

    def current_context() -> Optional[FormattingType]:
        """Get current formatting context (innermost)."""
        return context_stack[-1].format_type if context_stack else None

    def in_code_context() -> bool:
        """Check if we're inside code or code_block."""
        ctx = current_context()
        return ctx in (FormattingType.CODE, FormattingType.CODE_BLOCK)

    def push_context(fmt_type: FormattingType,
                     delimiter: str,
                     lang: str = "") -> None:
        """Push new formatting context."""
        context_stack.append(
            FormattingContext(format_type=fmt_type,
                              start_pos=len(result),
                              delimiter=delimiter,
                              language=lang))

    def pop_context(expected_type: FormattingType) -> bool:
        """Pop context if top matches expected type."""
        if context_stack and context_stack[-1].format_type == expected_type:
            context_stack.pop()
            return True
        return False

    while i < n:
        # Check for code block (```) - highest priority
        if text[i:i + 3] == "```":
            if current_context() == FormattingType.CODE_BLOCK:
                # Closing code block
                result.append("```")
                pop_context(FormattingType.CODE_BLOCK)
                i += 3
                continue
            if not in_code_context():
                # Opening code block
                result.append("```")
                i += 3
                # Extract language (if any, until newline)
                lang_start = i
                while i < n and text[i] != "\n" and text[i] != "`":
                    i += 1
                language = text[lang_start:i]
                result.append(language)
                push_context(FormattingType.CODE_BLOCK, "```", language)
                continue

        # Inside code block - output as-is (no escaping)
        if current_context() == FormattingType.CODE_BLOCK:
            result.append(text[i])
            i += 1
            continue

        # Check for inline code (`)
        if text[i] == "`" and text[i:i + 3] != "```":
            if current_context() == FormattingType.CODE:
                # Closing inline code
                result.append("`")
                pop_context(FormattingType.CODE)
            else:
                # Opening inline code
                result.append("`")
                push_context(FormattingType.CODE, "`")
            i += 1
            continue

        # Inside inline code - escape only ` and \
        if current_context() == FormattingType.CODE:
            if text[i] == "\\":
                result.append("\\\\")
            else:
                result.append(text[i])
            i += 1
            continue

        # Skip formatting inside link URL - output URL characters directly
        if current_context() == FormattingType.LINK_URL:
            # Whitespace in URL is invalid - close the link immediately
            if text[i] in " \t\n\r":
                result.append(")")
                pop_context(FormattingType.LINK_URL)
                # Don't consume the whitespace, let normal processing handle it
                continue
            if text[i] == "(":
                # Open paren in URL - track depth for balanced parens
                context_stack[-1].paren_depth += 1
                result.append("(")
                i += 1
                continue
            if text[i] == ")":
                # Check if this closes the link or is a balanced paren
                if context_stack[-1].paren_depth > 0:
                    # This ) matches an earlier ( in the URL - escape it
                    context_stack[-1].paren_depth -= 1
                    result.append("\\)")
                else:
                    # This ) closes the link
                    result.append(")")
                    pop_context(FormattingType.LINK_URL)
                i += 1
                continue
            if text[i] == "\\":
                result.append("\\\\")
            else:
                # Output URL characters as-is (no escaping except \ and ))
                result.append(text[i])
            i += 1
            continue

        # Check for standard Markdown bold (**) - convert to MarkdownV2 (*)
        if text[i:i + 2] == "**":
            if current_context() == FormattingType.BOLD:
                # Closing bold - use single * for MarkdownV2
                result.append("*")
                pop_context(FormattingType.BOLD)
            else:
                # Opening bold - use single * for MarkdownV2
                result.append("*")
                push_context(FormattingType.BOLD, "**")
            i += 2
            continue

        # Check for underline (__) - must check before italic (_)
        if text[i:i + 2] == "__":
            if current_context() == FormattingType.UNDERLINE:
                result.append("__")
                pop_context(FormattingType.UNDERLINE)
            else:
                result.append("__")
                push_context(FormattingType.UNDERLINE, "__")
            i += 2
            continue

        # Check for spoiler (||)
        if text[i:i + 2] == "||":
            if current_context() == FormattingType.SPOILER:
                result.append("||")
                pop_context(FormattingType.SPOILER)
            else:
                result.append("||")
                push_context(FormattingType.SPOILER, "||")
            i += 2
            continue

        # Check for strikethrough (~~) - convert to MarkdownV2 (~)
        if text[i:i + 2] == "~~":
            if current_context() == FormattingType.STRIKETHROUGH:
                result.append("~")
                pop_context(FormattingType.STRIKETHROUGH)
            else:
                result.append("~")
                push_context(FormattingType.STRIKETHROUGH, "~~")
            i += 2
            continue

        # Check for single * (could be italic in standard MD, but in MarkdownV2 it's bold)
        # We treat single * as bold only if not preceded by **
        if text[i] == "*" and text[i:i + 2] != "**":
            # In MarkdownV2, * is bold. Check if this is a close marker.
            # For Claude's output, single * is usually italic, but we convert to _
            # However, if Claude uses single * for emphasis, it should be italic
            # Let's treat single * as italic (convert to _)
            if current_context() == FormattingType.ITALIC:
                result.append("_")
                pop_context(FormattingType.ITALIC)
            elif (i + 1 < n and text[i + 1] not in " \t\n" and
                  (i == 0 or text[i - 1] in " \t\n([{")):
                # Looks like opening italic (after space/start, before non-space)
                result.append("_")
                push_context(FormattingType.ITALIC, "*")
            else:
                # Isolated *, escape it
                result.append("\\*")
            i += 1
            continue

        # Check for italic (_)
        if text[i] == "_" and text[i:i + 2] != "__":
            if current_context() == FormattingType.ITALIC:
                result.append("_")
                pop_context(FormattingType.ITALIC)
            elif (i + 1 < n and text[i + 1] not in " \t\n" and
                  (i == 0 or text[i - 1] in " \t\n([{")):
                # Opening italic
                result.append("_")
                push_context(FormattingType.ITALIC, "_")
            else:
                # Isolated _, escape it
                result.append("\\_")
            i += 1
            continue

        # Single ~ should always be escaped (Claude uses ~~ for strikethrough,
        # which is handled above and converted to single ~)
        # A lone ~ in Claude's output is NOT intended as strikethrough
        if text[i] == "~" and text[i:i + 2] != "~~":
            if current_context() == FormattingType.STRIKETHROUGH:
                # Closing strikethrough opened by ~~
                result.append("~")
                pop_context(FormattingType.STRIKETHROUGH)
            else:
                # Lone ~ should be escaped, not treated as strikethrough
                result.append("\\~")
            i += 1
            continue

        # Check for link [text](url)
        if text[i] == "[":
            # Could be start of link text - remember position to fix if not a link
            bracket_pos = len(result)
            result.append("[")
            ctx = FormattingContext(format_type=FormattingType.LINK_TEXT,
                                    start_pos=bracket_pos,
                                    delimiter="[")
            context_stack.append(ctx)
            i += 1
            continue

        if text[i] == "]" and current_context() == FormattingType.LINK_TEXT:
            if i + 1 < n and text[i + 1] == "(":
                # Transition to URL
                result.append("](")
                pop_context(FormattingType.LINK_TEXT)
                push_context(FormattingType.LINK_URL, "](")
                i += 2
                continue
            # Not a link, just brackets - escape the opening [ we added earlier
            ctx = context_stack[-1]
            if ctx.start_pos < len(result):
                result[ctx.start_pos] = "\\["
            result.append("\\]")
            pop_context(FormattingType.LINK_TEXT)
            i += 1
            continue

        # Regular character - escape if needed
        char = text[i]
        if char in ESCAPE_CHARS_NORMAL:
            result.append("\\" + char)
        else:
            result.append(char)
        i += 1

    # Auto-close unclosed formatting (in reverse order)
    if auto_close:
        while context_stack:
            ctx = context_stack.pop()
            if ctx.format_type == FormattingType.CODE_BLOCK:
                # Add newline if needed before closing
                if result and result[-1] != "\n":
                    result.append("\n")
                result.append("```")
            elif ctx.format_type == FormattingType.CODE:
                result.append("`")
            elif ctx.format_type == FormattingType.BOLD:
                result.append("*")
            elif ctx.format_type == FormattingType.ITALIC:
                result.append("_")
            elif ctx.format_type == FormattingType.UNDERLINE:
                result.append("__")
            elif ctx.format_type == FormattingType.STRIKETHROUGH:
                result.append("~")
            elif ctx.format_type == FormattingType.SPOILER:
                result.append("||")
            elif ctx.format_type == FormattingType.LINK_TEXT:
                # Escape the opening [ we added earlier
                if ctx.start_pos < len(result):
                    result[ctx.start_pos] = "\\["
                result.append("\\]")
            elif ctx.format_type == FormattingType.LINK_URL:
                # Close the URL - add ) to complete the link
                result.append(")")

    return "".join(result)


def render_streaming_safe(text: str) -> str:
    r"""Render text as valid MarkdownV2 with auto-closing.

    Convenience function for streaming - always auto-closes unclosed
    formatting to ensure valid MarkdownV2 output.

    Args:
        text: Raw text (possibly incomplete during streaming).

    Returns:
        Valid MarkdownV2 string.

    Examples:
        >>> render_streaming_safe("Here's *bold te")
        "Here's *bold te*"
        >>> render_streaming_safe("```python\\nprint('hello")
        "```python\\nprint('hello\\n```"
    """
    return _render_markdown_v2(text, auto_close=True)


def format_expandable_blockquote_md2(content: str) -> str:
    r"""Format content as expandable blockquote in MarkdownV2.

    Telegram expandable blockquote syntax:
    - **> prefix on first line (empty bold entity as expandable marker)
    - > prefix on subsequent lines
    - || suffix on last line (expandability end marker)

    Args:
        content: Content for blockquote (will be escaped).

    Returns:
        MarkdownV2 expandable blockquote string.

    Examples:
        >>> format_expandable_blockquote_md2("Line 1\\nLine 2")
        '**>Line 1\\n>Line 2||'
    """
    if not content:
        return ""

    lines = content.split("\n")
    result: list[str] = []

    for i, line in enumerate(lines):
        # Escape the line content
        escaped = escape_markdown_v2(line.rstrip(), EscapeContext.NORMAL)

        if i == 0:
            # First line: **> (expandable marker)
            result.append(f"**>{escaped}")
        else:
            # Subsequent lines: just >
            result.append(f">{escaped}")

    # Add expandability end marker || to the last line
    return "\n".join(result) + "||"


def format_blockquote_md2(content: str) -> str:
    r"""Format content as regular blockquote in MarkdownV2.

    Args:
        content: Content for blockquote (will be escaped).

    Returns:
        MarkdownV2 blockquote string.

    Examples:
        >>> format_blockquote_md2("Line 1\\nLine 2")
        '>Line 1\\n>Line 2'
    """
    if not content:
        return ""

    lines = content.split("\n")
    result: list[str] = []

    for line in lines:
        escaped = escape_markdown_v2(line.rstrip(), EscapeContext.NORMAL)
        result.append(f">{escaped}")

    return "\n".join(result)


def calculate_escaped_length(text: str,
                             context: EscapeContext = EscapeContext.NORMAL
                            ) -> int:
    """Calculate length of text after escaping.

    Args:
        text: Raw text.
        context: Escaping context.

    Returns:
        Length after escaping.
    """
    return len(escape_markdown_v2(text, context))


def convert_standard_markdown(text: str) -> str:
    """Convert standard Markdown to Telegram MarkdownV2.

    Handles common differences:
    - **bold** -> *bold*
    - ~~strike~~ -> ~strike~
    - Escapes special characters

    This is a simpler alternative to full rendering when you just
    need basic conversion without streaming considerations.

    Args:
        text: Standard Markdown text.

    Returns:
        Telegram MarkdownV2 text.
    """
    return _render_markdown_v2(text, auto_close=True)
