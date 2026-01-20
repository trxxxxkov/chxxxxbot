"""Base tool configuration dataclass.

This module defines the ToolConfig dataclass that provides a unified
configuration for all tools, eliminating the need for multiple
separate registries.

NO __init__.py - use direct import:
    from core.tools.base import ToolConfig, ToolResultFormatter
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Any, Callable, Dict, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession


class ToolResultFormatter(Protocol):
    """Protocol for tool result formatting functions.

    Each tool can define its own result formatter that generates
    user-visible system messages about tool execution.
    """

    def __call__(self, tool_input: Dict[str, Any], result: Dict[str,
                                                                Any]) -> str:
        """Format tool result for display.

        Args:
            tool_input: The input parameters passed to the tool.
            result: The result dictionary returned by the tool.

        Returns:
            Formatted message string, or empty string if no message needed.
        """
        ...  # pylint: disable=unnecessary-ellipsis


@dataclass
class ToolConfig:  # pylint: disable=too-many-instance-attributes
    """Unified configuration for a tool.

    This dataclass consolidates all tool-related configuration in one place:
    - API definition (schema for Claude)
    - Executor function
    - Display properties (emoji)
    - Runtime requirements (needs_bot_session)
    - Result formatting
    - File type validation

    When adding a new tool, create a ToolConfig instance in the tool module
    and import it into the registry. This eliminates the need to update
    multiple separate dictionaries.

    Attributes:
        name: Tool name (must match the name in definition).
        definition: Tool schema for Claude API (name, description, input_schema).
        executor: Async function that executes the tool.
        emoji: Emoji for visual display in messages.
        needs_bot_session: Whether executor needs bot and session parameters.
        format_result: Optional function to format result for user display.
        is_server_side: Whether this is a server-side tool (managed by Anthropic).
        file_id_param: Parameter name containing claude_file_id (for validation).
        allowed_mime_prefixes: List of allowed MIME type prefixes (e.g., ["image/"]).

    Examples:
        >>> config = ToolConfig(
        ...     name="execute_python",
        ...     definition=EXECUTE_PYTHON_TOOL,
        ...     executor=execute_python,
        ...     emoji="🐍",
        ...     needs_bot_session=True,
        ...     format_result=format_python_result,
        ... )
        >>> config = ToolConfig(
        ...     name="analyze_image",
        ...     definition=ANALYZE_IMAGE_TOOL,
        ...     executor=analyze_image,
        ...     file_id_param="claude_file_id",
        ...     allowed_mime_prefixes=["image/"],
        ... )
    """

    name: str
    definition: Dict[str, Any]
    executor: Optional[Callable] = None  # None for server-side tools
    emoji: str = "🔧"
    needs_bot_session: bool = False
    format_result: Optional[ToolResultFormatter] = None
    is_server_side: bool = False
    file_id_param: Optional[str] = None  # Parameter with claude_file_id
    allowed_mime_prefixes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        # Server-side tools don't have executors
        if not self.is_server_side and self.executor is None:
            raise ValueError(f"Tool '{self.name}' must have an executor "
                             f"(or set is_server_side=True)")

        # Validate name matches definition
        def_name = self.definition.get("name")
        if def_name and def_name != self.name:
            raise ValueError(f"Tool name mismatch: config.name='{self.name}' "
                             f"but definition.name='{def_name}'")

    def get_system_message(self, tool_input: Dict[str, Any],
                           result: Dict[str, Any]) -> str:
        """Get formatted system message for tool result.

        Args:
            tool_input: The input parameters passed to the tool.
            result: The result dictionary returned by the tool.

        Returns:
            Formatted message string, or empty string if no formatter.
        """
        if self.format_result:
            return self.format_result(tool_input, result)
        return ""
