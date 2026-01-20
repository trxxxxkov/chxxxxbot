"""Streaming session for Claude responses.

StreamingSession encapsulates all state needed during a single streaming
response, providing clean methods for handling events and managing display.
"""

from typing import Any, Optional

from core.tools.registry import get_tool_emoji
from telegram.draft_streaming import DraftManager
from telegram.streaming.display_manager import DisplayManager
from telegram.streaming.formatting import format_display
from telegram.streaming.formatting import format_final_text
from telegram.streaming.formatting import strip_tool_markers
from telegram.streaming.truncation import TruncationManager
from telegram.streaming.types import BlockType
from telegram.streaming.types import ToolCall
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class StreamingSession:  # pylint: disable=too-many-instance-attributes
    """Encapsulates state for a single streaming response.

    Manages:
    - Display blocks (thinking, text)
    - Draft updates (via DraftManager)
    - Pending tool calls
    - Last sent text (for deduplication)

    The session persists across multiple iterations of the tool loop,
    but display blocks are cleared when committing before files.

    Example:
        async with DraftManager(bot, chat_id, topic_id) as dm:
            session = StreamingSession(dm, thread_id)

            async for event in claude_provider.stream_events(request):
                await session.handle_event(event)

            if session.pending_tools:
                # Execute tools...
                session.clear_pending_tools()

            final_text = session.get_final_text()
    """

    def __init__(self, draft_manager: DraftManager, thread_id: int) -> None:
        """Initialize streaming session.

        Args:
            draft_manager: DraftManager for sending updates.
            thread_id: Database thread ID for logging.
        """
        self._dm = draft_manager
        self._thread_id = thread_id
        self._display = DisplayManager()
        self._truncator = TruncationManager()
        self._last_sent_text = ""
        self._pending_tools: list[ToolCall] = []
        self._message_part = 1  # Track message parts for splitting

        # Per-iteration state (reset each iteration)
        self._content_blocks: list[dict] = []
        self._current_thinking = ""
        self._current_text = ""
        self._current_block_type = ""
        self._stop_reason = ""
        self._captured_message: Any = None

    @property
    def display(self) -> DisplayManager:
        """Get the display manager."""
        return self._display

    @property
    def pending_tools(self) -> list[ToolCall]:
        """Get pending tool calls."""
        return self._pending_tools

    @property
    def stop_reason(self) -> str:
        """Get the stop reason from last message_end event."""
        return self._stop_reason

    @property
    def captured_message(self) -> Any:
        """Get the captured final message (for tool results)."""
        return self._captured_message

    @property
    def content_blocks(self) -> list[dict]:
        """Get content blocks collected during streaming."""
        return self._content_blocks

    def reset_iteration(self) -> None:
        """Reset per-iteration state for next tool loop iteration.

        Called at the start of each iteration. Display blocks persist
        across iterations (only cleared on file commits).
        """
        self._pending_tools.clear()
        self._content_blocks.clear()
        self._current_thinking = ""
        self._current_text = ""
        self._current_block_type = ""
        self._stop_reason = ""
        self._captured_message = None

    async def handle_thinking_delta(self, content: str) -> None:
        """Handle thinking_delta event.

        Args:
            content: Thinking content chunk.
        """
        # Add empty line before new thinking if previous was a system message
        # (tool marker/result ending with ])
        if not self._current_thinking:  # First thinking chunk in this iteration
            thinking_blocks = self._display.get_thinking_blocks()
            if thinking_blocks:
                last_thinking = thinking_blocks[-1].content.rstrip()
                if last_thinking.endswith("]"):
                    # Previous was tool marker/result, add empty line
                    content = "\n\n" + content.lstrip("\n")

        self._display.append(BlockType.THINKING, content)
        self._current_thinking += content
        self._current_block_type = "thinking"
        await self._update_draft()

    async def handle_text_delta(self, content: str) -> None:
        """Handle text_delta event.

        Adds empty line before text if previous thinking ends with ]
        (tool marker) for visual separation.

        Args:
            content: Text content chunk.
        """
        # Check if this is first text after tool markers
        # Add empty line for separation if needed
        if not self._current_text:  # First text chunk
            thinking_blocks = self._display.get_thinking_blocks()
            if thinking_blocks:
                last_thinking = thinking_blocks[-1].content.rstrip()
                if last_thinking.endswith("]"):
                    # Previous was tool marker, add empty line before text
                    content = "\n\n" + content.lstrip("\n")

        self._display.append(BlockType.TEXT, content)
        self._current_text += content
        self._current_block_type = "text"
        await self._update_draft()

    async def handle_tool_use_start(self, tool_id: str, tool_name: str) -> None:
        """Handle tool_use event (tool started, input not yet complete).

        Finalizes any pending text block and shows tool marker.

        Args:
            tool_id: Tool use ID from Claude.
            tool_name: Name of the tool being called.
        """
        # Finalize any pending content block
        self._finalize_current_block()

        # Show tool marker with visual separation
        emoji = get_tool_emoji(tool_name)
        if tool_name == "generate_image":
            tool_marker = f"\n\n[{emoji} {tool_name}…]"
        else:
            tool_marker = f"\n\n[{emoji} {tool_name}]"

        self._display.append(BlockType.THINKING, tool_marker)
        await self._update_draft(force=True)

        logger.info("stream.session.tool_detected",
                    thread_id=self._thread_id,
                    tool_name=tool_name,
                    tool_id=tool_id)

    def handle_tool_input_complete(self, tool_id: str, tool_name: str,
                                   tool_input: dict[str, Any]) -> None:
        """Handle block_end event with complete tool input.

        Updates tool marker (for generate_image) and adds to pending tools.

        Args:
            tool_id: Tool use ID from Claude.
            tool_name: Name of the tool.
            tool_input: Complete tool input parameters.
        """
        # Finalize current block
        self._finalize_current_block()

        # Add tool_use to content blocks
        self._content_blocks.append({
            "type": "tool_use",
            "id": tool_id,
            "name": tool_name,
            "input": tool_input or {}
        })

        # Update tool marker for generate_image (show prompt)
        if tool_input and tool_name == "generate_image":
            emoji = get_tool_emoji(tool_name)
            prompt = tool_input.get("prompt", "")
            old_marker = f"[{emoji} {tool_name}…]"
            new_marker = f"[{emoji} {tool_name}: \"{prompt}\"]"

            # Find and update marker in display blocks
            for block in self._display.blocks:
                if (block.block_type == BlockType.THINKING and
                        old_marker in block.content):
                    block.content = block.content.replace(
                        old_marker, new_marker)
                    break

        # Add to pending tools
        self._pending_tools.append(
            ToolCall(tool_id=tool_id, name=tool_name, input=tool_input or {}))

    async def handle_block_end(self) -> None:
        """Handle block_end event (non-tool).

        Finalizes current thinking or text block.
        """
        self._finalize_current_block()

    def handle_message_end(self, stop_reason: str) -> None:
        """Handle message_end event.

        Args:
            stop_reason: Reason for stopping (end_turn, tool_use, etc).
        """
        self._stop_reason = stop_reason

        # Finalize any remaining blocks
        if self._current_thinking:
            self._content_blocks.append({
                "type": "thinking",
                "thinking": self._current_thinking
            })
            self._current_thinking = ""

        if self._current_text:
            self._content_blocks.append({
                "type": "text",
                "text": self._current_text
            })
            self._current_text = ""

    def handle_stream_complete(self, final_message: Any) -> None:
        """Handle stream_complete event.

        Captures the final message for use in tool results.

        Args:
            final_message: The complete message from Claude API.
        """
        self._captured_message = final_message

    async def update_display(self) -> None:
        """Force update the draft with current display content."""
        await self._update_draft(force=True)

    async def commit_for_files(self) -> None:
        """Commit current content before sending files.

        Finalizes current text as permanent message, clears display.
        New draft will be created lazily on next update.
        """
        text_only = self._display.get_text_blocks()
        if not text_only:
            # No text content, just commit
            await self._dm.commit_and_create_new()
            self._last_sent_text = ""
            self._display.clear()
            return

        # Format text only (no thinking in final)
        from telegram.streaming.formatting import format_blocks
        final_text = format_blocks(text_only, is_streaming=False)
        final_text = strip_tool_markers(final_text)

        # Commit with final text
        await self._dm.commit_and_create_new(
            final_text=final_text.strip() or None)
        self._last_sent_text = ""
        self._display.clear()

    def get_final_text(self) -> str:
        """Get final answer text (text blocks only, stripped of markers).

        Returns:
            Clean final answer text.
        """
        return "\n\n".join(b.content.strip()
                           for b in self._display.get_text_blocks()
                           if b.content.strip())

    def get_final_display(self) -> str:
        """Get formatted final display (text only, no thinking).

        Returns:
            HTML-formatted final text.
        """
        return format_final_text(self._display)

    def add_system_message(self, message: str) -> None:
        """Add a system message to thinking block.

        Used for tool completion messages like [✅ Tool completed].
        Uses smart spacing: single newline if previous content ends with ]
        (another marker), double newline otherwise.

        Args:
            message: System message to add.
        """
        if not message:
            return

        # Check if previous thinking content ends with ] (tool marker)
        thinking_blocks = self._display.get_thinking_blocks()
        if thinking_blocks:
            last_content = thinking_blocks[-1].content.rstrip()
            if last_content.endswith("]"):
                # Previous was a marker, use single newline
                self._display.append(BlockType.THINKING, "\n" + message)
                return

        # Otherwise use double newline for visual separation
        self._display.append(BlockType.THINKING, "\n\n" + message)

    def clear_pending_tools(self) -> None:
        """Clear pending tools after execution."""
        self._pending_tools.clear()

    def log_iteration_complete(self, iteration: int) -> None:
        """Log iteration completion stats.

        Args:
            iteration: Current iteration number (1-based).
        """
        logger.info("stream.session.iteration_complete",
                    thread_id=self._thread_id,
                    iteration=iteration,
                    stop_reason=self._stop_reason,
                    pending_tools=len(self._pending_tools),
                    thinking_length=self._display.total_thinking_length(),
                    text_length=self._display.total_text_length())

    def _finalize_current_block(self) -> None:
        """Finalize current thinking or text block into content_blocks."""
        if self._current_block_type == "thinking" and self._current_thinking:
            self._content_blocks.append({
                "type": "thinking",
                "thinking": self._current_thinking
            })
            self._current_thinking = ""
        elif self._current_block_type == "text" and self._current_text:
            self._content_blocks.append({
                "type": "text",
                "text": self._current_text
            })
            self._current_text = ""
        self._current_block_type = ""

    async def _update_draft(self, force: bool = False) -> None:
        """Update draft if display has changed.

        Checks if message should be split when text exceeds threshold
        and thinking is already fully truncated.

        Args:
            force: If True, bypass throttling.
        """
        display_text = format_display(self._display, is_streaming=True)

        # Check if we need to split (text too long, thinking gone)
        text_length = self._display.total_text_length()
        # After formatting, thinking might be truncated to empty
        # Check the formatted result for blockquote presence
        has_thinking = "<blockquote" in display_text

        if self._truncator.should_split("x" if has_thinking else "",
                                        text_length):
            await self._split_message()
            # Re-format after split
            display_text = format_display(self._display, is_streaming=True)

        if display_text != self._last_sent_text:
            await self._dm.current.update(display_text, force=force)
            self._last_sent_text = display_text

    async def _split_message(self) -> None:
        """Split message when text exceeds limit.

        Finalizes current text as a message part and clears display
        for continuation. Thinking blocks are discarded (already truncated).
        """
        text_blocks = self._display.get_text_blocks()
        if not text_blocks:
            return

        # Format text only (no thinking)
        from telegram.streaming.formatting import format_blocks
        final_text = format_blocks(text_blocks, is_streaming=False)
        final_text = strip_tool_markers(final_text)

        if not final_text.strip():
            return

        logger.info("stream.session.splitting_message",
                    thread_id=self._thread_id,
                    part=self._message_part,
                    text_length=len(final_text))

        # Commit current part and create new draft
        await self._dm.commit_and_create_new(final_text=final_text.strip())
        self._message_part += 1

        # Clear display for continuation (thinking already gone)
        self._display.clear()
        self._last_sent_text = ""
