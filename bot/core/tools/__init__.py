"""Tools module for Claude tool use (Phase 1.5).

This module provides tool definitions and execution dispatcher for Claude's
tool use feature. Currently implements:
- analyze_image: Analyze images using Claude Vision API

Future tools (Phase 1.5):
- analyze_pdf: Analyze PDF documents
- web_search: Search the web
- web_fetch: Fetch web pages
- execute_python: Execute Python code via E2B

Tool architecture:
1. Each tool is a separate module with async function and TOOL definition
2. TOOL_DEFINITIONS list contains all tool schemas for Claude API
3. TOOL_EXECUTORS dict maps tool names to execution functions
4. execute_tool() dispatcher calls the appropriate tool function

NO __init__.py pattern - this file exists to export tools.
"""

from typing import Any, Dict, List

from core.tools.analyze_image import analyze_image
from core.tools.analyze_image import ANALYZE_IMAGE_TOOL
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Tool definitions for Claude API (list of tool schemas)
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    ANALYZE_IMAGE_TOOL,
    # Future tools will be added here:
    # ANALYZE_PDF_TOOL,
    # WEB_SEARCH_TOOL,
    # WEB_FETCH_TOOL,
    # EXECUTE_PYTHON_TOOL,
]

# Tool executors mapping (tool name -> execution function)
TOOL_EXECUTORS: Dict[str, Any] = {
    "analyze_image": analyze_image,
    # Future tools:
    # "analyze_pdf": analyze_pdf,
    # "web_search": web_search,
    # "web_fetch": web_fetch,
    # "execute_python": execute_python,
}


async def execute_tool(tool_name: str, tool_input: Dict[str,
                                                        Any]) -> Dict[str, str]:
    """Execute a tool by name with given input.

    Dispatcher function that routes tool calls to appropriate executor.
    Handles errors and logging for all tool executions.

    Args:
        tool_name: Name of the tool to execute (e.g., "analyze_image").
        tool_input: Tool input parameters as dictionary.

    Returns:
        Tool execution result as dictionary.
        For analyze_image: {"analysis": str, "tokens_used": str}

    Raises:
        ValueError: If tool_name not found in TOOL_EXECUTORS.
        Exception: If tool execution fails (re-raised from tool function).

    Examples:
        >>> result = await execute_tool(
        ...     tool_name="analyze_image",
        ...     tool_input={"claude_file_id": "file_abc...", "question": "What's this?"}
        ... )
        >>> print(result['analysis'])
    """
    logger.info("tools.execute_tool.called",
                tool_name=tool_name,
                tool_input_keys=list(tool_input.keys()))

    # Validate tool exists
    if tool_name not in TOOL_EXECUTORS:
        available_tools = ", ".join(TOOL_EXECUTORS.keys())
        error_msg = (f"Tool '{tool_name}' not found. "
                     f"Available tools: {available_tools}")
        logger.error("tools.execute_tool.not_found",
                     tool_name=tool_name,
                     available_tools=available_tools)
        raise ValueError(error_msg)

    # Get executor function
    executor = TOOL_EXECUTORS[tool_name]

    try:
        # Execute tool (all tools are async)
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
        # Re-raise to let handler decide what to do
        raise


__all__ = [
    "TOOL_DEFINITIONS",
    "TOOL_EXECUTORS",
    "execute_tool",
    "analyze_image",
    "ANALYZE_IMAGE_TOOL",
]
