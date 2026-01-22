"""Tests for render_latex tool.

Tests LaTeX to PNG rendering:
- Success flow (formula rendering)
- Parameter handling (display_mode, font_size)
- Error handling (invalid LaTeX, empty input)
- Output structure (_file_contents pattern)
"""

from unittest.mock import MagicMock

from core.tools.render_latex import format_render_latex_result
from core.tools.render_latex import render_latex
from core.tools.render_latex import RENDER_LATEX_TOOL
from core.tools.render_latex import TOOL_CONFIG
import pytest

# ============================================================================
# RENDER_LATEX_TOOL Schema Tests
# ============================================================================


class TestRenderLatexToolDefinition:
    """Tests for RENDER_LATEX_TOOL definition structure."""

    def test_tool_definition_structure(self):
        """Test RENDER_LATEX_TOOL has correct structure."""
        assert "name" in RENDER_LATEX_TOOL
        assert "description" in RENDER_LATEX_TOOL
        assert "input_schema" in RENDER_LATEX_TOOL

        assert RENDER_LATEX_TOOL["name"] == "render_latex"

    def test_input_schema_structure(self):
        """Test input schema has required fields."""
        schema = RENDER_LATEX_TOOL["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema

        assert set(schema["required"]) == {"latex"}

    def test_properties_defined(self):
        """Test all expected properties are defined."""
        properties = RENDER_LATEX_TOOL["input_schema"]["properties"]
        assert "latex" in properties
        assert "display_mode" in properties
        assert "font_size" in properties

    def test_display_mode_enum(self):
        """Test display_mode has correct enum values."""
        properties = RENDER_LATEX_TOOL["input_schema"]["properties"]
        assert "enum" in properties["display_mode"]
        assert set(properties["display_mode"]["enum"]) == {"inline", "display"}

    def test_tool_config_valid(self):
        """Test TOOL_CONFIG is properly configured."""
        assert TOOL_CONFIG.name == "render_latex"
        assert TOOL_CONFIG.emoji == "📐"
        assert TOOL_CONFIG.needs_bot_session is True
        assert TOOL_CONFIG.executor is render_latex
        assert TOOL_CONFIG.format_result is format_render_latex_result


# ============================================================================
# render_latex() Tests - Success Scenarios
# ============================================================================


class TestRenderLatexSuccess:
    """Tests for successful render_latex calls."""

    @pytest.mark.asyncio
    async def test_simple_fraction(self):
        """Test rendering a simple fraction."""
        result = await render_latex(
            latex=r"\frac{1}{2}",
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["success"] == "true"
        assert "_file_contents" in result
        assert len(result["_file_contents"]) == 1

        file_content = result["_file_contents"][0]
        assert "filename" in file_content
        assert file_content["filename"].startswith("formula_")
        assert file_content["filename"].endswith(".png")
        assert file_content["mime_type"] == "image/png"
        # PNG should be at least 1KB
        assert len(file_content["content"]) > 1000

    @pytest.mark.asyncio
    async def test_display_mode(self):
        """Test rendering with display mode."""
        result = await render_latex(
            latex=r"\sum_{i=1}^{n} i^2",
            bot=MagicMock(),
            session=MagicMock(),
            display_mode="display",
        )

        assert result["success"] == "true"
        assert "_file_contents" in result

    @pytest.mark.asyncio
    async def test_inline_mode_default(self):
        """Test that inline mode is default."""
        result = await render_latex(
            latex="x^2",
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["success"] == "true"

    @pytest.mark.asyncio
    async def test_custom_font_size(self):
        """Test rendering with custom font size."""
        result = await render_latex(
            latex="x^2 + y^2 = z^2",
            bot=MagicMock(),
            session=MagicMock(),
            font_size=32,
        )

        assert result["success"] == "true"
        assert "_file_contents" in result

    @pytest.mark.asyncio
    async def test_quadratic_formula(self):
        """Test rendering the quadratic formula."""
        result = await render_latex(
            latex=r"x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}",
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["success"] == "true"
        assert "_file_contents" in result

    @pytest.mark.asyncio
    async def test_greek_letters(self):
        """Test rendering Greek letters."""
        result = await render_latex(
            latex=r"\alpha + \beta = \gamma",
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["success"] == "true"

    @pytest.mark.asyncio
    async def test_integral(self):
        """Test rendering an integral."""
        result = await render_latex(
            latex=r"\int_0^{\infty} e^{-x^2} dx",
            bot=MagicMock(),
            session=MagicMock(),
            display_mode="display",
        )

        assert result["success"] == "true"

    @pytest.mark.asyncio
    async def test_sum_notation(self):
        """Test rendering sum notation."""
        result = await render_latex(
            latex=r"\sum_{n=0}^{\infty} \frac{x^n}{n!}",
            bot=MagicMock(),
            session=MagicMock(),
            display_mode="display",
        )

        assert result["success"] == "true"

    @pytest.mark.asyncio
    async def test_simple_power(self):
        """Test rendering simple power expression."""
        result = await render_latex(
            latex="x^2 + y^2",
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["success"] == "true"


# ============================================================================
# render_latex() Tests - Error Scenarios
# ============================================================================


class TestRenderLatexErrors:
    """Tests for render_latex error handling."""

    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Test that empty latex raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await render_latex(
                latex="",
                bot=MagicMock(),
                session=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_whitespace_only(self):
        """Test that whitespace-only latex raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            await render_latex(
                latex="   ",
                bot=MagicMock(),
                session=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_font_size_too_small(self):
        """Test that font_size below 12 raises ValueError."""
        with pytest.raises(ValueError, match="font_size must be between"):
            await render_latex(
                latex="x^2",
                bot=MagicMock(),
                session=MagicMock(),
                font_size=5,
            )

    @pytest.mark.asyncio
    async def test_font_size_too_large(self):
        """Test that font_size above 48 raises ValueError."""
        with pytest.raises(ValueError, match="font_size must be between"):
            await render_latex(
                latex="x^2",
                bot=MagicMock(),
                session=MagicMock(),
                font_size=100,
            )

    @pytest.mark.asyncio
    async def test_invalid_display_mode_defaults_to_inline(self):
        """Test that invalid display_mode defaults to inline."""
        result = await render_latex(
            latex="x^2",
            bot=MagicMock(),
            session=MagicMock(),
            display_mode="invalid",
        )

        # Should succeed with default inline mode
        assert result["success"] == "true"


# ============================================================================
# format_render_latex_result() Tests
# ============================================================================


class TestFormatRenderLatexResult:
    """Tests for format_render_latex_result function."""

    def test_format_success(self):
        """Test formatting successful result."""
        result = format_render_latex_result({"latex": "x^2"},
                                            {"success": "true"})

        assert "[📐 Formula rendered]" in result

    def test_format_error(self):
        """Test formatting error result."""
        result = format_render_latex_result({"latex": "invalid"}, {
            "success": "false",
            "error": "Invalid LaTeX syntax"
        })

        assert "Render error" in result
        assert "Invalid LaTeX" in result

    def test_format_error_long_message_truncated(self):
        """Test that long error messages are truncated."""
        long_error = "x" * 100
        result = format_render_latex_result({"latex": "test"}, {
            "success": "false",
            "error": long_error
        })

        # Should be truncated to 80 chars + ... + prefix
        assert "..." in result
        # Result should be shorter than full error + prefix
        assert len(result) < len(long_error) + 30


# ============================================================================
# Output File Format Tests
# ============================================================================


class TestOutputFileFormat:
    """Tests for output file format and structure."""

    @pytest.mark.asyncio
    async def test_filename_format(self):
        """Test that filename follows expected format."""
        result = await render_latex(
            latex="x^2",
            bot=MagicMock(),
            session=MagicMock(),
        )

        filename = result["_file_contents"][0]["filename"]
        # Should be formula_YYYYMMDD_HHMMSS.png
        assert filename.startswith("formula_")
        assert filename.endswith(".png")
        # Date part should be 8 digits
        date_part = filename[8:16]
        assert date_part.isdigit()

    @pytest.mark.asyncio
    async def test_mime_type(self):
        """Test that mime_type is image/png."""
        result = await render_latex(
            latex="x^2",
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["_file_contents"][0]["mime_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_content_is_bytes(self):
        """Test that content is bytes."""
        result = await render_latex(
            latex="x^2",
            bot=MagicMock(),
            session=MagicMock(),
        )

        content = result["_file_contents"][0]["content"]
        assert isinstance(content, bytes)

    @pytest.mark.asyncio
    async def test_content_is_valid_png(self):
        """Test that content starts with PNG magic bytes."""
        result = await render_latex(
            latex="x^2",
            bot=MagicMock(),
            session=MagicMock(),
        )

        content = result["_file_contents"][0]["content"]
        # PNG files start with these magic bytes
        png_magic = b'\x89PNG\r\n\x1a\n'
        assert content[:8] == png_magic
