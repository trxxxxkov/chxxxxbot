"""Context extractors for Telegram messages.

Extracts contextual information from aiogram message types for storage
in the database. This includes sender display, forward origin, reply
context, and quote data.

NO __init__.py - use direct import:
    from telegram.context.extractors import extract_message_context
"""

from dataclasses import dataclass
from typing import Optional

from aiogram import types

# Maximum length for reply snippet
REPLY_SNIPPET_MAX_LENGTH = 200


@dataclass
class MessageContext:
    """Extracted context from a Telegram message.

    Attributes:
        sender_display: @username or "First Last" for message sender.
        forward_origin: Forward origin dict or None.
        reply_snippet: First 200 chars of replied message or None.
        reply_sender_display: @username or "First Last" of replied sender.
        quote_data: Quote dict {text, position, is_manual} or None.
    """

    sender_display: Optional[str] = None
    forward_origin: Optional[dict] = None
    reply_snippet: Optional[str] = None
    reply_sender_display: Optional[str] = None
    quote_data: Optional[dict] = None


def get_sender_display(user: Optional[types.User]) -> Optional[str]:
    """Get display name for a user.

    Returns @username if available, otherwise "First Last" name.

    Args:
        user: Telegram User object or None.

    Returns:
        Display string like "@username" or "First Last", or None if no user.
    """
    if not user:
        return None

    if user.username:
        return f"@{user.username}"

    # Build full name from first_name and optional last_name
    name_parts = [user.first_name]
    if user.last_name:
        name_parts.append(user.last_name)
    return " ".join(name_parts)


def extract_forward_origin(
    forward_origin: Optional[types.MessageOrigin],) -> Optional[dict]:
    """Extract forward origin information.

    Handles all MessageOrigin types:
    - MessageOriginUser: from a user
    - MessageOriginChat: from a chat
    - MessageOriginChannel: from a channel
    - MessageOriginHiddenUser: from a hidden user

    Args:
        forward_origin: Telegram MessageOrigin object or None.

    Returns:
        Dict with {type, display, date, chat_id?, message_id?} or None.
    """
    if not forward_origin:
        return None

    result = {
        "type":
            forward_origin.type,
        "date":
            forward_origin.date.timestamp() if
            hasattr(forward_origin, "date") and forward_origin.date else None,
    }

    if isinstance(forward_origin, types.MessageOriginUser):
        result["display"] = get_sender_display(forward_origin.sender_user)

    elif isinstance(forward_origin, types.MessageOriginChat):
        chat = forward_origin.sender_chat
        if chat.username:
            result["display"] = f"@{chat.username}"
        else:
            result["display"] = chat.title or "Unknown Chat"
        result["chat_id"] = chat.id

    elif isinstance(forward_origin, types.MessageOriginChannel):
        channel = forward_origin.chat
        if channel.username:
            result["display"] = f"@{channel.username}"
        else:
            result["display"] = channel.title or "Unknown Channel"
        result["chat_id"] = channel.id
        result["message_id"] = forward_origin.message_id

    elif isinstance(forward_origin, types.MessageOriginHiddenUser):
        result["display"] = forward_origin.sender_user_name or "Hidden User"

    else:
        result["display"] = "Unknown"

    return result


def extract_quote_data(quote: Optional[types.TextQuote]) -> Optional[dict]:
    """Extract quote information from a reply.

    Args:
        quote: Telegram TextQuote object or None.

    Returns:
        Dict with {text, position, is_manual} or None.
    """
    if not quote:
        return None

    return {
        "text": quote.text,
        "position": quote.position,
        "is_manual": quote.is_manual or False,
    }


def extract_reply_context(
    reply_to_message: Optional[types.Message],
) -> tuple[Optional[str], Optional[str]]:
    """Extract reply context from replied message.

    Args:
        reply_to_message: Telegram Message that was replied to, or None.

    Returns:
        Tuple of (reply_snippet, reply_sender_display).
        Both can be None if no reply or no content.
    """
    if not reply_to_message:
        return None, None

    # Get sender display
    sender_display = get_sender_display(reply_to_message.from_user)

    # Get text snippet (text or caption)
    text = reply_to_message.text or reply_to_message.caption
    snippet = None
    if text:
        snippet = text[:REPLY_SNIPPET_MAX_LENGTH]
        if len(text) > REPLY_SNIPPET_MAX_LENGTH:
            snippet += "..."

    return snippet, sender_display


def extract_message_context(message: types.Message) -> MessageContext:
    """Extract all context information from a Telegram message.

    This is the main function to use when processing incoming messages.
    It extracts sender display, forward origin, reply context, and quote data.

    Args:
        message: Telegram Message object.

    Returns:
        MessageContext dataclass with all extracted information.
    """
    # Extract sender display
    sender_display = get_sender_display(message.from_user)

    # Extract forward origin
    forward_origin = extract_forward_origin(message.forward_origin)

    # Extract reply context
    reply_snippet, reply_sender_display = extract_reply_context(
        message.reply_to_message)

    # Extract quote data
    quote_data = extract_quote_data(message.quote)

    return MessageContext(
        sender_display=sender_display,
        forward_origin=forward_origin,
        reply_snippet=reply_snippet,
        reply_sender_display=reply_sender_display,
        quote_data=quote_data,
    )
