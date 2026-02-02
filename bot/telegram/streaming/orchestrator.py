"""Streaming orchestrator for Claude responses.

Coordinates streaming, tools, files, and billing. Replaces the monolithic
_stream_with_unified_events function with cleaner separation of concerns.

NO __init__.py - use direct import:
    from telegram.streaming.orchestrator import StreamingOrchestrator
"""

from typing import TYPE_CHECKING

from core.models import LLMRequest
from core.models import Message
from telegram.chat_action.manager import ChatActionManager
from telegram.chat_action.types import ActionPhase
from telegram.draft_streaming import DraftManager
from telegram.generation_tracker import generation_context
from telegram.handlers.claude_files import process_generated_files
from telegram.streaming.session import StreamingSession
from telegram.streaming.tool_executor import ToolExecutor
from telegram.streaming.types import CancellationReason
from telegram.streaming.types import StreamResult
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram import types
    from core.claude.provider import ClaudeProvider
    from db.repositories.user_file_repository import UserFileRepository
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Constants
TOOL_LOOP_MAX_ITERATIONS = 100
DRAFT_KEEPALIVE_INTERVAL = 3.0


def format_tool_results(
    tool_uses: list[dict],
    results: list[dict],
) -> list[dict]:
    """Format tool results for Claude API.

    Args:
        tool_uses: List of tool use dicts with id and name.
        results: List of result dicts matching tool_uses order.

    Returns:
        List of tool_result content blocks for Claude.
    """
    return [{
        "type": "tool_result",
        "tool_use_id": tool_uses[i]["id"],
        "content": str(results[i]),
    } for i in range(len(tool_uses))]


def get_tool_system_message(
    tool_name: str,
    tool_input: dict,
    result: dict,
) -> str | None:
    """Get system message to add after tool execution.

    Some tools need to add instructions to the conversation
    after execution (e.g., files delivered count).

    Args:
        tool_name: Name of the executed tool.
        tool_input: Tool input parameters.
        result: Tool execution result.

    Returns:
        System message string or None.
    """
    # Import here to avoid circular imports
    from core.tools.registry import get_tool_system_message as _get_msg
    return _get_msg(tool_name, tool_input, result)


def is_empty_content(content) -> bool:
    """Check if message content is empty.

    Empty content includes:
    - None or empty string ""
    - Empty list []
    - List without valid content blocks

    Args:
        content: Message content (str or list).

    Returns:
        True if content is empty, False otherwise.
    """
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        # Check if there's at least one valid content block
        valid_block_types = ("image", "document", "tool_result", "tool_use",
                             "server_tool_use", "server_tool_result")
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            # Text block with content is valid
            if block_type == "text" and block.get("text", "").strip():
                return False
            # Non-text blocks (images, tools) are always valid
            if block_type in valid_block_types:
                return False
        return True
    return False


def serialize_content_block(block) -> dict:
    """Serialize a content block for Claude API.

    Removes fields that are returned by API but not accepted on input,
    such as 'citations' in server_tool_result blocks.

    Args:
        block: Content block (Pydantic model or dict).

    Returns:
        Serialized dict safe to send back to API.
    """
    if hasattr(block, 'model_dump'):
        block_dict = block.model_dump()
    elif isinstance(block, dict):
        block_dict = block.copy()
    else:
        return block

    # Remove fields API returns but doesn't accept on input
    block_type = block_dict.get("type", "")
    if block_type in ("server_tool_result", "web_search_tool_result",
                      "web_fetch_tool_result"):
        block_dict.pop("citations", None)
        block_dict.pop("text", None)  # web_fetch_tool_result has 'text'

    # Also check nested content for server tool results
    if "content" in block_dict and isinstance(block_dict["content"], list):
        cleaned_content = []
        for item in block_dict["content"]:
            if isinstance(item, dict):
                item_copy = item.copy()
                item_copy.pop("citations", None)
                item_copy.pop("text", None)
                cleaned_content.append(item_copy)
            else:
                cleaned_content.append(item)
        block_dict["content"] = cleaned_content

    return block_dict


class StreamingOrchestrator:  # pylint: disable=too-many-instance-attributes
    """Orchestrates streaming response with tools and files.

    Manages the complete flow:
    1. Stream from Claude API
    2. Execute tools if requested (parallel)
    3. Process generated files
    4. Track costs
    5. Handle cancellation
    6. Continue if needed (tool results, turn break)

    Usage:
        orchestrator = StreamingOrchestrator(
            request=llm_request,
            first_message=message,
            thread_id=thread_id,
            session=session,
            user_file_repo=repo,
            chat_id=chat_id,
            user_id=user_id,
            telegram_thread_id=topic_id,
        )
        result = await orchestrator.stream()
    """

    def __init__(
        self,
        request: LLMRequest,
        first_message: "types.Message",
        thread_id: int,
        session: "AsyncSession",
        user_file_repo: "UserFileRepository",
        chat_id: int,
        user_id: int,
        telegram_thread_id: int | None = None,
        continuation_conversation: list | None = None,
        claude_provider: "ClaudeProvider | None" = None,
    ):
        """Initialize StreamingOrchestrator.

        Args:
            request: LLMRequest with tools configured.
            first_message: First Telegram message (for replies).
            thread_id: Thread ID for logging.
            session: Database session.
            user_file_repo: UserFileRepository for file handling.
            chat_id: Telegram chat ID.
            user_id: User ID.
            telegram_thread_id: Telegram thread/topic ID.
            continuation_conversation: Conversation state for continuation.
            claude_provider: Optional ClaudeProvider (uses singleton if None).
        """
        self._request = request
        self._first_message = first_message
        self._thread_id = thread_id
        self._session = session
        self._user_file_repo = user_file_repo
        self._chat_id = chat_id
        self._user_id = user_id
        self._telegram_thread_id = telegram_thread_id
        self._continuation_conversation = continuation_conversation
        self._claude_provider = claude_provider

        # Lazy-loaded components
        self._tool_executor: ToolExecutor | None = None

    def _get_claude_provider(self):
        """Get Claude provider (lazy import to avoid circular deps)."""
        if self._claude_provider is not None:
            return self._claude_provider
        from telegram.handlers.claude import claude_provider
        return claude_provider

    def _get_tool_executor(self) -> ToolExecutor:
        """Get or create tool executor."""
        if self._tool_executor is None:
            self._tool_executor = ToolExecutor(
                bot=self._first_message.bot,
                session=self._session,
                thread_id=self._thread_id,
                user_id=self._user_id,
                chat_id=self._chat_id,
                message_id=self._first_message.message_id,
                message_thread_id=self._first_message.message_thread_id,
            )
        return self._tool_executor

    async def stream(self) -> StreamResult:
        """Stream response with tool loop and continuation.

        Returns:
            StreamResult with final text, message, and metadata.
        """
        # Build conversation
        if self._continuation_conversation is not None:
            conversation = self._continuation_conversation
            logger.info(
                "orchestrator.continuation",
                thread_id=self._thread_id,
                conversation_length=len(conversation),
            )
        else:
            # Filter out messages with empty content to prevent API errors
            conversation = []
            for msg in self._request.messages:
                if is_empty_content(msg.content):
                    logger.warning(
                        "orchestrator.skipping_empty_message",
                        thread_id=self._thread_id,
                        role=msg.role,
                    )
                    continue
                conversation.append({"role": msg.role, "content": msg.content})

        logger.info(
            "orchestrator.start",
            thread_id=self._thread_id,
            max_iterations=TOOL_LOOP_MAX_ITERATIONS,
        )

        # Get ChatActionManager for typing indicator
        action_manager = ChatActionManager.get(
            self._first_message.bot,
            self._chat_id,
            self._telegram_thread_id,
        )

        # Enter generation context for /stop command support
        async with (
            generation_context(self._chat_id, self._user_id,
                               self._telegram_thread_id) as cancel_event,
            DraftManager(
                bot=self._first_message.bot,
                chat_id=self._chat_id,
                topic_id=self._telegram_thread_id,
                keepalive_interval=DRAFT_KEEPALIVE_INTERVAL,
            ) as dm,
        ):
            stream = StreamingSession(dm, self._thread_id)
            total_output_chars = 0

            for iteration in range(TOOL_LOOP_MAX_ITERATIONS):
                logger.info(
                    "orchestrator.iteration",
                    thread_id=self._thread_id,
                    iteration=iteration + 1,
                )

                # Reset per-iteration state
                stream.reset_iteration()

                # Build request for this iteration
                iter_request = LLMRequest(
                    messages=[
                        Message(role=msg["role"], content=msg["content"])
                        for msg in conversation
                    ],
                    system_prompt=self._request.system_prompt,
                    model=self._request.model,
                    max_tokens=self._request.max_tokens,
                    temperature=self._request.temperature,
                    tools=self._request.tools,
                )

                # Stream with typing indicator
                was_cancelled = False
                generating_scope_id = await action_manager.push_scope(
                    ActionPhase.GENERATING)
                generating_scope_active = True

                try:
                    provider = self._get_claude_provider()
                    async for event in provider.stream_events(iter_request):
                        # Check for cancellation
                        if cancel_event.is_set():
                            was_cancelled = True
                            break

                        # Handle events
                        if event.type == "thinking_delta":
                            await stream.handle_thinking_delta(event.content)
                        elif event.type == "text_delta":
                            await stream.handle_text_delta(event.content)
                        elif event.type == "tool_use":
                            # Stop typing when tool detected
                            if generating_scope_active:
                                await action_manager.pop_scope(
                                    generating_scope_id)
                                generating_scope_active = False
                            await stream.handle_tool_use_start(
                                event.tool_id, event.tool_name,
                                event.is_server_tool)
                        elif event.type == "block_end":
                            if event.tool_name and event.tool_id:
                                stream.handle_tool_input_complete(
                                    event.tool_id, event.tool_name,
                                    event.tool_input or {},
                                    event.is_server_tool)
                                await stream.update_display()
                            else:
                                await stream.handle_block_end()
                        elif event.type == "message_end":
                            stream.handle_message_end(event.stop_reason)
                        elif event.type == "stream_complete":
                            stream.handle_stream_complete(event.final_message)
                finally:
                    if generating_scope_active:
                        await action_manager.pop_scope(generating_scope_id)

                # Final update
                await stream.update_display()
                stream.log_iteration_complete(iteration + 1)
                total_output_chars += stream.get_current_text_length()

                # Handle cancellation
                if was_cancelled:
                    return await self._handle_cancellation(
                        stream, dm, total_output_chars)

                # Handle end_turn/pause_turn
                if stream.stop_reason in ("end_turn", "pause_turn"):
                    return await self._handle_completion(
                        stream, dm, iteration + 1)

                # Handle tool execution
                if stream.stop_reason == "tool_use" and stream.pending_tools:
                    result = await self._execute_tools(stream, dm, conversation,
                                                       cancel_event, iteration)
                    if result is not None:
                        return result
                    # Continue to next iteration with updated conversation
                elif stream.stop_reason == "tool_use" and not stream.pending_tools:
                    # Only server-side tools were called (web_search, web_fetch)
                    # They are executed by API automatically, just add to conversation
                    captured_msg = stream.captured_message
                    if captured_msg and captured_msg.content:
                        serialized_content = [
                            serialize_content_block(block)
                            for block in captured_msg.content
                        ]
                        conversation.append({
                            "role": "assistant",
                            "content": serialized_content
                        })
                        logger.info(
                            "orchestrator.server_tools_only",
                            thread_id=self._thread_id,
                            iteration=iteration + 1,
                        )
                    # Continue to next iteration
                else:
                    # Unexpected stop reason
                    return await self._handle_unexpected_stop(stream, dm)

            # Max iterations exceeded
            return await self._handle_max_iterations(dm)

    async def _handle_cancellation(
        self,
        stream: StreamingSession,
        dm: DraftManager,
        total_output_chars: int,
    ) -> StreamResult:
        """Handle user cancellation."""
        partial_answer = stream.get_final_text()
        partial_display = stream.get_final_display()

        # Add interrupted indicator
        stopped_suffix = "\n\n_\\[interrupted\\]_"
        if partial_display.strip():
            partial_display = partial_display + stopped_suffix
        else:
            partial_display = "_\\[interrupted\\]_"

        # Finalize draft
        final_message = None
        try:
            final_message = await dm.current.finalize(final_text=partial_display
                                                     )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.info(
                "orchestrator.cancelled.finalize_failed",
                thread_id=self._thread_id,
                error=str(e),
            )

        thinking_chars = stream.display.total_thinking_length()

        logger.info(
            "orchestrator.cancelled",
            thread_id=self._thread_id,
            partial_answer_length=len(partial_answer),
            thinking_chars=thinking_chars,
        )

        return StreamResult(
            text=partial_answer,
            display_text=partial_display,
            message=final_message,
            was_cancelled=True,
            cancellation_reason=CancellationReason.STOP_COMMAND,
            thinking_chars=thinking_chars,
            output_chars=total_output_chars,
            has_sent_parts=stream.has_sent_parts,
        )

    async def _handle_completion(
        self,
        stream: StreamingSession,
        dm: DraftManager,
        iterations: int,
    ) -> StreamResult:
        """Handle normal completion (end_turn/pause_turn)."""
        final_answer = stream.get_final_text()
        final_display = stream.get_final_display()

        logger.info(
            "orchestrator.complete",
            thread_id=self._thread_id,
            total_iterations=iterations,
            final_answer_length=len(final_answer),
            stop_reason=stream.stop_reason,
        )

        # Note: if tools were executed but no final text, that's OK.
        # Tool results are already displayed via sent_parts.

        # Finalize draft
        final_message = None
        if final_display.strip():
            try:
                final_message = await dm.current.finalize(
                    final_text=final_display)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.info(
                    "orchestrator.finalize_failed",
                    thread_id=self._thread_id,
                    error=str(e),
                )
        else:
            await dm.current.clear()

        return StreamResult(
            text=final_answer,
            display_text=final_display,
            message=final_message,
            iterations=iterations,
            has_sent_parts=stream.has_sent_parts,
        )

    async def _execute_tools(
        self,
        stream: StreamingSession,
        dm: DraftManager,
        conversation: list,
        cancel_event,
        iteration: int,
    ) -> StreamResult | None:
        """Execute pending tools and update conversation.

        Returns:
            StreamResult if we should stop (turn break or cancellation).
            None if we should continue to next iteration.
        """
        pending_tools = stream.pending_tools
        tool_names = [t.name for t in pending_tools]

        logger.info(
            "orchestrator.executing_tools",
            thread_id=self._thread_id,
            tool_count=len(pending_tools),
            tool_names=tool_names,
        )

        # File processing callback
        first_file_committed = False

        async def on_file_ready(result: dict, tool) -> None:
            nonlocal first_file_committed
            if not first_file_committed:
                await stream.commit_for_files()
                first_file_committed = True
            await process_generated_files(
                result,
                self._first_message,
                self._thread_id,
                self._session,
                self._user_file_repo,
                self._chat_id,
                self._user_id,
                self._telegram_thread_id,
            )

        # Callback for subagent tool progress (e.g., self_critique)
        async def on_subagent_tool(parent_tool: str, sub_tool: str) -> None:
            await stream.add_subagent_tool(parent_tool, sub_tool)

        # Callback for extended_thinking thinking chunks (streaming to expandable blockquote)
        async def on_thinking_chunk(chunk: str) -> None:
            await stream.handle_thinking_delta(chunk)

        # Execute tools
        executor = self._get_tool_executor()
        batch_result = await executor.execute_batch(
            pending_tools,
            cancel_event=cancel_event,
            on_file_ready=on_file_ready,
            on_subagent_tool=on_subagent_tool,
            on_thinking_chunk=on_thinking_chunk,
            model_id=self._request.model,
        )

        # Add system messages
        for exec_result in batch_result.results:
            if not exec_result.is_error:
                tool_system_msg = get_tool_system_message(
                    exec_result.tool.name,
                    exec_result.tool.input,
                    exec_result.result,
                )
                if tool_system_msg:
                    stream.add_system_message(tool_system_msg)

        await stream.update_display()

        # Format tool results for Claude
        tool_uses = [{"id": t.tool_id, "name": t.name} for t in pending_tools]
        results = [r.result for r in batch_result.results]
        tool_results = format_tool_results(tool_uses, results)

        # Add to conversation
        captured_msg = stream.captured_message
        if captured_msg and captured_msg.content:
            serialized_content = [
                serialize_content_block(block) for block in captured_msg.content
            ]
            conversation.append({
                "role": "assistant",
                "content": serialized_content
            })
            conversation.append({"role": "user", "content": tool_results})
        else:
            logger.error(
                "orchestrator.no_assistant_message",
                thread_id=self._thread_id,
                tool_count=len(pending_tools),
            )
            await dm.current.clear()
            return StreamResult(
                text="⚠️ Tool execution error: missing assistant context",
                display_text=
                "⚠️ Tool execution error: missing assistant context",
                was_cancelled=True,
                cancellation_reason=CancellationReason.ERROR,
            )

        await stream.update_display()

        logger.info(
            "orchestrator.tool_results_added",
            thread_id=self._thread_id,
            tool_count=len(pending_tools),
        )

        # Check for cancellation after tools
        if cancel_event.is_set():
            return await self._handle_cancellation(stream, dm, 0)

        # Check for turn break
        if batch_result.force_turn_break:
            logger.info(
                "orchestrator.forcing_turn_break",
                thread_id=self._thread_id,
                triggered_by=batch_result.turn_break_tool,
            )

            partial_answer = stream.get_final_text()
            partial_display = stream.get_final_display()

            final_message = None
            if partial_display.strip():
                try:
                    final_message = await dm.current.finalize(
                        final_text=partial_display)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.info(
                        "orchestrator.turn_break.finalize_failed",
                        thread_id=self._thread_id,
                        error=str(e),
                    )

            return StreamResult(
                text=partial_answer,
                display_text=partial_display,
                message=final_message,
                needs_continuation=True,
                conversation=conversation,
                has_sent_parts=stream.has_sent_parts,
                has_delivered_files=batch_result.turn_break_tool ==
                "deliver_file",
            )

        # Continue to next iteration
        return None

    async def _handle_unexpected_stop(
        self,
        stream: StreamingSession,
        dm: DraftManager,
    ) -> StreamResult:
        """Handle unexpected stop reason."""
        logger.info(
            "orchestrator.unexpected_stop",
            thread_id=self._thread_id,
            stop_reason=stream.stop_reason,
        )

        final_answer = stream.get_final_text()
        if not final_answer:
            final_answer = f"⚠️ Unexpected stop: {stream.stop_reason}"

        final_display = stream.get_final_display()
        if final_display:
            await dm.current.update(final_display, force=True)
        else:
            from telegram.streaming.formatting import escape_html
            await dm.current.update(
                escape_html(f"⚠️ Unexpected stop: {stream.stop_reason}"),
                force=True)

        try:
            final_message = await dm.current.finalize()
        except Exception:  # pylint: disable=broad-exception-caught
            final_message = None

        return StreamResult(
            text=final_answer,
            display_text=final_display or final_answer,
            message=final_message,
            has_sent_parts=stream.has_sent_parts,
        )

    async def _handle_max_iterations(
        self,
        dm: DraftManager,
    ) -> StreamResult:
        """Handle max iterations exceeded."""
        logger.warning(
            "orchestrator.max_iterations",
            thread_id=self._thread_id,
            max_iterations=TOOL_LOOP_MAX_ITERATIONS,
        )

        error_msg = (
            f"⚠️ Tool loop exceeded maximum iterations ({TOOL_LOOP_MAX_ITERATIONS}). "
            "The task might be too complex.")

        try:
            await dm.current.update(error_msg)
            final_message = await dm.current.finalize()
        except Exception:  # pylint: disable=broad-exception-caught
            final_message = None

        return StreamResult(
            text=error_msg,
            display_text=error_msg,
            message=final_message,
            was_cancelled=True,
            cancellation_reason=CancellationReason.MAX_ITERATIONS,
        )
