"""Tests for telegram/context/extractors.py.

Tests context extraction from Telegram messages including sender display,
forward origin, reply context, and quote data.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock

import pytest
from telegram.context.extractors import extract_forward_origin
from telegram.context.extractors import extract_message_context
from telegram.context.extractors import extract_quote_data
from telegram.context.extractors import extract_reply_context
from telegram.context.extractors import get_sender_display
from telegram.context.extractors import MessageContext
from telegram.context.extractors import REPLY_SNIPPET_MAX_LENGTH


class TestGetSenderDisplay:
    """Tests for get_sender_display function."""

    def test_none_user_returns_none(self):
        """Test that None user returns None."""
        result = get_sender_display(None)
        assert result is None

    def test_user_with_username(self):
        """Test user with username returns @username."""
        user = MagicMock()
        user.username = "john_doe"
        user.first_name = "John"
        user.last_name = "Doe"

        result = get_sender_display(user)
        assert result == "@john_doe"

    def test_user_without_username_first_name_only(self):
        """Test user without username returns first name."""
        user = MagicMock()
        user.username = None
        user.first_name = "John"
        user.last_name = None

        result = get_sender_display(user)
        assert result == "John"

    def test_user_without_username_full_name(self):
        """Test user without username returns full name."""
        user = MagicMock()
        user.username = None
        user.first_name = "John"
        user.last_name = "Doe"

        result = get_sender_display(user)
        assert result == "John Doe"

    def test_username_takes_priority(self):
        """Test username is preferred over name."""
        user = MagicMock()
        user.username = "jdoe"
        user.first_name = "John"
        user.last_name = "Doe"

        result = get_sender_display(user)
        assert result == "@jdoe"


class TestExtractForwardOrigin:
    """Tests for extract_forward_origin function."""

    def test_none_forward_origin_returns_none(self):
        """Test that None forward origin returns None."""
        result = extract_forward_origin(None)
        assert result is None

    def test_forward_origin_user(self):
        """Test extracting forward origin from user."""
        from aiogram import types

        sender_user = MagicMock()
        sender_user.username = "original_user"
        sender_user.first_name = "Original"
        sender_user.last_name = None

        forward_origin = MagicMock(spec=types.MessageOriginUser)
        forward_origin.type = "user"
        forward_origin.date = datetime(2024,
                                       1,
                                       15,
                                       12,
                                       0,
                                       0,
                                       tzinfo=timezone.utc)
        forward_origin.sender_user = sender_user

        result = extract_forward_origin(forward_origin)

        assert result["type"] == "user"
        assert result["display"] == "@original_user"
        assert result["date"] == forward_origin.date.timestamp()

    def test_forward_origin_chat(self):
        """Test extracting forward origin from chat."""
        from aiogram import types

        sender_chat = MagicMock()
        sender_chat.username = "test_group"
        sender_chat.title = "Test Group"
        sender_chat.id = -1001234567890

        forward_origin = MagicMock(spec=types.MessageOriginChat)
        forward_origin.type = "chat"
        forward_origin.date = datetime(2024,
                                       1,
                                       15,
                                       12,
                                       0,
                                       0,
                                       tzinfo=timezone.utc)
        forward_origin.sender_chat = sender_chat

        result = extract_forward_origin(forward_origin)

        assert result["type"] == "chat"
        assert result["display"] == "@test_group"
        assert result["chat_id"] == -1001234567890

    def test_forward_origin_chat_no_username(self):
        """Test extracting forward origin from chat without username."""
        from aiogram import types

        sender_chat = MagicMock()
        sender_chat.username = None
        sender_chat.title = "Private Group"
        sender_chat.id = -1001234567890

        forward_origin = MagicMock(spec=types.MessageOriginChat)
        forward_origin.type = "chat"
        forward_origin.date = datetime(2024,
                                       1,
                                       15,
                                       12,
                                       0,
                                       0,
                                       tzinfo=timezone.utc)
        forward_origin.sender_chat = sender_chat

        result = extract_forward_origin(forward_origin)

        assert result["display"] == "Private Group"

    def test_forward_origin_channel(self):
        """Test extracting forward origin from channel."""
        from aiogram import types

        channel = MagicMock()
        channel.username = "news_channel"
        channel.title = "News Channel"
        channel.id = -1001234567890

        forward_origin = MagicMock(spec=types.MessageOriginChannel)
        forward_origin.type = "channel"
        forward_origin.date = datetime(2024,
                                       1,
                                       15,
                                       12,
                                       0,
                                       0,
                                       tzinfo=timezone.utc)
        forward_origin.chat = channel
        forward_origin.message_id = 12345

        result = extract_forward_origin(forward_origin)

        assert result["type"] == "channel"
        assert result["display"] == "@news_channel"
        assert result["chat_id"] == -1001234567890
        assert result["message_id"] == 12345

    def test_forward_origin_hidden_user(self):
        """Test extracting forward origin from hidden user."""
        from aiogram import types

        forward_origin = MagicMock(spec=types.MessageOriginHiddenUser)
        forward_origin.type = "hidden_user"
        forward_origin.date = datetime(2024,
                                       1,
                                       15,
                                       12,
                                       0,
                                       0,
                                       tzinfo=timezone.utc)
        forward_origin.sender_user_name = "Anonymous User"

        result = extract_forward_origin(forward_origin)

        assert result["type"] == "hidden_user"
        assert result["display"] == "Anonymous User"

    def test_forward_origin_hidden_user_no_name(self):
        """Test extracting forward origin from hidden user without name."""
        from aiogram import types

        forward_origin = MagicMock(spec=types.MessageOriginHiddenUser)
        forward_origin.type = "hidden_user"
        forward_origin.date = datetime(2024,
                                       1,
                                       15,
                                       12,
                                       0,
                                       0,
                                       tzinfo=timezone.utc)
        forward_origin.sender_user_name = None

        result = extract_forward_origin(forward_origin)

        assert result["display"] == "Hidden User"


class TestExtractQuoteData:
    """Tests for extract_quote_data function."""

    def test_none_quote_returns_none(self):
        """Test that None quote returns None."""
        result = extract_quote_data(None)
        assert result is None

    def test_quote_extraction(self):
        """Test extracting quote data."""
        quote = MagicMock()
        quote.text = "This is the quoted text"
        quote.position = 42
        quote.is_manual = True

        result = extract_quote_data(quote)

        assert result["text"] == "This is the quoted text"
        assert result["position"] == 42
        assert result["is_manual"] is True

    def test_quote_is_manual_false(self):
        """Test extracting quote with is_manual=False."""
        quote = MagicMock()
        quote.text = "Quoted text"
        quote.position = 0
        quote.is_manual = False

        result = extract_quote_data(quote)

        assert result["is_manual"] is False

    def test_quote_is_manual_none(self):
        """Test extracting quote with is_manual=None defaults to False."""
        quote = MagicMock()
        quote.text = "Quoted text"
        quote.position = 0
        quote.is_manual = None

        result = extract_quote_data(quote)

        assert result["is_manual"] is False


class TestExtractReplyContext:
    """Tests for extract_reply_context function."""

    def test_none_reply_returns_none_tuple(self):
        """Test that None reply returns (None, None)."""
        snippet, sender = extract_reply_context(None)
        assert snippet is None
        assert sender is None

    def test_reply_with_text(self):
        """Test extracting reply context with text."""
        user = MagicMock()
        user.username = "replier"
        user.first_name = "Reply"
        user.last_name = "User"

        reply_msg = MagicMock()
        reply_msg.text = "This is the original message"
        reply_msg.caption = None
        reply_msg.from_user = user

        snippet, sender = extract_reply_context(reply_msg)

        assert snippet == "This is the original message"
        assert sender == "@replier"

    def test_reply_with_caption(self):
        """Test extracting reply context with caption (no text)."""
        user = MagicMock()
        user.username = None
        user.first_name = "Photo"
        user.last_name = "Sender"

        reply_msg = MagicMock()
        reply_msg.text = None
        reply_msg.caption = "Photo caption"
        reply_msg.from_user = user

        snippet, sender = extract_reply_context(reply_msg)

        assert snippet == "Photo caption"
        assert sender == "Photo Sender"

    def test_reply_long_text_truncated(self):
        """Test that long text is truncated with ellipsis."""
        user = MagicMock()
        user.username = "user"

        long_text = "A" * 300  # Longer than REPLY_SNIPPET_MAX_LENGTH
        reply_msg = MagicMock()
        reply_msg.text = long_text
        reply_msg.caption = None
        reply_msg.from_user = user

        snippet, sender = extract_reply_context(reply_msg)

        assert len(snippet) == REPLY_SNIPPET_MAX_LENGTH + 3  # +3 for "..."
        assert snippet.endswith("...")
        assert snippet[:
                       REPLY_SNIPPET_MAX_LENGTH] == "A" * REPLY_SNIPPET_MAX_LENGTH

    def test_reply_exact_max_length_no_ellipsis(self):
        """Test that text at exact max length has no ellipsis."""
        user = MagicMock()
        user.username = "user"

        exact_text = "A" * REPLY_SNIPPET_MAX_LENGTH
        reply_msg = MagicMock()
        reply_msg.text = exact_text
        reply_msg.caption = None
        reply_msg.from_user = user

        snippet, sender = extract_reply_context(reply_msg)

        assert snippet == exact_text
        assert not snippet.endswith("...")

    def test_reply_no_content(self):
        """Test reply with no text or caption."""
        user = MagicMock()
        user.username = "user"

        reply_msg = MagicMock()
        reply_msg.text = None
        reply_msg.caption = None
        reply_msg.from_user = user

        snippet, sender = extract_reply_context(reply_msg)

        assert snippet is None
        assert sender == "@user"

    def test_reply_no_user(self):
        """Test reply with no from_user (channel message)."""
        reply_msg = MagicMock()
        reply_msg.text = "Channel message"
        reply_msg.caption = None
        reply_msg.from_user = None

        snippet, sender = extract_reply_context(reply_msg)

        assert snippet == "Channel message"
        assert sender is None


class TestExtractMessageContext:
    """Tests for extract_message_context function."""

    def test_simple_message(self):
        """Test extracting context from simple message."""
        user = MagicMock()
        user.username = "sender"
        user.first_name = "Sender"
        user.last_name = None

        message = MagicMock()
        message.from_user = user
        message.forward_origin = None
        message.reply_to_message = None
        message.quote = None

        result = extract_message_context(message)

        assert isinstance(result, MessageContext)
        assert result.sender_display == "@sender"
        assert result.forward_origin is None
        assert result.reply_snippet is None
        assert result.reply_sender_display is None
        assert result.quote_data is None

    def test_message_with_reply(self):
        """Test extracting context from message with reply."""
        sender = MagicMock()
        sender.username = "current_user"

        reply_user = MagicMock()
        reply_user.username = "original_user"

        reply_msg = MagicMock()
        reply_msg.text = "Original message"
        reply_msg.caption = None
        reply_msg.from_user = reply_user

        message = MagicMock()
        message.from_user = sender
        message.forward_origin = None
        message.reply_to_message = reply_msg
        message.quote = None

        result = extract_message_context(message)

        assert result.sender_display == "@current_user"
        assert result.reply_snippet == "Original message"
        assert result.reply_sender_display == "@original_user"

    def test_message_with_quote(self):
        """Test extracting context from message with quote."""
        sender = MagicMock()
        sender.username = "quoter"

        reply_user = MagicMock()
        reply_user.username = "quoted_user"

        reply_msg = MagicMock()
        reply_msg.text = "Full original message"
        reply_msg.caption = None
        reply_msg.from_user = reply_user

        quote = MagicMock()
        quote.text = "quoted part"
        quote.position = 5
        quote.is_manual = True

        message = MagicMock()
        message.from_user = sender
        message.forward_origin = None
        message.reply_to_message = reply_msg
        message.quote = quote

        result = extract_message_context(message)

        assert result.quote_data["text"] == "quoted part"
        assert result.quote_data["position"] == 5
        assert result.quote_data["is_manual"] is True

    def test_message_with_forward(self):
        """Test extracting context from forwarded message."""
        from aiogram import types

        sender = MagicMock()
        sender.username = "forwarder"

        original_sender = MagicMock()
        original_sender.username = "original_author"

        forward_origin = MagicMock(spec=types.MessageOriginUser)
        forward_origin.type = "user"
        forward_origin.date = datetime(2024,
                                       1,
                                       15,
                                       12,
                                       0,
                                       0,
                                       tzinfo=timezone.utc)
        forward_origin.sender_user = original_sender

        message = MagicMock()
        message.from_user = sender
        message.forward_origin = forward_origin
        message.reply_to_message = None
        message.quote = None

        result = extract_message_context(message)

        assert result.sender_display == "@forwarder"
        assert result.forward_origin is not None
        assert result.forward_origin["type"] == "user"
        assert result.forward_origin["display"] == "@original_author"

    def test_message_with_all_context(self):
        """Test extracting context from message with all features."""
        from aiogram import types

        sender = MagicMock()
        sender.username = "complex_user"

        reply_user = MagicMock()
        reply_user.username = "reply_to"

        reply_msg = MagicMock()
        reply_msg.text = "Message being replied to"
        reply_msg.caption = None
        reply_msg.from_user = reply_user

        quote = MagicMock()
        quote.text = "quoted"
        quote.position = 0
        quote.is_manual = False

        original_author = MagicMock()
        original_author.username = "original"

        forward_origin = MagicMock(spec=types.MessageOriginUser)
        forward_origin.type = "user"
        forward_origin.date = datetime(2024,
                                       1,
                                       15,
                                       12,
                                       0,
                                       0,
                                       tzinfo=timezone.utc)
        forward_origin.sender_user = original_author

        message = MagicMock()
        message.from_user = sender
        message.forward_origin = forward_origin
        message.reply_to_message = reply_msg
        message.quote = quote

        result = extract_message_context(message)

        assert result.sender_display == "@complex_user"
        assert result.forward_origin["display"] == "@original"
        assert result.reply_snippet == "Message being replied to"
        assert result.reply_sender_display == "@reply_to"
        assert result.quote_data["text"] == "quoted"


class TestMessageContextDataclass:
    """Tests for MessageContext dataclass."""

    def test_default_values(self):
        """Test that MessageContext has correct defaults."""
        ctx = MessageContext()

        assert ctx.sender_display is None
        assert ctx.forward_origin is None
        assert ctx.reply_snippet is None
        assert ctx.reply_sender_display is None
        assert ctx.quote_data is None

    def test_with_values(self):
        """Test MessageContext with values."""
        ctx = MessageContext(
            sender_display="@user",
            forward_origin={
                "type": "user",
                "display": "@original"
            },
            reply_snippet="Reply text",
            reply_sender_display="@replier",
            quote_data={
                "text": "quoted",
                "position": 0,
                "is_manual": False
            },
        )

        assert ctx.sender_display == "@user"
        assert ctx.forward_origin["type"] == "user"
        assert ctx.reply_snippet == "Reply text"
        assert ctx.reply_sender_display == "@replier"
        assert ctx.quote_data["text"] == "quoted"
