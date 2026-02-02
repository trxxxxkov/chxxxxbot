"""Streaming session for Claude responses.

StreamingSession encapsulates all state needed during a single streaming
response, providing clean methods for handling events and managing display.
"""

from typing import Any, Optional

from core.tools.registry import get_tool_emoji
from telegram.draft_streaming import DraftManager
from telegram.streaming.display_manager import DisplayManager
from telegram.streaming.formatting import DEFAULT_PARSE_MODE
from telegram.streaming.formatting import format_display
from telegram.streaming.formatting import format_final_text
from telegram.streaming.formatting import ParseMode
from telegram.streaming.formatting import strip_tool_markers
from telegram.streaming.truncation import TruncationManager
from telegram.streaming.types import BlockType
from telegram.streaming.types import ToolCall
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def _get_unclosed_code_block_prefix(text: str) -> str:
    r"""Check if text has an unclosed code block and return the opening prefix.

    When text is split mid-code-block, we need to continue the code block
    in the next message. This function detects unclosed ``` blocks and
    returns the prefix to prepend (e.g., "```python\n").

    Args:
        text: Raw text to check.

    Returns:
        Opening prefix if unclosed code block found, empty string otherwise.
        Example: "```python\n" or "```\n"
    """
    # Count code block markers
    # Each ``` toggles code block state
    code_block_count = text.count("```")

    if code_block_count % 2 == 0:
        # Balanced - no unclosed code block
        return ""

    # Odd number of ``` means unclosed code block
    # Find the last opening ``` to get the language
    last_open_pos = text.rfind("```")
    if last_open_pos == -1:
        return ""

    # Extract language (if any) - it's between ``` and first newline
    after_marker = text[last_open_pos + 3:]
    newline_pos = after_marker.find("\n")

    if newline_pos == -1:
        # No newline after ``` - just code block start
        language = after_marker.strip()
    else:
        language = after_marker[:newline_pos].strip()

    # Build the prefix
    if language:
        return f"```{language}\n"
    else:
        return "```\n"


# pylint: disable=too-many-public-methods
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

    def __init__(self,
                 draft_manager: DraftManager,
                 thread_id: int,
                 parse_mode: ParseMode = DEFAULT_PARSE_MODE) -> None:
        """Initialize streaming session.

        Args:
            draft_manager: DraftManager for sending updates.
            thread_id: Database thread ID for logging.
            parse_mode: "MarkdownV2" (default) or "HTML".
        """
        self._dm = draft_manager
        self._thread_id = thread_id
        self._parse_mode = parse_mode
        self._display = DisplayManager()
        self._truncator = TruncationManager(parse_mode=parse_mode)
        self._last_sent_text = ""
        self._pending_tools: list[ToolCall] = []
        self._message_part = 1  # Track message parts for splitting

        # Continuation prefix for split messages
        # When message is split mid-code-block, this stores the opening marker
        # (e.g., "```python\n") to prepend to the next message part
        self._continuation_prefix = ""

        # TTFT optimization: track if first update was sent
        # First update is forced (bypasses throttle) for fast time-to-first-token
        self._first_update_sent = False

        # Per-iteration state (reset each iteration)
        self._content_blocks: list[dict] = []
        self._current_thinking = ""
        self._current_text = ""
        self._current_block_type = ""
        self._stop_reason = ""
        self._captured_message: Any = None

        # Track subagent tools for display (tool_name -> list of subagent tools)
        self._subagent_tools: dict[str, list[str]] = {}

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

        Also handles continuation after message split: if previous message
        was split mid-code-block, prepends the opening marker to continue
        the code block formatting.

        Args:
            content: Text content chunk.
        """
        # Check if we need to continue formatting from split message
        # This happens when previous message was split mid-code-block
        if self._continuation_prefix and not self._current_text:
            content = self._continuation_prefix + content
            logger.debug("stream.session.continuation_prefix_applied",
                         thread_id=self._thread_id,
                         prefix=repr(self._continuation_prefix))
            self._continuation_prefix = ""  # Clear after use

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

    async def handle_tool_use_start(self,
                                    tool_id: str,
                                    tool_name: str,
                                    is_server_tool: bool = False) -> None:
        """Handle tool_use event (tool started, input not yet complete).

        Finalizes any pending text block and shows tool marker.

        Args:
            tool_id: Tool use ID from Claude.
            tool_name: Name of the tool being called.
            is_server_tool: True for server-side tools (web_search, web_fetch).
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
                    tool_id=tool_id,
                    is_server_tool=is_server_tool)

    def handle_tool_input_complete(self,
                                   tool_id: str,
                                   tool_name: str,
                                   tool_input: dict[str, Any],
                                   is_server_tool: bool = False) -> None:
        """Handle block_end event with complete tool input.

        Updates tool marker (for generate_image) and adds to pending tools.
        Server-side tools (web_search, web_fetch) are NOT added to pending_tools
        because they are executed by the API automatically.

        Args:
            tool_id: Tool use ID from Claude.
            tool_name: Name of the tool.
            tool_input: Complete tool input parameters.
            is_server_tool: True for server-side tools (web_search, web_fetch).
        """
        # Finalize current block
        self._finalize_current_block()

        # Server-side tools are already executed by API and included in response
        # Don't add to content_blocks (captured_message has them) or pending_tools
        if is_server_tool:
            logger.info("stream.session.server_tool_skipped",
                        thread_id=self._thread_id,
                        tool_name=tool_name,
                        tool_id=tool_id)
            return

        # Add tool_use to content blocks (client-side tools only)
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

        # Add to pending tools (client-side only - need execution)
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
            await self._dm.commit_and_create_new(parse_mode=self._parse_mode)
            self._last_sent_text = ""
            self._display.clear()
            return

        # Format text only (no thinking in final)
        from telegram.streaming.formatting import format_blocks
        final_text = format_blocks(text_only,
                                   is_streaming=False,
                                   parse_mode=self._parse_mode)
        final_text = strip_tool_markers(final_text)

        # Commit with final text
        await self._dm.commit_and_create_new(final_text=final_text.strip() or
                                             None,
                                             parse_mode=self._parse_mode)
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
            Formatted final text (MarkdownV2 or HTML based on parse_mode).
        """
        return format_final_text(self._display, parse_mode=self._parse_mode)

    @property
    def has_sent_parts(self) -> bool:
        """Check if message was split and parts already sent.

        Returns:
            True if at least one message part was committed via splitting.
        """
        return self._message_part > 1

    def get_current_text_length(self) -> int:
        """Get current text length before any clearing.

        Returns:
            Total character count of text blocks.
        """
        return self._display.total_text_length()

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

        # Always use double newline for proper visual separation
        # Single newline doesn't create visible separation in Telegram
        self._display.append(BlockType.THINKING, "\n\n" + message)

    def clear_pending_tools(self) -> None:
        """Clear pending tools after execution."""
        self._pending_tools.clear()

    async def add_subagent_tool(self, parent_tool: str, sub_tool: str) -> None:
        """Add subagent tool to parent tool's progress display.

        Updates the tool marker to show which tools the subagent is using.
        For example: [🔍 self_critique] → with subagent list below.

        Args:
            parent_tool: Name of the parent tool (e.g., 'self_critique').
            sub_tool: Name of the subagent tool being called.
        """
        if parent_tool not in self._subagent_tools:
            self._subagent_tools[parent_tool] = []

        self._subagent_tools[parent_tool].append(sub_tool)

        # Build subagent tools list text
        tools_list = self._subagent_tools[parent_tool]
        tools_text = "\n".join(f"- {t}" for t in tools_list)
        subagent_marker = f"[{tools_text}]"

        # Find parent tool marker and update/add subagent marker
        parent_emoji = get_tool_emoji(parent_tool)
        parent_marker = f"[{parent_emoji} {parent_tool}]"

        # Look for existing subagent marker or add new one
        found_parent = False
        for block in self._display.blocks:
            if block.block_type == BlockType.THINKING:
                if parent_marker in block.content:
                    found_parent = True
                    # Check if there's already a subagent marker
                    # Pattern: [🔍 self_critique]\n[- tool1\n- tool2]
                    lines = block.content.split("\n")
                    new_lines = []
                    skip_until_close = False

                    for line in lines:
                        if parent_marker in line:
                            new_lines.append(line)
                            # Add subagent marker on next line
                            new_lines.append(subagent_marker)
                            skip_until_close = True
                        elif skip_until_close and line.startswith("[- "):
                            # Skip old subagent marker lines
                            continue
                        elif skip_until_close and line.startswith("-"):
                            # Continue skipping subagent lines
                            continue
                        elif skip_until_close and line.endswith(
                                "]") and not line.startswith("["):
                            # End of old subagent marker
                            skip_until_close = False
                            continue
                        else:
                            skip_until_close = False
                            new_lines.append(line)

                    block.content = "\n".join(new_lines)
                    break

        if found_parent:
            await self._update_draft(force=True)

        logger.debug("stream.session.subagent_tool_added",
                     thread_id=self._thread_id,
                     parent_tool=parent_tool,
                     sub_tool=sub_tool,
                     total_subagent_tools=len(tools_list))

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

        TTFT optimization: First update is always forced (bypasses throttle)
        for fast time-to-first-token delivery.

        Args:
            force: If True, bypass throttling.
        """
        display_text = format_display(self._display,
                                      is_streaming=True,
                                      parse_mode=self._parse_mode)

        # Check if we need to split (text too long, thinking gone)
        text_length = self._display.total_text_length()
        # After formatting, thinking might be truncated to empty
        # Check the formatted result for blockquote/expandable marker presence
        if self._parse_mode == "MarkdownV2":
            has_thinking = "**>" in display_text
        else:
            has_thinking = "<blockquote" in display_text

        if self._truncator.should_split("x" if has_thinking else "",
                                        text_length):
            await self._split_message()
            # Re-format after split
            display_text = format_display(self._display,
                                          is_streaming=True,
                                          parse_mode=self._parse_mode)

        if display_text != self._last_sent_text:
            # TTFT: Force first update to bypass throttle
            should_force = force or not self._first_update_sent
            await self._dm.current.update(display_text,
                                          parse_mode=self._parse_mode,
                                          force=should_force)
            self._last_sent_text = display_text

            if not self._first_update_sent:
                self._first_update_sent = True
                logger.debug("stream.session.first_update_sent",
                             thread_id=self._thread_id,
                             text_length=len(display_text))

    async def _split_message(self) -> None:
        """Split message when text exceeds limit.

        Finalizes current text as a message part and clears display
        for continuation. Thinking blocks are discarded (already truncated).

        If the text ends mid-code-block (unclosed ```), saves the opening
        marker as continuation prefix for the next message part.
        """
        text_blocks = self._display.get_text_blocks()
        if not text_blocks:
            return

        # Get raw text to check for unclosed code blocks BEFORE formatting
        raw_text = "\n\n".join(b.content.strip() for b in text_blocks)
        self._continuation_prefix = _get_unclosed_code_block_prefix(raw_text)

        if self._continuation_prefix:
            logger.info("stream.session.unclosed_code_block",
                        thread_id=self._thread_id,
                        prefix=repr(self._continuation_prefix))

        # Format text only (no thinking)
        from telegram.streaming.formatting import format_blocks
        final_text = format_blocks(text_blocks,
                                   is_streaming=False,
                                   parse_mode=self._parse_mode)
        final_text = strip_tool_markers(final_text)

        if not final_text.strip():
            return

        logger.info("stream.session.splitting_message",
                    thread_id=self._thread_id,
                    part=self._message_part,
                    text_length=len(final_text))

        # Commit current part and create new draft
        await self._dm.commit_and_create_new(final_text=final_text.strip(),
                                             parse_mode=self._parse_mode)
        self._message_part += 1

        # Clear display for continuation (thinking already gone)
        self._display.clear()
        self._last_sent_text = ""
        # Reset current text so continuation prefix is applied to next chunk
        self._current_text = ""
