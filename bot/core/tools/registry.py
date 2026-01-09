"""Tool registry and execution dispatcher (Phase 1.5).

This module provides centralized tool definitions and execution dispatcher
for Claude's tool use feature.

Currently implements:
- analyze_image: Analyze images using Claude Vision API
- analyze_pdf: Analyze PDF documents using Claude PDF API
- execute_python: Execute Python code via E2B sandbox
- web_search: Search the web (server-side, managed by Anthropic)
- web_fetch: Fetch web pages (server-side, managed by Anthropic)

NO __init__.py - use direct import:
    from core.tools.registry import TOOL_DEFINITIONS, execute_tool
"""

from typing import Any, Dict, List

from core.tools.analyze_image import analyze_image
from core.tools.analyze_image import ANALYZE_IMAGE_TOOL
from core.tools.analyze_pdf import analyze_pdf
from core.tools.analyze_pdf import ANALYZE_PDF_TOOL
from core.tools.execute_python import execute_python
from core.tools.execute_python import EXECUTE_PYTHON_TOOL
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Server-side tools (managed by Anthropic, no executor needed)
# Phase 1.5 Stage 4
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search"
    # Server-side tool: Anthropic executes searches automatically
    # Cost: $0.01 per search (tracked in usage.server_tool_use.web_search_requests)
    # No max_uses: Claude decides optimal search count
}

WEB_FETCH_TOOL = {
    "type": "web_fetch_20250910",
    "name": "web_fetch"
    # Server-side tool: Anthropic fetches URLs automatically
    # Cost: FREE (only tokens for fetched content)
    # Supports web pages and PDFs
}

# Tool definitions for Claude API (list of tool schemas)
TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    ANALYZE_IMAGE_TOOL,
    ANALYZE_PDF_TOOL,
    WEB_SEARCH_TOOL,
    WEB_FETCH_TOOL,
    EXECUTE_PYTHON_TOOL,
]

# Tool executors mapping (tool name -> execution function)
TOOL_EXECUTORS: Dict[str, Any] = {
    "analyze_image": analyze_image,
    "analyze_pdf": analyze_pdf,
    "execute_python": execute_python,
    # Server-side tools NOT included (managed by Anthropic):
    # "web_search": (server-side)
    # "web_fetch": (server-side)
}


async def execute_tool(tool_name: str, tool_input: Dict[str,
                                                        Any]) -> Dict[str, str]:
    """Execute a tool by name with given input.

    Dispatcher function that routes tool calls to appropriate executor.
    Handles errors and logging for all tool executions.

    Args:
        tool_name: Name of the tool to execute (e.g., "analyze_image",
            "analyze_pdf").
        tool_input: Tool input parameters as dictionary.

    Returns:
        Tool execution result as dictionary.
        For analyze_image: {"analysis": str, "tokens_used": str}
        For analyze_pdf: {"analysis": str, "tokens_used": str,
            "cached_tokens": str}
        For execute_python: {"stdout": str, "stderr": str, "results": str,
            "error": str, "success": str}

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
