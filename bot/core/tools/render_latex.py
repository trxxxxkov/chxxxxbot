"""Render LaTeX formulas as PNG images.

This module implements the render_latex tool for converting LaTeX math
expressions into PNG images that are sent to Telegram users.

Uses matplotlib's mathtext renderer which supports a subset of LaTeX
without requiring a full LaTeX installation.

NO __init__.py - use direct import:
    from core.tools.render_latex import render_latex, RENDER_LATEX_TOOL
"""

import asyncio
from datetime import datetime
from datetime import UTC
from io import BytesIO
from typing import Any, Dict, TYPE_CHECKING

from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Tool definition for Claude API
RENDER_LATEX_TOOL = {
    "name":
        "render_latex",
    "description":
        """Render LaTeX math formulas as PNG images.

<purpose>
Convert LaTeX mathematical expressions into high-quality PNG images.
Use when Telegram's text formatting cannot display formulas properly.
Images are auto-delivered to the user.
</purpose>

<when_to_use>
USE this tool for:
- Complex mathematical formulas with fractions, integrals, sums
- Equations with multiple levels of subscripts/superscripts
- Matrix notation and linear algebra expressions
- Formulas with special symbols not available in Unicode
- Any math that would look broken in plain text

DO NOT USE for:
- Simple expressions that work in Unicode (x², a/b, Greek letters)
- Single symbols or very short expressions
- Non-math content
</when_to_use>

<latex_syntax>
Input should be LaTeX math syntax WITHOUT delimiters:
- Correct: "\\frac{1}{2} + \\sqrt{x}"
- Incorrect: "$\\frac{1}{2}$" (no $ delimiters needed)
- Incorrect: "\\[\\frac{1}{2}\\]" (no \\[ delimiters needed)

Supported commands (mathtext subset):
- Fractions: \\frac{a}{b}
- Roots: \\sqrt{x}, \\sqrt[n]{x}
- Powers/indices: x^2, x_i, x^{n+1}_{i,j}
- Greek: \\alpha, \\beta, \\gamma, \\Gamma, \\pi, \\Phi, \\omega
- Operators: \\sum, \\prod, \\int, \\lim, \\infty
- Relations: \\neq, \\leq, \\geq, \\approx, \\equiv
- Accents: \\hat{x}, \\bar{x}, \\vec{v}, \\dot{x}
- Delimiters: \\left( \\right), \\left[ \\right]
- Sets: \\in, \\subset, \\cup, \\cap, \\emptyset
- Functions: \\sin, \\cos, \\tan, \\log, \\ln, \\exp
- Spaces: \\quad, \\qquad, \\, \\;
</latex_syntax>

<display_mode>
- "inline": Compact rendering (default), good for formulas in text context
- "display": Larger rendering with limits above/below sums/integrals
</display_mode>

<examples>
Simple fraction:
  latex="\\frac{a}{b}"

Quadratic formula:
  latex="x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}"

Sum notation:
  latex="\\sum_{i=1}^{n} i^2 = \\frac{n(n+1)(2n+1)}{6}"
  display_mode="display"

Integral:
  latex="\\int_0^{\\infty} e^{-x^2} dx = \\frac{\\sqrt{\\pi}}{2}"
  display_mode="display"

Taylor series:
  latex="e^x = \\sum_{n=0}^{\\infty} \\frac{x^n}{n!}"
  display_mode="display"
</examples>

<cost>
FREE - local rendering with matplotlib, no external API calls.
</cost>""",
    "input_schema": {
        "type": "object",
        "properties": {
            "latex": {
                "type":
                    "string",
                "description":
                    ("LaTeX math expression WITHOUT delimiters. "
                     "Example: '\\\\frac{1}{2}' not '$\\\\frac{1}{2}$'")
            },
            "display_mode": {
                "type":
                    "string",
                "enum": ["inline", "display"],
                "description":
                    ("'inline' for compact (default), 'display' for larger "
                     "rendering with limits above/below operators.")
            },
            "font_size": {
                "type":
                    "integer",
                "description":
                    ("Font size in points (12-48). Default: 20. "
                     "Increase for complex formulas or better readability.")
            }
        },
        "required": ["latex"]
    }
}


def _render_sync(latex: str, display_mode: str, font_size: int) -> bytes:
    """Synchronous LaTeX rendering using matplotlib.

    Called via asyncio.to_thread() to avoid blocking event loop.

    Args:
        latex: LaTeX math expression.
        display_mode: 'inline' or 'display'.
        font_size: Font size in points.

    Returns:
        PNG image bytes.

    Raises:
        ValueError: If LaTeX syntax is invalid.
    """
    import matplotlib
    matplotlib.use('Agg')  # Headless mode - no GUI
    import matplotlib.pyplot as plt

    # Configure matplotlib for math rendering
    plt.rcParams.update({
        'mathtext.fontset': 'cm',  # Computer Modern (LaTeX-like font)
        'font.size': font_size,
    })

    # Create figure with minimal size (will be auto-adjusted)
    fig, ax = plt.subplots(figsize=(0.01, 0.01))
    ax.set_axis_off()

    # Format LaTeX string
    # Note: \displaystyle is not supported by mathtext, so we just use
    # larger font for display mode (handled via font_size parameter)
    latex_str = f"${latex}$"

    # Render text
    try:
        text = ax.text(0.5,
                       0.5,
                       latex_str,
                       transform=ax.transAxes,
                       fontsize=font_size,
                       ha='center',
                       va='center')
    except ValueError as e:
        plt.close(fig)
        raise ValueError(f"Invalid LaTeX syntax: {e}") from e

    # Auto-size figure to fit text
    fig.tight_layout(pad=0.1)
    renderer = fig.canvas.get_renderer()
    bbox = text.get_window_extent(renderer)

    dpi = 300
    width_inches = bbox.width / dpi + 0.15
    height_inches = bbox.height / dpi + 0.15

    # Minimum size to avoid tiny images
    width_inches = max(width_inches, 0.5)
    height_inches = max(height_inches, 0.3)

    fig.set_size_inches(width_inches, height_inches)

    # Save to buffer
    buffer = BytesIO()
    fig.savefig(buffer,
                format='png',
                dpi=dpi,
                bbox_inches='tight',
                pad_inches=0.05,
                facecolor='white',
                edgecolor='none',
                transparent=False)
    plt.close(fig)

    buffer.seek(0)
    return buffer.read()


async def render_latex(
    latex: str,
    bot: 'Bot',
    session: 'AsyncSession',
    display_mode: str = "inline",
    font_size: int = 20,
) -> Dict[str, Any]:
    """Render LaTeX formula as PNG image.

    Args:
        latex: LaTeX math expression (without delimiters).
        bot: Telegram Bot instance (unused, for interface consistency).
        session: Database session (unused, for interface consistency).
        display_mode: 'inline' (compact) or 'display' (larger).
        font_size: Font size in points (12-48).

    Returns:
        Dictionary with rendering result:
        {
            "success": "true",
            "_file_contents": [{
                "filename": "formula_YYYYMMDD_HHMMSS.png",
                "content": bytes,
                "mime_type": "image/png"
            }]
        }

    Raises:
        ValueError: If latex is empty or font_size out of range.
    """
    # Mark as unused for pylint
    _ = bot
    _ = session

    logger.info("tools.render_latex.called",
                latex_length=len(latex),
                display_mode=display_mode,
                font_size=font_size)

    # Validate input
    if not latex or not latex.strip():
        raise ValueError("LaTeX expression cannot be empty")

    if not 12 <= font_size <= 48:
        raise ValueError("font_size must be between 12 and 48")

    if display_mode not in ("inline", "display"):
        display_mode = "inline"

    # For display mode, increase font size if using default
    # This makes sums/integrals more readable
    if display_mode == "display" and font_size == 20:
        font_size = 28

    try:
        # Render in thread pool to avoid blocking
        image_bytes = await asyncio.to_thread(_render_sync, latex.strip(),
                                              display_mode, font_size)

        filename = f"formula_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.png"

        logger.info("tools.render_latex.success",
                    latex_preview=latex[:50],
                    image_size=len(image_bytes),
                    filename=filename)

        return {
            "success":
                "true",
            "_file_contents": [{
                "filename": filename,
                "content": image_bytes,
                "mime_type": "image/png"
            }]
        }

    except ValueError as e:
        logger.warning("tools.render_latex.syntax_error",
                       latex_preview=latex[:50],
                       error=str(e))
        return {"success": "false", "error": str(e)}
    except Exception as e:
        logger.error("tools.render_latex.failed",
                     latex_preview=latex[:50],
                     error=str(e),
                     exc_info=True)
        raise


def format_render_latex_result(
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> str:
    """Format render_latex result for user display.

    Args:
        tool_input: The input parameters (latex, display_mode, font_size).
        result: The result dictionary.

    Returns:
        Formatted system message string.
    """
    _ = tool_input  # Mark as unused
    if result.get("success") == "true":
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
