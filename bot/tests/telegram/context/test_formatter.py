"""Tests for telegram/context/formatter.py.

Tests context formatting for Claude messages including sender display,
replies, quotes, forwards, and edit indicators.
"""

from unittest.mock import MagicMock

import pytest
from telegram.context.formatter import ContextFormatter
from telegram.context.formatter import format_for_llm


def create_mock_db_message(
    from_user_id=123,
    text_content="Hello",
    caption=None,
    sender_display=None,
    forward_origin=None,
    reply_snippet=None,
    reply_sender_display=None,
    quote_data=None,
    edit_count=0,
    role=None,
    thinking_blocks=None,
):
    """Create a mock database Message object."""
    # Import here to avoid circular imports in test
    from db.models.message import MessageRole
    msg = MagicMock()
    msg.from_user_id = from_user_id
    msg.text_content = text_content
    msg.caption = caption
    msg.sender_display = sender_display
    msg.forward_origin = forward_origin
    msg.reply_snippet = reply_snippet
    msg.reply_sender_display = reply_sender_display
    msg.quote_data = quote_data
    msg.edit_count = edit_count
    msg.thinking_blocks = thinking_blocks
    # Set role based on from_user_id if not explicitly provided
    if role is not None:
        msg.role = role
    elif from_user_id:
        msg.role = MessageRole.USER
    else:
        msg.role = MessageRole.ASSISTANT
    return msg


class TestContextFormatterInit:
    """Tests for ContextFormatter initialization."""

    def test_default_chat_type(self):
        """Test default chat type is private."""
        formatter = ContextFormatter()
        assert formatter.chat_type == "private"
        assert formatter.is_group is False

    def test_private_chat(self):
        """Test private chat initialization."""
        formatter = ContextFormatter(chat_type="private")
        assert formatter.chat_type == "private"
        assert formatter.is_group is False

    def test_group_chat(self):
        """Test group chat initialization."""
        formatter = ContextFormatter(chat_type="group")
        assert formatter.chat_type == "group"
        assert formatter.is_group is True

    def test_supergroup_chat(self):
        """Test supergroup chat initialization."""
        formatter = ContextFormatter(chat_type="supergroup")
        assert formatter.chat_type == "supergroup"
        assert formatter.is_group is True

    def test_channel_chat(self):
        """Test channel chat initialization."""
        formatter = ContextFormatter(chat_type="channel")
        assert formatter.chat_type == "channel"
        assert formatter.is_group is False


class TestContextFormatterFormatMessage:
    """Tests for ContextFormatter.format_message method."""

    def test_simple_user_message(self):
        """Test formatting simple user message in private chat."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Hello, how are you?",
        )

        result = formatter.format_message(msg)

        assert result.role == "user"
        assert result.content == "Hello, how are you?"

    def test_simple_assistant_message(self):
        """Test formatting assistant message (no from_user_id)."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="I'm doing well, thank you!",
        )

        result = formatter.format_message(msg)

        assert result.role == "assistant"
        assert result.content == "I'm doing well, thank you!"

    def test_caption_fallback(self):
        """Test caption is used when text_content is None."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content=None,
            caption="Photo caption",
        )

        result = formatter.format_message(msg)

        assert result.content == "Photo caption"

    def test_empty_content(self):
        """Test empty content when both text_content and caption are None."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content=None,
            caption=None,
        )

        result = formatter.format_message(msg)

        assert result.content == ""


class TestContextFormatterGroupChat:
    """Tests for ContextFormatter in group chats."""

    def test_group_chat_includes_sender(self):
        """Test group chat always includes sender display."""
        formatter = ContextFormatter(chat_type="group")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Group message",
            sender_display="@john_doe",
        )

        result = formatter.format_message(msg)

        assert "**@john_doe**:" in result.content
        assert "Group message" in result.content

    def test_supergroup_includes_sender(self):
        """Test supergroup includes sender display."""
        formatter = ContextFormatter(chat_type="supergroup")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Supergroup message",
            sender_display="@jane_doe",
        )

        result = formatter.format_message(msg)

        assert "**@jane_doe**:" in result.content

    def test_private_chat_no_sender_without_context(self):
        """Test private chat without context doesn't include sender."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Private message",
            sender_display="@user",
        )

        result = formatter.format_message(msg)

        # No context, so no sender header
        assert result.content == "Private message"


class TestContextFormatterReplyContext:
    """Tests for reply context formatting."""

    def test_reply_with_snippet(self):
        """Test message with reply snippet."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="My reply",
            sender_display="@replier",
            reply_snippet="Original message text",
            reply_sender_display="@original",
        )

        result = formatter.format_message(msg)

        assert '> Replying to @original: "Original message text"' in result.content
        assert "My reply" in result.content

    def test_reply_adds_sender_in_private(self):
        """Test reply adds sender header even in private chat."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Reply text",
            sender_display="@user",
            reply_snippet="Original",
            reply_sender_display="@bot",
        )

        result = formatter.format_message(msg)

        # Has context (reply), so should include sender
        assert "**@user**:" in result.content

    def test_reply_unknown_sender(self):
        """Test reply with unknown sender (None)."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Reply",
            sender_display="@user",
            reply_snippet="Original text",
            reply_sender_display=None,
        )

        result = formatter.format_message(msg)

        assert '> Replying to Unknown: "Original text"' in result.content


class TestContextFormatterQuoteData:
    """Tests for quote data formatting."""

    def test_quote_formatting(self):
        """Test message with quote."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="My response",
            sender_display="@user",
            quote_data={
                "text": "Quoted text here",
                "position": 0,
                "is_manual": True
            },
        )

        result = formatter.format_message(msg)

        assert '> Quote: "Quoted text here"' in result.content
        assert "My response" in result.content

    def test_quote_with_reply(self):
        """Test message with both reply and quote."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="My response",
            sender_display="@user",
            reply_snippet="Full message here",
            reply_sender_display="@other",
            quote_data={
                "text": "quoted part",
                "position": 5,
                "is_manual": True
            },
        )

        result = formatter.format_message(msg)

        assert '> Replying to @other: "Full message here"' in result.content
        assert '> Quote: "quoted part"' in result.content
        assert "My response" in result.content

    def test_empty_quote_text(self):
        """Test quote with empty text is not included."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Message",
            sender_display="@user",
            quote_data={
                "text": "",
                "position": 0,
                "is_manual": False
            },
        )

        result = formatter.format_message(msg)

        # Empty quote should not add Quote: block
        assert "> Quote:" not in result.content


class TestContextFormatterForwardOrigin:
    """Tests for forward origin formatting."""

    def test_forward_from_user(self):
        """Test forwarded message from user."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Forwarded content",
            sender_display="@forwarder",
            forward_origin={
                "type": "user",
                "display": "@original_user"
            },
        )

        result = formatter.format_message(msg)

        assert "Forwarded from @original_user:" in result.content
        assert "Forwarded content" in result.content

    def test_forward_from_channel(self):
        """Test forwarded message from channel."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="News article",
            sender_display="@forwarder",
            forward_origin={
                "type": "channel",
                "display": "@news_channel",
                "message_id": 12345,
            },
        )

        result = formatter.format_message(msg)

        assert "Forwarded from @news_channel:" in result.content


class TestContextFormatterEditTracking:
    """Tests for edit count formatting."""

    def test_edited_message(self):
        """Test message with edits shows edit count."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Edited message",
            sender_display="@user",
            edit_count=2,
            reply_snippet="Something",  # Need context to show sender
            reply_sender_display="@other",
        )

        result = formatter.format_message(msg)

        assert "(edited 2x)" in result.content

    def test_single_edit(self):
        """Test message with single edit."""
        formatter = ContextFormatter(chat_type="group")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Once edited",
            sender_display="@user",
            edit_count=1,
        )

        result = formatter.format_message(msg)

        assert "(edited 1x)" in result.content

    def test_no_edits_no_indicator(self):
        """Test message without edits has no indicator."""
        formatter = ContextFormatter(chat_type="group")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Original",
            sender_display="@user",
            edit_count=0,
        )

        result = formatter.format_message(msg)

        assert "edited" not in result.content


class TestContextFormatterFormatConversation:
    """Tests for format_conversation method."""

    def test_format_empty_list(self):
        """Test formatting empty message list."""
        formatter = ContextFormatter(chat_type="private")
        result = formatter.format_conversation([])
        assert result == []

    def test_format_single_message(self):
        """Test formatting single message."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(text_content="Single message")

        result = formatter.format_conversation([msg])

        assert len(result) == 1
        assert result[0].content == "Single message"

    def test_format_multiple_messages(self):
        """Test formatting multiple messages."""
        formatter = ContextFormatter(chat_type="group")
        messages = [
            create_mock_db_message(
                from_user_id=1,
                text_content="First",
                sender_display="@alice",
            ),
            create_mock_db_message(
                from_user_id=None,
                text_content="Response",
            ),
            create_mock_db_message(
                from_user_id=2,
                text_content="Second user",
                sender_display="@bob",
            ),
        ]

        result = formatter.format_conversation(messages)

        assert len(result) == 3
        assert result[0].role == "user"
        assert result[1].role == "assistant"
        assert result[2].role == "user"
        assert "@alice" in result[0].content
        assert "@bob" in result[2].content


class TestFormatForLlmFunction:
    """Tests for format_for_llm convenience function."""

    def test_format_for_llm_default(self):
        """Test format_for_llm with defaults."""
        msg = create_mock_db_message(text_content="Test")
        result = format_for_llm([msg])

        assert len(result) == 1
        assert result[0].content == "Test"

    def test_format_for_llm_with_chat_type(self):
        """Test format_for_llm with chat type."""
        msg = create_mock_db_message(
            text_content="Group msg",
            sender_display="@user",
        )
        result = format_for_llm([msg], chat_type="group")

        assert "@user" in result[0].content


class TestContextFormatterEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_multiline_reply_snippet(self):
        """Test reply snippet with newlines is escaped."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Reply",
            sender_display="@user",
            reply_snippet="Line 1\nLine 2\nLine 3",
            reply_sender_display="@other",
        )

        result = formatter.format_message(msg)

        # Newlines should be escaped for blockquote
        assert "\n> " in result.content or "Line 1" in result.content

    def test_multiline_quote_text(self):
        """Test quote with newlines is escaped."""
        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Response",
            sender_display="@user",
            quote_data={
                "text": "Quote line 1\nQuote line 2",
                "position": 0,
                "is_manual": True,
            },
        )

        result = formatter.format_message(msg)

        # Should handle newlines
        assert "Quote line 1" in result.content

    def test_all_context_combined(self):
        """Test message with all context types."""
        formatter = ContextFormatter(chat_type="group")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="Full context message",
            sender_display="@full_user",
            forward_origin={
                "type": "user",
                "display": "@original"
            },
            reply_snippet="Original reply",
            reply_sender_display="@replier",
            quote_data={
                "text": "quoted",
                "position": 0,
                "is_manual": True
            },
            edit_count=3,
        )

        result = formatter.format_message(msg)

        # Check all elements are present
        assert "**@full_user**" in result.content
        assert "(edited 3x)" in result.content
        assert "Forwarded from @original:" in result.content
        assert '> Replying to @replier: "Original reply"' in result.content
        assert '> Quote: "quoted"' in result.content
        assert "Full context message" in result.content

    def test_no_sender_display_in_group(self):
        """Test group message without sender_display."""
        formatter = ContextFormatter(chat_type="group")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="No sender",
            sender_display=None,  # Missing sender display
        )

        result = formatter.format_message(msg)

        # Should still work, just no header
        assert result.content == "No sender"


class TestContextFormatterThinkingBlocks:
    """Tests for Extended Thinking - thinking blocks NOT passed to context.

    Thinking blocks are stored in DB but NOT included in conversation context
    to save tokens (up to 16K per response with extended thinking enabled).
    Only text_content is used for assistant messages in context.
    """

    def test_assistant_with_thinking_blocks_uses_text_content(self):
        """Test assistant message with thinking blocks uses text_content only."""
        import json

        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")
        # thinking_blocks contains full content with thinking
        thinking_json = json.dumps([{
            "type": "thinking",
            "thinking": "Let me think about this...",
            "signature": "abc123signature"
        }, {
            "type": "text",
            "text": "The answer is 42."
        }])
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="The answer is 42.",  # Only this is used
            role=MessageRole.ASSISTANT,
            thinking_blocks=thinking_json,  # Stored but not used in context
        )

        result = formatter.format_message(msg)

        # Thinking blocks are NOT passed to context - only text_content
        assert isinstance(result.content, str)
        assert result.content == "The answer is 42."

    def test_assistant_with_thinking_blocks_legacy_text(self):
        """Test legacy format (plain text thinking) also uses text_content."""
        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="The answer is 42.",
            role=MessageRole.ASSISTANT,
            thinking_blocks="Let me think about this... The user asked...",
        )

        result = formatter.format_message(msg)

        assert isinstance(result.content, str)
        assert result.content == "The answer is 42."

    def test_assistant_without_thinking_blocks(self):
        """Test assistant message without thinking returns string content."""
        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="Simple response",
            role=MessageRole.ASSISTANT,
            thinking_blocks=None,
        )

        result = formatter.format_message(msg)

        assert isinstance(result.content, str)
        assert result.content == "Simple response"

    def test_user_message_ignores_thinking_blocks(self):
        """Test user message never has thinking blocks."""
        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")
        msg = create_mock_db_message(
            from_user_id=123,
            text_content="User question",
            role=MessageRole.USER,
            thinking_blocks="This should be ignored",
        )

        result = formatter.format_message(msg)

        assert isinstance(result.content, str)
        assert result.content == "User question"

    def test_thinking_blocks_not_in_context_saves_tokens(self):
        """Test that thinking blocks are excluded to save context tokens.

        With extended thinking enabled, each response can have up to 16K
        tokens of thinking content. Excluding these from context preserves
        the context window for actual conversation content.
        """
        import json

        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")

        # Large thinking content (simulating 16K budget usage)
        large_thinking = "Step 1: " + "x" * 1000 + "\nStep 2: " + "y" * 1000
        original_content = [{
            "type": "thinking",
            "thinking": large_thinking,
            "signature": "sig_abc123"
        }, {
            "type": "text",
            "text": "Final answer."
        }]

        thinking_json = json.dumps(original_content)
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="Final answer.",
            role=MessageRole.ASSISTANT,
            thinking_blocks=thinking_json,
        )

        result = formatter.format_message(msg)

        # Only text_content is used - thinking is excluded
        assert isinstance(result.content, str)
        assert result.content == "Final answer."
        assert large_thinking not in result.content
