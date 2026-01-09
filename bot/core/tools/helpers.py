"""Helper functions for tool use integration.

This module provides utility functions for:
- Retrieving available files for a thread
- Formatting files list for system prompt
- Extracting tool use blocks from Claude responses
- Formatting tool results for API

NO __init__.py - use direct import:
    from core.tools.helpers import get_available_files
"""

from datetime import datetime
import json
from typing import Any, Dict, List

import anthropic
from db.repositories.user_file_repository import UserFileRepository
from utils.structured_logging import get_logger

logger = get_logger(__name__)


async def get_available_files(thread_id: int,
                              user_file_repo: UserFileRepository) -> List[Any]:
    """Get all available files for a thread.

    Retrieves files from user_files table that belong to messages in
    this thread. Files are used for tool selection and system prompt.

    Args:
        thread_id: Internal thread ID from threads table.
        user_file_repo: UserFileRepository instance.

    Returns:
        List of UserFile instances (may be empty).

    Examples:
        >>> files = await get_available_files(thread_id=42, user_file_repo=repo)
        >>> if files:
        ...     print(f"Found {len(files)} files")
    """
    logger.debug("tools.helpers.get_available_files.calling_repo",
                 thread_id=thread_id,
                 repo_type=type(user_file_repo).__name__)

    files = await user_file_repo.get_by_thread_id(thread_id)

    logger.info("tools.helpers.get_available_files",
                thread_id=thread_id,
                file_count=len(files))

    return files


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Formatted size string (e.g., '1.5 MB').

    Examples:
        >>> format_size(1500000)
        '1.4 MB'
    """
    size: float = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_time_ago(dt: datetime) -> str:
    """Format datetime as 'X ago' string.

    Args:
        dt: Datetime to format.

    Returns:
        Human-readable time ago string.

    Examples:
        >>> format_time_ago(datetime.utcnow() - timedelta(minutes=5))
        '5 min ago'
    """
    now = datetime.utcnow()
    delta = now - dt

    if delta.days > 0:
        return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
    if delta.seconds >= 3600:
        hours = delta.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    if delta.seconds >= 60:
        minutes = delta.seconds // 60
        return f"{minutes} min ago"
    return "just now"


def format_files_section(files: List[Any]) -> str:
    """Format available files list for system prompt.

    Creates a formatted section listing all available files with their
    metadata. Included in system prompt when files are present.

    Args:
        files: List of UserFile instances.

    Returns:
        Formatted string for system prompt (empty if no files).

    Examples:
        >>> section = format_files_section(files)
        >>> print(section)
        Available files in this conversation:
        - photo.jpg (image, 1.2 MB, uploaded 5 min ago)
          claude_file_id: file_abc123...
    """
    if not files:
        return ""

    lines = ["Available files in this conversation:"]

    for file in files:
        # Format: filename (type, size, uploaded time)
        file_info = (f"- {file.filename} ({file.file_type.value}, "
                     f"{format_size(file.file_size)}, "
                     f"uploaded {format_time_ago(file.uploaded_at)})")
        lines.append(file_info)

        # Add claude_file_id on next line (indented)
        lines.append(f"  claude_file_id: {file.claude_file_id}")

    # Add usage instructions
    lines.append("")
    lines.append(f"Total files available: {len(files)}")
    lines.append("")
    lines.append("To analyze these files, use the appropriate tool "
                 "(analyze_image for images, analyze_pdf for PDFs).")
    lines.append("")
    lines.append("IMPORTANT: If user asks about multiple files (e.g., 'these images', "
                 "'all photos', 'these files'), analyze ALL files from the list above. "
                 "Call the tool once for each file.")

    result = "\n".join(lines)

    logger.debug("tools.helpers.format_files_section",
                 file_count=len(files),
                 section_length=len(result))

    return result


def extract_tool_uses(
        content: List[anthropic.types.ContentBlock]) -> List[Dict[str, Any]]:
    """Extract tool_use blocks from Claude response content.

    Parses response content blocks and extracts all tool_use requests.
    Each tool_use contains: id, name, input parameters.

    Args:
        content: List of ContentBlock objects from Claude response.

    Returns:
        List of dicts with tool use information:
        [{"id": "toolu_...", "name": "analyze_image", "input": {...}}, ...]

    Examples:
        >>> response = await provider.get_message(request)
        >>> tool_uses = extract_tool_uses(response.content)
        >>> for tool in tool_uses:
        ...     print(f"Tool: {tool['name']}")
    """
    tool_uses = []

    for block in content:
        if block.type == "tool_use":
            tool_uses.append({
                "id": block.id,
                "name": block.name,
                "input": block.input
            })

    logger.info("tools.helpers.extract_tool_uses",
                content_blocks=len(content),
                tool_count=len(tool_uses),
                tool_names=[t["name"] for t in tool_uses])

    return tool_uses


def format_tool_results(tool_uses: List[Dict[str, Any]],
                        results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Format tool execution results for Claude API.

    Creates tool_result blocks that match the tool_use requests.
    Handles both successful results and errors.

    Args:
        tool_uses: List of tool_use dicts (from extract_tool_uses).
        results: List of execution results (from execute_tool).

    Returns:
        List of tool_result dicts for Claude API.

    Examples:
        >>> tool_results = format_tool_results(tool_uses, results)
        >>> # Send back to Claude:
        >>> messages.append({"role": "user", "content": tool_results})
    """
    if len(tool_uses) != len(results):
        logger.error("tools.helpers.format_tool_results.mismatch",
                     tool_count=len(tool_uses),
                     result_count=len(results))
        raise ValueError(
            f"Mismatch: {len(tool_uses)} tools but {len(results)} results")

    formatted = []

    for tool_use, result in zip(tool_uses, results):
        # Check if result is an error
        is_error = result.get("error") is not None

        if is_error:
            # Error result
            formatted.append({
                "type": "tool_result",
                "tool_use_id": tool_use["id"],
                "is_error": True,
                "content": result["error"]
            })
            logger.warning("tools.helpers.format_tool_results.error",
                           tool_use_id=tool_use["id"],
                           tool_name=tool_use["name"],
                           error=result["error"])
        else:
            # Success result - serialize to JSON
            formatted.append({
                "type": "tool_result",
                "tool_use_id": tool_use["id"],
                "content": json.dumps(result)
            })
            logger.info("tools.helpers.format_tool_results.success",
                        tool_use_id=tool_use["id"],
                        tool_name=tool_use["name"])

    return formatted
