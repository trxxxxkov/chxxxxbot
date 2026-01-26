"""Tests for render_latex tool.

Tests LaTeX to PNG rendering using pdflatex:
- Success flow (formula rendering with caching)
- Parameter handling (dpi)
- Error handling (invalid LaTeX, empty input)
- Output structure (output_files pattern with temp_id)
- TikZ diagram rendering
- Complex formulas (matrices, cases, align)
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from core.tools.render_latex import _sanitize_latex
from core.tools.render_latex import _wrap_in_document
from core.tools.render_latex import format_render_latex_result
from core.tools.render_latex import render_latex
from core.tools.render_latex import RENDER_LATEX_TOOL
from core.tools.render_latex import TOOL_CONFIG
import pytest

# ============================================================================
# _sanitize_latex() Tests
# ============================================================================


class TestSanitizeLatex:
    """Tests for _sanitize_latex function."""

    def test_removes_dollar_delimiters(self):
        """Test removal of $...$ delimiters."""
        result = _sanitize_latex(r"$x^2$")
        assert result == "x^2"

    def test_removes_double_dollar_delimiters(self):
        """Test removal of $$...$$ delimiters."""
        result = _sanitize_latex(r"$$\frac{1}{2}$$")
        assert result == r"\frac{1}{2}"

    def test_removes_bracket_delimiters(self):
        r"""Test removal of \[...\] delimiters."""
        result = _sanitize_latex(r"\[\sum_{i=1}^n i\]")
        assert result == r"\sum_{i=1}^n i"

    def test_removes_paren_delimiters(self):
        r"""Test removal of \(...\) delimiters."""
        result = _sanitize_latex(r"\(x + y\)")
        assert result == "x + y"

    def test_handles_newlines_in_input(self):
        """Test that leading/trailing newlines are stripped."""
        result = _sanitize_latex("\n$x^2$\n")
        assert result == "x^2"

    def test_strips_whitespace(self):
        """Test that whitespace is stripped."""
        result = _sanitize_latex("  x^2  ")
        assert result == "x^2"

    def test_no_delimiters_passes_through(self):
        """Test that clean input passes through unchanged."""
        result = _sanitize_latex(r"\frac{a}{b}")
        assert result == r"\frac{a}{b}"


# ============================================================================
# _wrap_in_document() Tests
# ============================================================================


class TestWrapInDocument:
    """Tests for _wrap_in_document function."""

    def test_wraps_simple_formula_in_math_mode(self):
        """Test wrapping simple formula in document with math mode."""
        result = _wrap_in_document(r"\frac{1}{2}")
        assert r"\documentclass" in result
        assert r"\usepackage{amsmath" in result
        assert r"\usepackage{tikz}" in result
        assert r"\begin{document}" in result
        assert r"\end{document}" in result
        # Should be wrapped in display math \[...\]
        assert r"\[\frac{1}{2}\]" in result

    def test_wraps_math_environments_in_math_mode(self):
        """Test that math environments like bmatrix are wrapped in math mode."""
        latex = r"\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}"
        result = _wrap_in_document(latex)
        # Should wrap in \[...\] since bmatrix is a math environment
        assert r"\[" + latex + r"\]" in result

    def test_does_not_wrap_tikz(self):
        """Test that TikZ pictures are not wrapped in math mode."""
        latex = r"\begin{tikzpicture}\node[draw] {Hello};\end{tikzpicture}"
        result = _wrap_in_document(latex)
        # Should NOT wrap in \[...\] since tikzpicture is self-contained
        assert r"\[" not in result
        assert latex in result

    def test_does_not_wrap_align(self):
        """Test that align environment is not wrapped in math mode."""
        latex = r"\begin{align} x &= 1 \\ y &= 2 \end{align}"
        result = _wrap_in_document(latex)
        # Should NOT wrap in \[...\] since align is a display math env
        assert r"\[" not in result
        assert latex in result

    def test_includes_tikz_libraries(self):
        """Test that TikZ libraries are included."""
        result = _wrap_in_document(r"\begin{tikzpicture}\end{tikzpicture}")
        assert r"\usetikzlibrary{" in result
        assert "arrows" in result
        assert "shapes" in result
        assert "positioning" in result

    def test_includes_pgfplots(self):
        """Test that pgfplots is included."""
        result = _wrap_in_document(r"\begin{tikzpicture}\end{tikzpicture}")
        assert r"\usepackage{pgfplots}" in result
        assert r"\pgfplotsset{compat=" in result


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
        assert "dpi" in properties

    def test_tool_config_valid(self):
        """Test TOOL_CONFIG is properly configured."""
        assert TOOL_CONFIG.name == "render_latex"
        assert TOOL_CONFIG.emoji == "📐"
        assert TOOL_CONFIG.needs_bot_session is True
        assert TOOL_CONFIG.executor is render_latex
        assert TOOL_CONFIG.format_result is format_render_latex_result

    def test_description_mentions_deliver_file(self):
        """Test that description mentions deliver_file workflow."""
        description = RENDER_LATEX_TOOL["description"]
        assert "deliver_file" in description
        assert "temp_id" in description


# ============================================================================
# render_latex() Tests - Success Scenarios with Mocked Cache
# ============================================================================


class TestRenderLatexWithMockedCache:
    """Tests for render_latex with mocked Redis cache."""

    @pytest.fixture
    def mock_store_exec_file(self):
        """Mock store_exec_file to return predictable metadata."""

        async def _store(filename,
                         content,
                         mime_type,
                         context,
                         execution_id,
                         thread_id=None):
            return {
                "temp_id": f"exec_{execution_id}_{filename}",
                "filename": filename,
                "size_bytes": len(content),
                "mime_type": mime_type,
                "preview": f"Image 200x100 (RGB), {len(content)/1024:.1f} KB",
                "context": context,
                "thread_id": thread_id,
            }

        return _store

    @pytest.mark.asyncio
    async def test_simple_fraction_returns_output_files(self,
                                                        mock_store_exec_file):
        """Test rendering a simple fraction returns output_files with temp_id."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex=r"\frac{1}{2}",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"
        assert "output_files" in result
        assert len(result["output_files"]) == 1
        assert "temp_id" in result["output_files"][0]
        assert "preview" in result["output_files"][0]
        assert "message" in result
        assert "deliver_file" in result["message"]

    @pytest.mark.asyncio
    async def test_quadratic_formula(self, mock_store_exec_file):
        """Test rendering the quadratic formula."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex=r"x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"
        assert "output_files" in result

    @pytest.mark.asyncio
    async def test_matrix_rendering(self, mock_store_exec_file):
        """Test rendering a matrix."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex=r"\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"
        assert "output_files" in result

    @pytest.mark.asyncio
    async def test_cases_environment(self, mock_store_exec_file):
        """Test rendering cases environment."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex=r"\begin{cases} x + y = 1 \\ x - y = 0 \end{cases}",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"

    @pytest.mark.asyncio
    async def test_tikz_simple_node(self, mock_store_exec_file):
        """Test rendering simple TikZ node."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex=
                r"\begin{tikzpicture}\node[draw] {Hello};\end{tikzpicture}",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"
        assert "output_files" in result

    @pytest.mark.asyncio
    async def test_align_environment(self, mock_store_exec_file):
        """Test rendering align environment."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex=r"\begin{align} x &= 1 \\ y &= 2 \end{align}",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"

    @pytest.mark.asyncio
    async def test_custom_dpi(self, mock_store_exec_file):
        """Test rendering with custom DPI."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex="x^2",
                bot=MagicMock(),
                session=MagicMock(),
                dpi=300,
            )

        assert result["success"] == "true"

    @pytest.mark.asyncio
    async def test_with_dollar_delimiters(self, mock_store_exec_file):
        """Test that rendering works even with $ delimiters."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex=r"$x^2 + y^2$",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"
        assert "output_files" in result

    @pytest.mark.asyncio
    async def test_includes_image_preview_for_claude(self,
                                                     mock_store_exec_file):
        """Test that result includes _image_preview for Claude to see."""
        with patch('core.tools.render_latex.store_exec_file',
                   new=mock_store_exec_file):
            result = await render_latex(
                latex=r"\frac{a}{b}",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"
        # Check for image preview (base64-encoded PNG for Claude)
        assert "_image_preview" in result
        assert "data" in result["_image_preview"]
        assert "media_type" in result["_image_preview"]
        assert result["_image_preview"]["media_type"] == "image/png"
        # Verify base64 data is not empty
        assert len(result["_image_preview"]["data"]) > 0
        # Verify message mentions visual review
        assert "Review the image" in result["message"]


# ============================================================================
# render_latex() Tests - Cache Fallback
# ============================================================================


class TestRenderLatexCacheFallback:
    """Tests for render_latex cache fallback behavior."""

    @pytest.mark.asyncio
    async def test_fallback_to_direct_delivery_on_cache_fail(self):
        """Test fallback to _file_contents when cache fails."""

        async def _store_fail(*args, **kwargs):
            return None  # Simulate cache failure

        with patch('core.tools.render_latex.store_exec_file', new=_store_fail):
            result = await render_latex(
                latex=r"\frac{1}{2}",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["success"] == "true"
        # Fallback to direct delivery
        assert "_file_contents" in result
        assert "output_files" not in result


# ============================================================================
# render_latex() Tests - Error Scenarios
# ============================================================================


class TestRenderLatexErrors:
    """Tests for render_latex error handling."""

    @pytest.mark.asyncio
    async def test_empty_input_returns_error(self):
        """Test that empty latex returns error dict."""
        result = await render_latex(
            latex="",
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["success"] == "false"
        assert "error" in result
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_error(self):
        """Test that whitespace-only latex returns error dict."""
        result = await render_latex(
            latex="   ",
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["success"] == "false"
        assert "error" in result

    @pytest.mark.asyncio
    async def test_invalid_dpi_uses_default(self):
        """Test that invalid dpi uses default value."""

        async def _store(filename,
                         content,
                         mime_type,
                         context,
                         execution_id,
                         thread_id=None):
            return {
                "temp_id": f"exec_{execution_id}_{filename}",
                "filename": filename,
                "size_bytes": len(content),
                "mime_type": mime_type,
                "preview": "test",
                "context": context,
                "thread_id": thread_id,
            }

        with patch('core.tools.render_latex.store_exec_file', new=_store):
            # Should not fail, just use default dpi
            result = await render_latex(
                latex="x^2",
                bot=MagicMock(),
                session=MagicMock(),
                dpi=1000,  # Invalid, should default to 200
            )

        assert result["success"] == "true"

    @pytest.mark.asyncio
    async def test_invalid_latex_syntax_returns_error(self):
        """Test that invalid LaTeX syntax returns error dict."""
        result = await render_latex(
            latex=r"\begin{invalid}",  # Unclosed environment
            bot=MagicMock(),
            session=MagicMock(),
        )

        assert result["success"] == "false"
        assert "error" in result


# ============================================================================
# format_render_latex_result() Tests
# ============================================================================


class TestFormatRenderLatexResult:
    """Tests for format_render_latex_result function."""

    def test_format_success_with_output_files(self):
        """Test formatting successful result with output_files."""
        result = format_render_latex_result(
            {"latex": "x^2"},
            {
                "success":
                    "true",
                "output_files": [{
                    "temp_id": "exec_abc_formula.png",
                    "preview": "Image 300x150 (RGB), 12.5 KB"
                }]
            },
        )

        assert "[📐 Formula rendered:" in result
        assert "300x150" in result

    def test_format_success_without_output_files(self):
        """Test formatting successful result without output_files (fallback)."""
        result = format_render_latex_result(
            {"latex": "x^2"},
            {
                "success": "true",
                "_file_contents": [{
                    "filename": "test.png"
                }]
            },
        )

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

        async def _store(filename,
                         content,
                         mime_type,
                         context,
                         execution_id,
                         thread_id=None):
            return {
                "temp_id": f"exec_{execution_id}_{filename}",
                "filename": filename,
                "size_bytes": len(content),
                "mime_type": mime_type,
                "preview": "test",
                "context": context,
            }

        with patch('core.tools.render_latex.store_exec_file', new=_store):
            result = await render_latex(
                latex="x^2",
                bot=MagicMock(),
                session=MagicMock(),
            )

        filename = result["output_files"][0]["filename"]
        # Should be formula_YYYYMMDD_HHMMSS.png
        assert filename.startswith("formula_")
        assert filename.endswith(".png")
        # Date part should be 8 digits
        date_part = filename[8:16]
        assert date_part.isdigit()

    @pytest.mark.asyncio
    async def test_mime_type_is_png(self):
        """Test that mime_type is image/png."""

        async def _store(filename,
                         content,
                         mime_type,
                         context,
                         execution_id,
                         thread_id=None):
            return {
                "temp_id": f"exec_{execution_id}_{filename}",
                "filename": filename,
                "size_bytes": len(content),
                "mime_type": mime_type,
                "preview": "test",
                "context": context,
            }

        with patch('core.tools.render_latex.store_exec_file', new=_store):
            result = await render_latex(
                latex="x^2",
                bot=MagicMock(),
                session=MagicMock(),
            )

        assert result["output_files"][0]["mime_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_temp_id_format(self):
        """Test that temp_id has expected format."""

        async def _store(filename,
                         content,
                         mime_type,
                         context,
                         execution_id,
                         thread_id=None):
            return {
                "temp_id": f"exec_{execution_id}_{filename}",
                "filename": filename,
                "size_bytes": len(content),
                "mime_type": mime_type,
                "preview": "test",
                "context": context,
            }

        with patch('core.tools.render_latex.store_exec_file', new=_store):
            result = await render_latex(
                latex="x^2",
                bot=MagicMock(),
                session=MagicMock(),
            )

        temp_id = result["output_files"][0]["temp_id"]
        assert temp_id.startswith("exec_")
        assert "formula_" in temp_id
        assert temp_id.endswith(".png")
