"""Tool registry and execution dispatcher (Phase 1.6+).

This module provides centralized tool definitions and execution dispatcher
for Claude's tool use feature.

Unified architecture using ToolConfig:
- Each tool module exports TOOL_CONFIG with all metadata
- Registry imports and consolidates into single TOOLS dict
- Helper functions use TOOLS as single source of truth

Currently implements:
- analyze_image: Analyze images using Claude Vision API
- analyze_pdf: Analyze PDF documents using Claude PDF API
- transcribe_audio: Transcribe audio/video using OpenAI Whisper API
- generate_image: Generate images using Google Gemini API
- execute_python: Execute Python code via E2B sandbox
- web_search: Search the web (server-side, managed by Anthropic)
- web_fetch: Fetch web pages (server-side, managed by Anthropic)

NO __init__.py - use direct import:
    from core.tools.registry import TOOLS, execute_tool, get_tool_definitions
"""

from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

from core.tools.analyze_image import TOOL_CONFIG as ANALYZE_IMAGE_CONFIG
from core.tools.analyze_pdf import TOOL_CONFIG as ANALYZE_PDF_CONFIG
from core.tools.base import ToolConfig
from core.tools.execute_python import TOOL_CONFIG as EXECUTE_PYTHON_CONFIG
from core.tools.generate_image import TOOL_CONFIG as GENERATE_IMAGE_CONFIG
from core.tools.transcribe_audio import TOOL_CONFIG as TRANSCRIBE_AUDIO_CONFIG
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Server-side tools (managed by Anthropic, no executor needed)
# These use ToolConfig with is_server_side=True
WEB_SEARCH_CONFIG = ToolConfig(
    name="web_search",
    definition={
        "type": "web_search_20250305",
        "name": "web_search"
    },
    executor=None,
    emoji="🔍",
    is_server_side=True,
)

WEB_FETCH_CONFIG = ToolConfig(
    name="web_fetch",
    definition={
        "type": "web_fetch_20250910",
        "name": "web_fetch"
    },
    executor=None,
    emoji="🌐",
    is_server_side=True,
)

# ============================================================================
# UNIFIED TOOLS REGISTRY - Single source of truth
# ============================================================================
# When adding a new tool:
# 1. Create TOOL_CONFIG in the tool module
# 2. Import it here
# 3. Add to TOOLS dict
# That's it! No other files need to be updated.
# ============================================================================

TOOLS: Dict[str, ToolConfig] = {
    "analyze_image": ANALYZE_IMAGE_CONFIG,
    "analyze_pdf": ANALYZE_PDF_CONFIG,
    "transcribe_audio": TRANSCRIBE_AUDIO_CONFIG,
    "generate_image": GENERATE_IMAGE_CONFIG,
    "execute_python": EXECUTE_PYTHON_CONFIG,
    "web_search": WEB_SEARCH_CONFIG,
    "web_fetch": WEB_FETCH_CONFIG,
}

# ============================================================================
# Helper functions - all derive from TOOLS
# ============================================================================


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Get all tool definitions for Claude API.

    Returns:
        List of tool schema dictionaries.
    """
    return [tool.definition for tool in TOOLS.values()]


def get_tool_emoji(tool_name: str) -> str:
    """Get emoji for a tool.

    Args:
        tool_name: Name of the tool.

    Returns:
        Emoji string, or default 🔧 if not found.
    """
    tool = TOOLS.get(tool_name)
    return tool.emoji if tool else "🔧"


def get_tool_system_message(
    tool_name: str,
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> str:
    """Get formatted system message for tool result.

    Args:
        tool_name: Name of the executed tool.
        tool_input: The input parameters passed to the tool.
        result: The result dictionary returned by the tool.

    Returns:
        Formatted message string, or empty string if no formatter.
    """
    tool = TOOLS.get(tool_name)
    if tool:
        return tool.get_system_message(tool_input, result)
    return ""


def is_server_side_tool(tool_name: str) -> bool:
    """Check if tool is server-side (managed by Anthropic).

    Args:
        tool_name: Name of the tool.

    Returns:
        True if server-side tool, False otherwise.
    """
    tool = TOOLS.get(tool_name)
    return tool.is_server_side if tool else False


async def execute_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    bot: 'Bot',
    session: 'AsyncSession',
) -> Dict[str, str]:
    """Execute a tool by name with given input.

    Dispatcher function that routes tool calls to appropriate executor.
    Handles errors and logging for all tool executions.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Tool input parameters as dictionary.
        bot: Telegram Bot instance for downloading user files.
        session: Database session for querying file metadata.

    Returns:
        Tool execution result as dictionary.

    Raises:
        ValueError: If tool_name not found or is server-side tool.
        Exception: If tool execution fails (re-raised from tool function).
    """
    logger.info("tools.execute_tool.called",
                tool_name=tool_name,
                tool_input_keys=list(tool_input.keys()))

    # Validate tool exists
    tool = TOOLS.get(tool_name)
    if not tool:
        available = ", ".join(TOOLS.keys())
        error_msg = f"Tool '{tool_name}' not found. Available: {available}"
        logger.error("tools.execute_tool.not_found",
                     tool_name=tool_name,
                     available_tools=available)
        raise ValueError(error_msg)

    # Server-side tools cannot be executed locally
    if tool.is_server_side:
        error_msg = f"Tool '{tool_name}' is server-side (managed by Anthropic)"
        logger.error("tools.execute_tool.server_side", tool_name=tool_name)
        raise ValueError(error_msg)

    # Get executor
    executor = tool.executor
    if executor is None:
        raise ValueError(f"Tool '{tool_name}' has no executor")

    try:
        # Execute tool (all tools are async)
        if tool.needs_bot_session:
            result = await executor(bot=bot, session=session, **tool_input)
        else:
            result = await executor(**tool_input)

        logger.info("tools.execute_tool.success",
                    tool_name=tool_name,
                    result_keys=list(result.keys()))

        return result

    except Exception as e:
        logger.error("tools.execute_tool.failed",
                     tool_name=tool_name,
                     error=str(e),
                     exc_info=True)
        raise


# ============================================================================
# Backward compatibility - deprecated, will be removed
# ============================================================================
# These are kept for compatibility with existing code.
# Use TOOLS dict and helper functions instead.

# Old-style definitions (deprecated)
TOOL_DEFINITIONS = get_tool_definitions()

TOOL_EXECUTORS = {
    name: tool.executor
    for name, tool in TOOLS.items()
    if not tool.is_server_side and tool.executor
}

TOOL_METADATA = {
    name: {
        "needs_bot_session": tool.needs_bot_session
    } for name, tool in TOOLS.items() if not tool.is_server_side
}

# Re-export individual tool definitions for backward compatibility
from core.tools.analyze_image import ANALYZE_IMAGE_TOOL
from core.tools.analyze_pdf import ANALYZE_PDF_TOOL
from core.tools.execute_python import EXECUTE_PYTHON_TOOL
from core.tools.generate_image import GENERATE_IMAGE_TOOL
from core.tools.transcribe_audio import TRANSCRIBE_AUDIO_TOOL

WEB_SEARCH_TOOL = WEB_SEARCH_CONFIG.definition
WEB_FETCH_TOOL = WEB_FETCH_CONFIG.definition
