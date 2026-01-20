"""Context formatter for Claude messages.

Formats database messages into LLM-ready messages with contextual
information (sender, replies, quotes, forwards) in Markdown format.

NO __init__.py - use direct import:
    from telegram.context.formatter import ContextFormatter
"""

import json
from typing import Any, Optional, Union

from core.models import Message as LLMMessage
from db.models.message import Message as DBMessage
from db.models.message import MessageRole


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

        For assistant messages with thinking_blocks, formats content as
        a list with thinking block first (required when Extended Thinking
        is enabled).

        Args:
            msg: Database Message object with context fields.

        Returns:
            LLM Message with formatted content.
        """
        role = "user" if msg.from_user_id else "assistant"
        text_content = self._format_content(msg)

        # For assistant messages with thinking, format as content blocks
        # (required by Claude API when extended thinking is enabled)
        if msg.role == MessageRole.ASSISTANT and msg.thinking_blocks:
            # thinking_blocks is stored as JSON string with full blocks + signatures
            try:
                thinking_list = json.loads(msg.thinking_blocks)
                # Verify blocks have signatures (required by API)
                if thinking_list and "signature" in thinking_list[0]:
                    # Build content: thinking blocks first, then text
                    content: Union[str, list[dict[str,
                                                  Any]]] = thinking_list + [{
                                                      "type": "text",
                                                      "text": text_content
                                                  }]
                else:
                    # JSON but no signature - skip thinking (legacy or invalid)
                    content = text_content
            except (json.JSONDecodeError, TypeError):
                # Not valid JSON (legacy plain text format) - skip thinking
                # Old messages without signatures will cause API errors
                content = text_content
        else:
            content = text_content

        return LLMMessage(role=role, content=content)

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
