"""Render LaTeX formulas as PNG images using pdflatex.

This module implements the render_latex tool for converting LaTeX code
into PNG images. Supports full LaTeX including TikZ diagrams, complex
matrices, and all standard packages.

Uses pdflatex + pdf2image for rendering. Images are cached in Redis
so the model can review the preview and decide whether to deliver
to the user via deliver_file tool.

NO __init__.py - use direct import:
    from core.tools.render_latex import render_latex, RENDER_LATEX_TOOL
"""

import asyncio
import base64
from datetime import datetime
from datetime import UTC
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Dict, Optional, TYPE_CHECKING
import uuid

from cache.exec_cache import store_exec_file
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def _sanitize_latex(latex: str) -> str:
    """Sanitize LaTeX input by removing delimiters and extracting from documents.

    Claude sometimes passes LaTeX with delimiters or as full documents despite
    instructions. This function cleans the input to ensure successful rendering.

    Args:
        latex: Raw LaTeX input that may contain delimiters or be a full document.

    Returns:
        Cleaned LaTeX content without delimiters.
    """
    result = latex.strip()

    # Extract content from full documents (Claude sometimes passes these)
    # This ensures we get cropped formulas instead of full pages
    if r'\documentclass' in result and r'\begin{document}' in result:
        begin_idx = result.find(r'\begin{document}')
        end_idx = result.find(r'\end{document}')
        if begin_idx != -1 and end_idx != -1:
            # Extract content between \begin{document} and \end{document}
            content_start = begin_idx + len(r'\begin{document}')
            result = result[content_start:end_idx].strip()
            logger.debug(
                "render_latex.extracted_from_document",
                original_length=len(latex),
                extracted_length=len(result),
            )

    # Remove display math delimiters: \[...\] or $$...$$
    if result.startswith(r'\[') and result.endswith(r'\]'):
        result = result[2:-2].strip()
    elif result.startswith('$$') and result.endswith('$$'):
        result = result[2:-2].strip()

    # Remove inline math delimiters: \(...\) or $...$
    if result.startswith(r'\(') and result.endswith(r'\)'):
        result = result[2:-2].strip()
    elif result.startswith('$') and result.endswith(
            '$') and not result.startswith('$$'):
        result = result[1:-1].strip()

    return result


def _wrap_in_document(latex: str) -> str:
    """Wrap LaTeX fragment in minimal standalone document.

    Args:
        latex: LaTeX code fragment (math, tikz, etc.).

    Returns:
        Complete LaTeX document ready for compilation.
    """
    # Environments that provide their own context (no math wrapping needed)
    # - TikZ/drawing environments
    # - Top-level display math environments (align, equation, etc.)
    # - Document structure environments
    self_contained_environments = (
        # Drawing
        'tikzpicture',
        'pgfpicture',
        # Display math environments (amsmath) - already in math mode
        'align',
        'align*',
        'equation',
        'equation*',
        'gather',
        'gather*',
        'multline',
        'multline*',
        'flalign',
        'flalign*',
        'alignat',
        'alignat*',
        'eqnarray',
        'eqnarray*',
        # Document structure
        'document',
        'figure',
        'table',
        'minipage',
        'center',
        'flushleft',
        'flushright',
        'itemize',
        'enumerate',
        'description',
        'verbatim',
        'lstlisting',
        'tabular',
    )

    # Check if content contains a self-contained environment
    needs_math_wrap = True
    for env in self_contained_environments:
        if rf'\begin{{{env}}}' in latex:
            needs_math_wrap = False
            break

    # Math expressions and inline math environments (cases, bmatrix, etc.)
    # need to be wrapped in display math \[...\]
    if needs_math_wrap:
        latex = r'\[' + latex + r'\]'

    # Check if content contains Cyrillic characters
    has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in latex)

    # Build preamble based on content
    preamble = r'''\documentclass[preview,border=2pt]{standalone}
\usepackage[utf8]{inputenc}
'''

    # Add Cyrillic support if needed
    if has_cyrillic:
        preamble += r'''\usepackage[T2A]{fontenc}
\usepackage[russian]{babel}
'''
    else:
        preamble += r'\usepackage[T1]{fontenc}' + '\n'

    preamble += r'''\usepackage{amsmath,amssymb,amsfonts}
\usepackage{tikz}
\usetikzlibrary{arrows,shapes,positioning,calc,decorations.pathmorphing}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\usepackage[svgnames,x11names]{xcolor}
\usepackage{array,booktabs,multirow}
'''

    return preamble + r'\begin{document}' + '\n' + latex + '\n' + r'\end{document}'


def _render_pdflatex(latex: str, dpi: int = 200) -> bytes:
    """Render LaTeX to PNG using pdflatex + pdf2image.

    Supports:
    - TikZ diagrams
    - Complex matrices (bmatrix, pmatrix, etc.)
    - Multi-line equations (align, cases, etc.)
    - All standard LaTeX packages

    Args:
        latex: LaTeX code to render.
        dpi: Resolution in dots per inch (150-300).

    Returns:
        PNG image bytes.

    Raises:
        ValueError: If LaTeX compilation fails.
    """
    # Import here to avoid startup overhead
    from pdf2image import \
        convert_from_path  # pylint: disable=import-outside-toplevel
    from PIL import Image  # pylint: disable=import-outside-toplevel

    # Wrap in document if not already a full document
    if r'\documentclass' not in latex:
        latex = _wrap_in_document(latex)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        tex_file = tmpdir_path / 'formula.tex'
        pdf_file = tmpdir_path / 'formula.pdf'

        tex_file.write_text(latex, encoding='utf-8')

        # Run pdflatex with timeout
        try:
            result = subprocess.run(
                [
                    'pdflatex',
                    '-interaction=nonstopmode',
                    '-halt-on-error',
                    '-output-directory',
                    str(tmpdir_path),
                    str(tex_file),
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ValueError("LaTeX compilation timed out (30s limit)") from e

        if not pdf_file.exists():
            # Extract error message from log
            log_file = tmpdir_path / 'formula.log'
            error_msg = "Unknown compilation error"
            if log_file.exists():
                log_content = log_file.read_text(encoding='utf-8',
                                                 errors='ignore')
                # Find error lines
                error_lines = []
                for line in log_content.split('\n'):
                    if line.startswith('!') or 'Error' in line:
                        error_lines.append(line.strip())
                if error_lines:
                    error_msg = '; '.join(error_lines[:3])
            raise ValueError(f"LaTeX compilation failed: {error_msg}")

        # Convert PDF to PNG
        try:
            images = convert_from_path(
                str(pdf_file),
                dpi=dpi,
                fmt='png',
            )
        except Exception as e:
            raise ValueError(f"PDF to PNG conversion failed: {e}") from e

        if not images:
            raise ValueError("No pages generated from PDF")

        # Save first page to bytes
        buffer = BytesIO()
        images[0].save(buffer, format='PNG', optimize=True)
        buffer.seek(0)
        return buffer.read()


def _generate_render_temp_id(filename: str) -> str:
    """Generate unique temporary ID for render output file.

    Args:
        filename: Original filename (e.g., "formula.png").

    Returns:
        Temporary ID (e.g., "render_a1b2c3d4_formula.png").
    """
    short_uuid = uuid.uuid4().hex[:8]
    return f"render_{short_uuid}_{filename}"


# Tool definition for Claude API
RENDER_LATEX_TOOL = {
    "name":
        "render_latex",
    "description":
        """Render LaTeX to PNG image (supports full LaTeX including TikZ).

<purpose>
Convert LaTeX code into PNG images. Supports complex formulas, matrices,
TikZ diagrams, and all standard LaTeX packages.
Images are cached - use deliver_file to send to user after reviewing preview.
</purpose>

<capabilities>
- Math: fractions, integrals, sums, limits, matrices
- Matrices: bmatrix, pmatrix, vmatrix, cases, align
- TikZ: diagrams, graphs, flowcharts, plots
- Packages: amsmath, amssymb, tikz, pgfplots, xcolor
</capabilities>

<workflow>
1. Call render_latex with LaTeX code
2. IMPORTANT: You will SEE the actual rendered image in the response
3. Visually verify the formula/diagram looks correct
4. If issues found, re-render with LaTeX corrections
5. Call deliver_file(temp_id='...') to send to user
</workflow>

<input_format>
Either:
- LaTeX fragment (auto-wrapped in document): "\\frac{a}{b}"
- Full document with \\documentclass: "\\documentclass..."

Delimiters ($, $$, \\[, \\]) are auto-stripped.
</input_format>

<examples>
Simple fraction:
  latex="\\frac{a}{b}"

Matrix:
  latex="\\begin{bmatrix} 1 & 2 \\\\ 3 & 4 \\end{bmatrix}"

TikZ diagram:
  latex="\\begin{tikzpicture}\\node[draw] {Hello};\\end{tikzpicture}"

System of equations:
  latex="\\begin{cases} x + y = 1 \\\\ x - y = 0 \\end{cases}"

Quadratic formula:
  latex="x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}"
</examples>

<cost>
FREE - local rendering (no external API).
</cost>""",
    "input_schema": {
        "type": "object",
        "properties": {
            "latex": {
                "type":
                    "string",
                "description":
                    "LaTeX code to render (fragment or full document)"
            },
            "dpi": {
                "type":
                    "integer",
                "description":
                    "Resolution: 150 (fast), 200 (default), 300 (high quality)"
            }
        },
        "required": ["latex"]
    }
}


async def render_latex(
    latex: str,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    dpi: int = 200,
) -> Dict[str, Any]:
    """Render LaTeX to PNG and cache for model-decided delivery.

    Args:
        latex: LaTeX code to render (fragment or full document).
        bot: Telegram Bot instance (unused, for interface consistency).
        session: Database session (unused, for interface consistency).
        thread_id: Thread ID for associating file with conversation.
        dpi: Resolution in dots per inch (150-300, default 200).

    Returns:
        Dictionary with rendering result:
        - On success with cache:
            {
                "success": "true",
                "output_files": [{
                    "temp_id": "render_abc123_formula.png",
                    "filename": "formula_YYYYMMDD_HHMMSS.png",
                    "size_bytes": 12345,
                    "mime_type": "image/png",
                    "preview": "Image 400x200 (RGB), 12.3 KB"
                }],
                "message": "Rendered LaTeX formula. Use deliver_file..."
            }
        - On success without cache (fallback):
            {
                "success": "true",
                "_file_contents": [...]
            }
        - On failure:
            {
                "success": "false",
                "error": "..."
            }

    Raises:
        ValueError: If latex is empty or dpi out of range.
    """
    # Mark unused for pylint
    _ = bot
    _ = session

    logger.info("tools.render_latex.called", latex_length=len(latex), dpi=dpi)

    # Validate input
    if not latex or not latex.strip():
        return {"success": "false", "error": "LaTeX expression cannot be empty"}

    if not 150 <= dpi <= 300:
        dpi = 200  # Use default for invalid values

    # Sanitize input (remove delimiters)
    clean_latex = _sanitize_latex(latex)

    logger.debug("tools.render_latex.sanitized",
                 original_length=len(latex),
                 clean_length=len(clean_latex),
                 clean_preview=clean_latex[:100] if clean_latex else "")

    try:
        # Render in thread pool to avoid blocking event loop
        image_bytes = await asyncio.to_thread(
            _render_pdflatex,
            clean_latex,
            dpi,
        )

        # Generate filename with timestamp
        filename = f"formula_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.png"

        # Generate preview
        from PIL import Image  # pylint: disable=import-outside-toplevel
        img = Image.open(BytesIO(image_bytes))
        size_kb = len(image_bytes) / 1024
        preview = f"Image {img.width}x{img.height} ({img.mode}), {size_kb:.1f} KB"

        # Generate temp_id for cache
        temp_id = _generate_render_temp_id(filename)

        # Truncate LaTeX for context (max 200 chars)
        latex_context = clean_latex[:200] + ("..."
                                             if len(clean_latex) > 200 else "")

        # Store in Redis cache for model-decided delivery
        metadata = await store_exec_file(
            filename=filename,
            content=image_bytes,
            mime_type="image/png",
            context=f"LaTeX: {latex_context}",
            execution_id=temp_id.split('_')[1],  # uuid part
            thread_id=thread_id,
        )

        if metadata is None:
            # Fallback: direct delivery if cache fails (graceful degradation)
            logger.info("tools.render_latex.cache_failed_fallback",
                        filename=filename)
            # Truncate LaTeX for context (max 200 chars)
            latex_context = clean_latex[:200] + ("..." if len(clean_latex) > 200
                                                 else "")
            return {
                "success":
                    "true",
                "_file_contents": [{
                    "filename": filename,
                    "content": image_bytes,
                    "mime_type": "image/png",
                    "context": f"LaTeX: {latex_context}"
                }]
            }

        # Use the temp_id from metadata (generated by store_exec_file)
        actual_temp_id = metadata["temp_id"]

        logger.info("tools.render_latex.success",
                    latex_preview=clean_latex[:50],
                    image_size=len(image_bytes),
                    filename=filename,
                    temp_id=actual_temp_id,
                    preview=preview)

        # Encode image as base64 for Claude to see the preview
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        return {
            "success":
                "true",
            "output_files": [{
                "temp_id": actual_temp_id,
                "filename": filename,
                "size_bytes": len(image_bytes),
                "mime_type": "image/png",
                "preview": preview,
            }],
            # Image preview for Claude to visually verify before delivery
            "_image_preview": {
                "data": image_base64,
                "media_type": "image/png",
            },
            "message": (f"Rendered LaTeX formula. Preview: {preview}. "
                        f"Review the image above. If it looks correct, use "
                        f"deliver_file(temp_id='{actual_temp_id}') to send. "
                        "If not, re-render with corrections.")
        }

    except ValueError as e:
        # User LaTeX syntax error - not a code bug
        logger.info("tools.render_latex.compilation_error",
                    latex_preview=clean_latex[:50],
                    error=str(e))
        return {"success": "false", "error": str(e)}
    except Exception as e:
        # LaTeX rendering failures are usually invalid input, not internal bugs
        logger.info("tools.render_latex.failed",
                    latex_preview=clean_latex[:50] if clean_latex else "",
                    error=str(e))
        return {"success": "false", "error": f"Rendering failed: {str(e)}"}


def format_render_latex_result(
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> str:
    """Format render_latex result for user display.

    Args:
        tool_input: The input parameters (latex, dpi).
        result: The result dictionary.

    Returns:
        Formatted system message string.
    """
    _ = tool_input  # Mark as unused
    if result.get("success") == "true":
        if "output_files" in result:
            # Cached - model will decide to deliver
            preview = result["output_files"][0].get("preview", "")
            return f"[📐 Formula rendered: {preview}]"
        else:
            # Direct delivery (fallback)
            return "[📐 Formula rendered]"

    error = result.get("error", "unknown error")
    preview = error[:80] + "..." if len(error) > 80 else error
    return f"[❌ Render error: {preview}]"


# Unified tool configuration
from core.tools.base import ToolConfig  # pylint: disable=wrong-import-position

TOOL_CONFIG = ToolConfig(
    name="render_latex",
    definition=RENDER_LATEX_TOOL,
    executor=render_latex,
    emoji="📐",
    needs_bot_session=True,
    format_result=format_render_latex_result,
)
