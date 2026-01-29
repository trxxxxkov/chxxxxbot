"""Context formatter for Claude messages.

Formats database messages into LLM-ready messages with contextual
information (sender, replies, quotes, forwards) in Markdown format.

Supports multimodal content:
- Images are included directly in message content using Anthropic's format
- PDFs can also be included for Claude's document understanding

NO __init__.py - use direct import:
    from telegram.context.formatter import ContextFormatter
"""

from typing import Any, TYPE_CHECKING

from core.models import Message as LLMMessage
from db.models.message import Message as DBMessage
from db.models.user_file import FileType

if TYPE_CHECKING:
    from db.models.user_file import UserFile
    from db.repositories.user_file_repository import UserFileRepository
    from sqlalchemy.ext.asyncio import AsyncSession


class ContextFormatter:
    """Formats conversation history for Claude with Telegram context.

    Uses a tiered approach:
    - Simple messages (private chat, no context): plain text
    - Messages with context (reply, quote, forward): Markdown formatting
    - Group chats: always include sender

    Attributes:
        chat_type: Type of chat (private, group, supergroup, channel).
        is_group: Whether the chat is a group/supergroup.
    """

    def __init__(self, chat_type: str = "private"):
        """Initialize formatter with chat type.

        Args:
            chat_type: Type of chat from Telegram (private, group,
                supergroup, channel). Defaults to "private".
        """
        self.chat_type = chat_type
        self.is_group = chat_type in ("group", "supergroup")

    def format_message(self, msg: DBMessage) -> LLMMessage:
        """Format a single database message for LLM.

        Args:
            msg: Database Message object with context fields.

        Returns:
            LLM Message with formatted content.
        """
        role = "user" if msg.from_user_id else "assistant"

        # Always use text_content - thinking blocks are not passed to context
        # to save tokens (up to 16K per response with extended thinking)
        text_content = self._format_content(msg)
        # Ensure we never return empty content (API requires non-empty)
        if not text_content:
            text_content = "[empty message]"
        return LLMMessage(role=role, content=text_content)

    def _format_content(self, msg: DBMessage) -> str:
        """Format message content with context.

        Applies Markdown formatting when needed:
        - Sender header (always in groups, or when other context present)
        - Reply block (if replying to a message)
        - Quote block (if quoting text)
        - Forward indicator (if forwarded)
        - Edit indicator (if edited)

        Args:
            msg: Database Message object.

        Returns:
            Formatted content string.
        """
        text = msg.text_content or msg.caption or ""
        parts = []

        # Check if we need any context formatting
        has_context = (msg.forward_origin or msg.reply_snippet or
                       msg.quote_data or
                       (msg.edit_count and msg.edit_count > 0))

        # Determine if we need sender header
        # - Always in groups
        # - In private chats only if there's other context
        needs_sender = self.is_group or has_context

        # 1. Sender header (if needed and available)
        if needs_sender and msg.sender_display:
            edit_suffix = ""
            if msg.edit_count and msg.edit_count > 0:
                edit_suffix = f" (edited {msg.edit_count}x)"
            parts.append(f"**{msg.sender_display}**{edit_suffix}:")

        # 2. Forward indicator
        if msg.forward_origin:
            forward = msg.forward_origin
            display = forward.get("display", "Unknown")
            parts.append(f"Forwarded from {display}:")

        # 3. Reply block
        if msg.reply_snippet:
            reply_sender = msg.reply_sender_display or "Unknown"
            snippet = msg.reply_snippet
            # Escape snippet for markdown blockquote
            snippet_escaped = snippet.replace("\n", "\n> ")
            parts.append(f'> Replying to {reply_sender}: "{snippet_escaped}"')

        # 4. Quote block (if present)
        if msg.quote_data:
            quote_text = msg.quote_data.get("text", "")
            if quote_text:
                # Escape quote for markdown blockquote
                quote_escaped = quote_text.replace("\n", "\n> ")
                parts.append(f"> Quote: \"{quote_escaped}\"")

        # 5. Message text
        if text:
            parts.append(text)

        # Join with newlines if we have context, otherwise just return text
        if len(parts) > 1:
            return "\n\n".join(parts)
        elif parts:
            return parts[0]
        else:
            return ""

    def format_conversation(
        self,
        messages: list[DBMessage],
    ) -> list[LLMMessage]:
        """Format a list of database messages for LLM.

        Args:
            messages: List of database Message objects.

        Returns:
            List of LLM Message objects with formatted content.
        """
        return [self.format_message(msg) for msg in messages]

    async def format_conversation_with_files(
        self,
        messages: list[DBMessage],
        session: "AsyncSession",
    ) -> list[LLMMessage]:
        """Format messages with multimodal file content.

        For user messages with attached images/PDFs, includes them directly
        in the message content using Claude's multimodal format.

        Anthropic multimodal format:
        {
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "file", "file_id": "..."}},
                {"type": "text", "text": "What's in this image?"}
            ]
        }

        Args:
            messages: List of database Message objects.
            session: Database session for querying files.

        Returns:
            List of LLM Message objects with multimodal content.
        """
        from db.repositories.user_file_repository import UserFileRepository

        file_repo = UserFileRepository(session)
        result = []

        for msg in messages:
            formatted = await self._format_message_with_files(msg, file_repo)
            result.append(formatted)

        return result

    async def _format_message_with_files(
        self,
        msg: DBMessage,
        file_repo: "UserFileRepository",
    ) -> LLMMessage:
        """Format a single message with any attached files.

        Args:
            msg: Database Message object.
            file_repo: UserFileRepository for querying files.

        Returns:
            LLM Message with multimodal content if files present.
        """
        role = "user" if msg.from_user_id else "assistant"

        # Always use text_content - thinking blocks are not passed to context
        # to save tokens (up to 16K per response with extended thinking)
        text_content = self._format_content(msg)

        # For user messages, check for ALL attached files
        if msg.from_user_id:
            # Get all files for this message (no type filter)
            all_files = await file_repo.get_by_message_id(msg.message_id)

            if all_files:
                # Separate visual files (Claude can see) from other files
                visual_files = [
                    f for f in all_files
                    if f.file_type in (FileType.IMAGE, FileType.PDF)
                ]
                other_files = [
                    f for f in all_files
                    if f.file_type not in (FileType.IMAGE, FileType.PDF)
                ]

                # Add text description for non-visual files
                if other_files:
                    file_descriptions = []
                    for f in other_files:
                        file_descriptions.append(
                            f"[Attached: {f.filename} - "
                            f"see Available Files section to analyze]")
                    files_text = "\n".join(file_descriptions)
                    if text_content:
                        text_content = f"{text_content}\n\n{files_text}"
                    else:
                        text_content = files_text

                # Build multimodal content if visual files present
                if visual_files:
                    content_blocks = self._build_multimodal_content(
                        visual_files, text_content)
                    return LLMMessage(role=role, content=content_blocks)

        # No visual files - return simple text format
        # Ensure we never return empty content (API requires non-empty)
        if not text_content:
            text_content = "[empty message]"
        return LLMMessage(role=role, content=text_content)

    def _build_multimodal_content(
        self,
        files: list["UserFile"],
        text_content: str,
    ) -> list[dict[str, Any]]:
        """Build multimodal content blocks from files and text.

        Args:
            files: List of UserFile objects with claude_file_id.
            text_content: Text content to include.

        Returns:
            List of content blocks in Anthropic format.
        """
        content_blocks: list[dict[str, Any]] = []

        # Add file blocks first (images, then PDFs)
        for file in files:
            if not file.claude_file_id:
                continue

            if file.file_type == FileType.IMAGE:
                content_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "file",
                        "file_id": file.claude_file_id,
                    }
                })
            elif file.file_type == FileType.PDF:
                content_blocks.append({
                    "type": "document",
                    "source": {
                        "type": "file",
                        "file_id": file.claude_file_id,
                    }
                })

        # Add text block (always add at least placeholder to ensure non-empty)
        if text_content:
            content_blocks.append({
                "type": "text",
                "text": text_content,
            })
        elif not content_blocks:
            # Fallback: ensure we never return empty content
            content_blocks.append({
                "type": "text",
                "text": "[empty message]",
            })

        return content_blocks


def format_for_llm(
    messages: list[DBMessage],
    chat_type: str = "private",
) -> list[LLMMessage]:
    """Convenience function to format messages for LLM.

    Args:
        messages: List of database Message objects.
        chat_type: Type of chat (private, group, supergroup, channel).

    Returns:
        List of LLM Message objects with formatted content.
    """
    formatter = ContextFormatter(chat_type=chat_type)
    return formatter.format_conversation(messages)
