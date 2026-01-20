"""Type definitions for streaming module.

This module defines the core types used throughout the streaming system:
- BlockType: Enum for content block types (thinking, text)
- DisplayBlock: Dataclass for typed content blocks
"""

from dataclasses import dataclass
from dataclasses import field
from enum import Enum
from typing import Any


class BlockType(str, Enum):
    """Type of content block in streaming display.

    Using str mixin allows direct string comparison and JSON serialization.
    """

    THINKING = "thinking"
    TEXT = "text"


@dataclass
class DisplayBlock:
    """A typed content block for display.

    Attributes:
        block_type: Type of content (thinking or text).
        content: The actual content string.
    """

    block_type: BlockType
    content: str

    def __post_init__(self) -> None:
        """Validate block has content."""
        if not isinstance(self.block_type, BlockType):
            self.block_type = BlockType(self.block_type)


@dataclass
class ToolCall:
    """Represents a pending tool call.

    Attributes:
        tool_id: Unique identifier from Claude API.
        name: Tool name (e.g., "generate_image", "execute_python").
        input: Tool input parameters.
    """

    tool_id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class FileDelivery:
    """File to be delivered to user.

    Attributes:
        filename: Original filename.
        content: File bytes.
        mime_type: MIME type of the file.
        source_tool: Tool that generated this file.
    """

    filename: str
    content: bytes
    mime_type: str
    source_tool: str
