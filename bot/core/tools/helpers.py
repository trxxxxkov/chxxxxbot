"""Helper functions for tool use integration.

This module provides utility functions for:
- Retrieving available files for a thread (with Redis caching)
- Formatting files list for system prompt
- Extracting tool use blocks from Claude responses
- Formatting tool results for API

NO __init__.py - use direct import:
    from core.tools.helpers import get_available_files
"""

from datetime import datetime
from datetime import timezone
import json
from typing import Any, Dict, List, Optional

import anthropic
from db.models.user_file import UserFile
from db.repositories.user_file_repository import UserFileRepository
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def _user_file_to_dict(uf: UserFile) -> Dict[str, Any]:
    """Convert UserFile to dict for caching.

    Args:
        uf: UserFile instance.

    Returns:
        Dict with serializable file data.
    """
    return {
        "id": uf.id,
        "filename": uf.filename,
        "file_type": uf.file_type.value,
        "mime_type": uf.mime_type,
        "file_size": uf.file_size,
        "claude_file_id": uf.claude_file_id,
        "uploaded_at": uf.uploaded_at.isoformat() if uf.uploaded_at else None,
        "source": uf.source.value if uf.source else None,
    }


class CachedUserFile:
    """Wrapper class to provide UserFile-like interface from cached dict."""

    def __init__(self, data: Dict[str, Any]):
        """Initialize from cached dict.

        Args:
            data: Dict from cache with file data.
        """
        self._data = data

    @property
    def id(self) -> int:
        """File ID."""
        return self._data.get("id", 0)

    @property
    def filename(self) -> str:
        """Original filename."""
        return self._data.get("filename", "")

    @property
    def file_type(self) -> Any:
        """File type as object with .value attribute."""
        from db.models.user_file import \
            FileType  # pylint: disable=import-outside-toplevel
        type_val = self._data.get("file_type", "document")
        return FileType(type_val)

    @property
    def mime_type(self) -> str:
        """MIME type."""
        return self._data.get("mime_type", "")

    @property
    def file_size(self) -> int:
        """File size in bytes."""
        return self._data.get("file_size", 0)

    @property
    def claude_file_id(self) -> str:
        """Claude Files API ID."""
        return self._data.get("claude_file_id", "")

    @property
    def uploaded_at(self) -> Optional[datetime]:
        """Upload timestamp."""
        ts = self._data.get("uploaded_at")
        if ts:
            return datetime.fromisoformat(ts)
        return None

    @property
    def source(self) -> Any:
        """Get file source enum value: USER or ASSISTANT."""
        from db.models.user_file import \
            FileSource  # pylint: disable=import-outside-toplevel
        source_val = self._data.get("source", "user")
        return FileSource(source_val) if source_val else None


async def get_available_files(thread_id: int,
                              user_file_repo: UserFileRepository) -> List[Any]:
    """Get all available files for a thread with caching.

    Uses Redis cache with 1 hour TTL. Falls back to database on cache miss.
    Retrieves files from user_files table that belong to messages in
    this thread. Files are used for tool selection and system prompt.

    Args:
        thread_id: Internal thread ID from threads table.
        user_file_repo: UserFileRepository instance.

    Returns:
        List of file objects (UserFile or CachedUserFile, may be empty).

    Examples:
        >>> files = await get_available_files(thread_id=42, user_file_repo=repo)
        >>> if files:
        ...     print(f"Found {len(files)} files")
    """
    # Import cache functions here to avoid circular imports
    from cache.thread_cache import \
        cache_files  # pylint: disable=import-outside-toplevel
    from cache.thread_cache import \
        get_cached_files  # pylint: disable=import-outside-toplevel

    # Try cache first
    cached = await get_cached_files(thread_id)
    if cached is not None:
        logger.debug("tools.helpers.get_available_files.cache_hit",
                     thread_id=thread_id,
                     file_count=len(cached))
        # Convert cached dicts back to file-like objects
        return [CachedUserFile(f) for f in cached]

    # Cache miss - query database
    logger.debug("tools.helpers.get_available_files.calling_repo",
                 thread_id=thread_id,
                 repo_type=type(user_file_repo).__name__)

    files = await user_file_repo.get_by_thread_id(thread_id)

    logger.info("tools.helpers.get_available_files",
                thread_id=thread_id,
                file_count=len(files))

    # Cache result
    if files:
        files_data = [_user_file_to_dict(f) for f in files]
        await cache_files(thread_id, files_data)

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
        dt: Datetime to format (timezone-aware or naive, naive treated as UTC).

    Returns:
        Human-readable time ago string.

    Examples:
        >>> format_time_ago(datetime.now(timezone.utc) - timedelta(minutes=5))
        '5 min ago'
    """
    now = datetime.now(timezone.utc)

    # Handle timezone-naive datetimes (treat as UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

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
    Groups files by type for better readability.

    Args:
        files: List of UserFile instances (or CachedUserFile).

    Returns:
        Formatted string for system prompt (empty if no files).

    Examples:
        >>> section = format_files_section(files)
        >>> print(section)
        Available files in this conversation:
        IMAGE files:
          - photo.jpg (1.2 MB, 5 min ago)
            claude_file_id: file_abc123...
    """
    if not files:
        return ""

    # Group files by type
    by_type: Dict[str, List[Any]] = {}
    for file in files:
        file_type = file.file_type.value
        if file_type not in by_type:
            by_type[file_type] = []
        by_type[file_type].append(file)

    lines = ["Available files in this conversation:"]

    # Order: images first, then PDFs, then others
    type_order = [
        "image", "pdf", "document", "audio", "voice", "video", "generated"
    ]
    for file_type in type_order:
        if file_type not in by_type:
            continue
        type_files = by_type[file_type]

        lines.append(f"\n{file_type.upper()} files ({len(type_files)}):")
        for file in type_files:
            file_info = (f"  - {file.filename} "
                         f"({format_size(file.file_size)}, "
                         f"{format_time_ago(file.uploaded_at)})")
            lines.append(file_info)
            lines.append(f"    claude_file_id: {file.claude_file_id}")

    # Add any types not in order
    for file_type, type_files in by_type.items():
        if file_type in type_order:
            continue
        lines.append(f"\n{file_type.upper()} files ({len(type_files)}):")
        for file in type_files:
            file_info = (f"  - {file.filename} "
                         f"({format_size(file.file_size)}, "
                         f"{format_time_ago(file.uploaded_at)})")
            lines.append(file_info)
            lines.append(f"    claude_file_id: {file.claude_file_id}")

    lines.append("")
    lines.append(f"Total files available: {len(files)}")
    lines.append("")

    # Tool guidance for ALL file types
    lines.append("How to work with these files:")
    lines.append("- IMAGE files: use analyze_image(claude_file_id)")
    lines.append("- PDF files: use analyze_pdf(claude_file_id)")
    lines.append("- AUDIO/VOICE/VIDEO files: use transcribe_audio(file_id) "
                 "to get transcript")
    lines.append("- DOCUMENT/GENERATED files: use execute_python with "
                 "file_inputs parameter")
    lines.append("")
    lines.append(
        "CRITICAL: These files are ALREADY SENT to user and available here. "
        "Do NOT regenerate or re-create files that are in this list! "
        "If user asks about files shown above, work with them directly.")
    lines.append("")
    lines.append(
        "If user asks about multiple files (e.g., 'these images', "
        "'all photos'), analyze ALL relevant files from the list above.")

    result = "\n".join(lines)

    logger.debug("tools.helpers.format_files_section",
                 file_count=len(files),
                 types=list(by_type.keys()),
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

    Special handling for image previews:
    - If result contains `_image_preview` key, includes image in content
    - This allows Claude to visually verify rendered images before delivery

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
        # Check if result is an error (not None and not empty string)
        error_msg = result.get("error")
        is_error = error_msg is not None and error_msg != ""

        if is_error:
            # Error result
            formatted.append({
                "type": "tool_result",
                "tool_use_id": tool_use["id"],
                "is_error": True,
                "content": error_msg
            })
            logger.info("tools.helpers.format_tool_results.error",
                        tool_use_id=tool_use["id"],
                        tool_name=tool_use["name"],
                        error=error_msg)
        else:
            # Check for image previews (render_latex, execute_python plots)
            # Single image preview (render_latex)
            image_preview = result.pop("_image_preview", None)
            # Multiple image previews (execute_python)
            image_previews = result.pop("_image_previews", None)

            # Build list of all images to include
            images_to_include: List[Dict[str, Any]] = []
            if image_preview:
                images_to_include.append(image_preview)
            if image_previews:
                images_to_include.extend(image_previews)

            if images_to_include:
                # Multi-part content: images + text result
                content_blocks: List[Dict[str, Any]] = []

                # Add all images
                for img in images_to_include:
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.get("media_type", "image/png"),
                            "data": img["data"],
                        }
                    })

                # Add text result (JSON)
                content_blocks.append({
                    "type": "text",
                    "text": json.dumps(result)
                })

                formatted.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use["id"],
                    "content": content_blocks
                })

                total_size_kb = sum(
                    len(img["data"]) / 1024 for img in images_to_include)
                logger.info("tools.helpers.format_tool_results.with_images",
                            tool_use_id=tool_use["id"],
                            tool_name=tool_use["name"],
                            image_count=len(images_to_include),
                            total_size_kb=round(total_size_kb, 1))
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
