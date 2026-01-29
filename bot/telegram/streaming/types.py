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


class CancellationReason(str, Enum):
    """Reason for stream cancellation.

    Using str mixin allows direct string comparison and JSON serialization.
    """

    STOP_COMMAND = "stop_command"
    NEW_MESSAGE = "new_message"
    MAX_ITERATIONS = "max_iterations"
    ERROR = "error"


@dataclass
class StreamResult:  # pylint: disable=too-many-instance-attributes
    """Result of streaming operation.

    Returned by StreamingOrchestrator.stream() to provide all information
    needed by the caller for billing, logging, and response handling.

    Attributes:
        text: Final text content (without thinking).
        display_text: Formatted display text (may include thinking markers).
        message: Final Telegram message (if finalized).
        needs_continuation: True if tool requested turn break.
        was_cancelled: True if user cancelled generation.
        cancellation_reason: Why generation was cancelled.
        conversation: Updated conversation state for continuation.
        thinking_chars: Character count of thinking (for partial cost).
        output_chars: Character count of output text (for partial cost).
        iterations: Number of tool loop iterations completed.
        has_sent_parts: True if message was split and parts already sent.
        has_delivered_files: True if files were delivered via deliver_file tool.
    """

    text: str
    display_text: str
    message: Any = None
    needs_continuation: bool = False
    was_cancelled: bool = False
    cancellation_reason: "CancellationReason | None" = None
    conversation: "list[dict] | None" = None
    thinking_chars: int = 0
    output_chars: int = 0
    iterations: int = 0
    has_sent_parts: bool = False
    has_delivered_files: bool = False
