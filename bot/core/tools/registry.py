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
- render_latex: Render LaTeX math formulas as PNG images
- execute_python: Execute Python code via E2B sandbox
- preview_file: Preview cached file content before delivery
- deliver_file: Deliver cached execution files to user
- web_search: Search the web (server-side, managed by Anthropic)
- web_fetch: Fetch web pages (server-side, managed by Anthropic)

NO __init__.py - use direct import:
    from core.tools.registry import TOOLS, execute_tool, get_tool_definitions
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import ToolValidationError
from core.tools.analyze_image import TOOL_CONFIG as ANALYZE_IMAGE_CONFIG
from core.tools.analyze_pdf import TOOL_CONFIG as ANALYZE_PDF_CONFIG
from core.tools.base import ToolConfig
from core.tools.deliver_file import TOOL_CONFIG as DELIVER_FILE_CONFIG
from core.tools.execute_python import TOOL_CONFIG as EXECUTE_PYTHON_CONFIG
from core.tools.extended_thinking import TOOL_CONFIG as EXTENDED_THINK_CONFIG
from core.tools.generate_image import TOOL_CONFIG as GENERATE_IMAGE_CONFIG
from core.tools.preview_file import TOOL_CONFIG as PREVIEW_FILE_CONFIG
from core.tools.render_latex import TOOL_CONFIG as RENDER_LATEX_CONFIG
from core.tools.self_critique import TOOL_CONFIG as SELF_CRITIQUE_CONFIG
from core.tools.transcribe_audio import TOOL_CONFIG as TRANSCRIBE_AUDIO_CONFIG
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Server-side tools (managed by Anthropic, no executor needed)
# These use ToolConfig with is_server_side=True
WEB_SEARCH_CONFIG = ToolConfig(
    name="web_search",
    definition={
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 100,  # Max searches per request
    },
    executor=None,
    emoji="🔍",
    is_server_side=True,
)

WEB_FETCH_CONFIG = ToolConfig(
    name="web_fetch",
    definition={
        "type": "web_fetch_20250910",
        "name": "web_fetch",
        "max_uses": 100,  # Max fetches per request
        "citations": {
            "enabled": True
        },
        "max_content_tokens": 100000,  # Protect against huge pages
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
    "render_latex": RENDER_LATEX_CONFIG,
    "execute_python": EXECUTE_PYTHON_CONFIG,
    "preview_file": PREVIEW_FILE_CONFIG,
    "deliver_file": DELIVER_FILE_CONFIG,
    "extended_thinking": EXTENDED_THINK_CONFIG,
    "self_critique": SELF_CRITIQUE_CONFIG,
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


async def _validate_file_type(
    tool: ToolConfig,
    tool_input: Dict[str, Any],
    session: 'AsyncSession',
) -> None:
    """Validate file MIME type matches tool requirements.

    Args:
        tool: Tool configuration with allowed_mime_prefixes.
        tool_input: Tool input parameters containing file ID.
        session: Database session for querying file metadata.

    Raises:
        ValueError: If file type doesn't match tool requirements.
    """
    if not tool.file_id_param or not tool.allowed_mime_prefixes:
        return  # No validation needed

    file_id = tool_input.get(tool.file_id_param)
    if not file_id:
        return  # Let the tool handle missing file ID

    # Import here to avoid circular imports
    from db.repositories.user_file_repository import UserFileRepository

    repo = UserFileRepository(session)
    user_file = await repo.get_by_claude_file_id(file_id)

    if not user_file:
        logger.info("tools.file_validation.not_found",
                    tool_name=tool.name,
                    claude_file_id=file_id)
        return  # Let the tool handle missing file

    # Check MIME type against allowed prefixes
    mime_type = user_file.mime_type or ""
    is_allowed = any(
        mime_type.startswith(prefix) for prefix in tool.allowed_mime_prefixes)

    if not is_allowed:
        allowed_str = ", ".join(tool.allowed_mime_prefixes)
        error_msg = (f"File type '{mime_type}' not supported by {tool.name}. "
                     f"Expected types starting with: {allowed_str}. "
                     f"File: {user_file.filename}")
        logger.info("tools.file_validation.wrong_type",
                    tool_name=tool.name,
                    claude_file_id=file_id,
                    mime_type=mime_type,
                    filename=user_file.filename,
                    allowed_prefixes=tool.allowed_mime_prefixes)
        raise ToolValidationError(error_msg, tool_name=tool.name)

    logger.debug("tools.file_validation.passed",
                 tool_name=tool.name,
                 mime_type=mime_type,
                 filename=user_file.filename)


async def execute_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> Dict[str, str]:
    """Execute a tool by name with given input.

    Dispatcher function that routes tool calls to appropriate executor.
    Handles errors and logging for all tool executions.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Tool input parameters as dictionary.
        bot: Telegram Bot instance for downloading user files.
        session: Database session for querying file metadata.
        thread_id: Optional thread ID for associating generated files
            with the conversation (used by execute_python, render_latex).
        user_id: Optional user ID for balance checks and cost tracking
            (required by self_critique).

    Returns:
        Tool execution result as dictionary.

    Raises:
        ValueError: If tool_name not found, is server-side tool,
            or file type validation fails.
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

    # Validate file type if tool has requirements
    await _validate_file_type(tool, tool_input, session)

    # Get executor
    executor = tool.executor
    if executor is None:
        raise ValueError(f"Tool '{tool_name}' has no executor")

    try:
        # Execute tool (all tools are async)
        if tool.needs_bot_session:
            # self_critique requires user_id for balance check and cost tracking
            if tool_name == "self_critique":
                if user_id is None:
                    raise ValueError(
                        "self_critique requires user_id for cost tracking")
                result = await executor(
                    bot=bot,
                    session=session,
                    thread_id=thread_id,
                    user_id=user_id,
                    on_subagent_tool=tool_input.pop("on_subagent_tool", None),
                    cancel_event=tool_input.pop("cancel_event", None),
                    **tool_input,
                )
            else:
                result = await executor(
                    bot=bot,
                    session=session,
                    thread_id=thread_id,
                    **tool_input,
                )
        else:
            result = await executor(**tool_input)

        logger.info("tools.execute_tool.success",
                    tool_name=tool_name,
                    result_keys=list(result.keys()))

        return result

    except Exception as e:
        # Log as info - external API errors handled correctly by our service
        logger.info("tools.execute_tool.external_error",
                    tool_name=tool_name,
                    error=str(e))
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
from core.tools.deliver_file import DELIVER_FILE_TOOL
from core.tools.execute_python import EXECUTE_PYTHON_TOOL
from core.tools.generate_image import GENERATE_IMAGE_TOOL
from core.tools.preview_file import PREVIEW_FILE_TOOL
from core.tools.render_latex import RENDER_LATEX_TOOL
from core.tools.transcribe_audio import TRANSCRIBE_AUDIO_TOOL

WEB_SEARCH_TOOL = WEB_SEARCH_CONFIG.definition
WEB_FETCH_TOOL = WEB_FETCH_CONFIG.definition
