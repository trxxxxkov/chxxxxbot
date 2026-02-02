"""Tool cost estimation for pre-check and analytics.

This module identifies which tools have external API costs and provides
cost estimation functions for logging and analytics purposes.

The main purpose is to enable balance pre-checks before executing
expensive tool calls, preventing users from going into large negative
balance.

Simple rule: If balance < 0, reject all paid tool calls.
"""

from decimal import Decimal
from typing import Any, Optional

# Tools that have API costs (external or Claude)
# If user balance < 0, these tools are blocked
PAID_TOOLS: set[str] = {
    "generate_image",  # Google Gemini: $0.134-0.240/image
    "transcribe_audio",  # OpenAI Whisper: $0.006/minute
    "web_search",  # Anthropic: $0.01/request
    "execute_python",  # E2B sandbox: $0.000036/second
    "analyze_image",  # Claude API: separate call for image analysis
    "analyze_pdf",  # Claude API: separate call for PDF analysis
    "preview_file",  # Claude Vision API for images/PDF (free for text)
    "deep_think",  # Claude API: Extended Thinking call
}

# Free tools (for reference, not used in checks)
# - render_latex: local pdflatex
# - web_fetch: server-side, no external API
# - deliver_file: file delivery only


def is_paid_tool(tool_name: str) -> bool:
    """Check if tool has external API costs.

    Args:
        tool_name: Name of the tool to check.

    Returns:
        True if the tool has external API costs, False otherwise.
    """
    return tool_name in PAID_TOOLS


def estimate_tool_cost(
    tool_name: str,
    tool_input: dict[str, Any],
    audio_duration_seconds: Optional[float] = None,
) -> Optional[Decimal]:
    """Estimate tool cost for logging and analytics.

    This is used for cost tracking and analytics, not for blocking
    decisions. The blocking decision is based solely on whether
    balance < 0 and tool is paid.

    Args:
        tool_name: Name of the tool.
        tool_input: Tool input parameters.
        audio_duration_seconds: For transcribe_audio, the duration in
            seconds. If not provided, estimates 5 minutes.

    Returns:
        Estimated cost in USD, or None for free tools.
    """
    if tool_name not in PAID_TOOLS:
        return None

    if tool_name == "generate_image":
        resolution = tool_input.get("resolution", "2k")
        return Decimal("0.240") if resolution == "4k" else Decimal("0.134")

    if tool_name == "transcribe_audio":
        # Estimate 5 minutes if duration unknown
        duration = audio_duration_seconds if audio_duration_seconds else 300
        minutes = Decimal(str(duration)) / 60
        return minutes * Decimal("0.006")

    if tool_name == "web_search":
        return Decimal("0.01")

    if tool_name == "execute_python":
        # Use timeout from input, default 3600 seconds (1 hour)
        timeout = tool_input.get("timeout", 3600)
        return Decimal(str(timeout)) * Decimal("0.000036")

    # analyze_image, analyze_pdf, preview_file (images/PDF):
    # Claude API cost depends on response tokens
    # Can't estimate upfront, actual cost calculated after call
    return None
