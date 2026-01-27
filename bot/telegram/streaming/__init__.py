"""Streaming module for Claude responses.

This module provides clean abstractions for streaming Claude responses
to Telegram with proper display formatting and draft management.

Public API:
    - BlockType: Enum for content block types
    - DisplayBlock: Dataclass for typed content blocks
    - DisplayManager: Manages display blocks lifecycle
    - StreamingSession: Encapsulates streaming state

Formatting functions:
    - escape_html: Escape HTML for Telegram
    - strip_tool_markers: Remove tool markers from final text
    - format_blocks: Format blocks for display
    - format_display: Format DisplayManager for display
    - format_final_text: Format only text for final message
"""

from telegram.streaming.display_manager import DisplayManager
from telegram.streaming.formatting import escape_html
from telegram.streaming.formatting import format_blocks
from telegram.streaming.formatting import format_display
from telegram.streaming.formatting import format_final_text
from telegram.streaming.formatting import strip_tool_markers
from telegram.streaming.session import StreamingSession
from telegram.streaming.types import BlockType
from telegram.streaming.types import CancellationReason
from telegram.streaming.types import DisplayBlock
from telegram.streaming.types import FileDelivery
from telegram.streaming.types import StreamResult
from telegram.streaming.types import ToolCall

__all__ = [
    # Types
    "BlockType",
    "DisplayBlock",
    "ToolCall",
    "FileDelivery",
    "StreamResult",
    "CancellationReason",
    # Display management
    "DisplayManager",
    # Formatting
    "escape_html",
    "strip_tool_markers",
    "format_blocks",
    "format_display",
    "format_final_text",
    # Session
    "StreamingSession",
]
