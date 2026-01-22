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
    """Tests for Extended Thinking support."""

    def test_assistant_with_thinking_blocks_json(self):
        """Test assistant message with JSON thinking blocks (with signature)."""
        import json

        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")
        # New format: JSON string with FULL content (thinking + text blocks)
        # This preserves exact Claude response for context reconstruction
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
            text_content="The answer is 42.",  # For display/search
            role=MessageRole.ASSISTANT,
            thinking_blocks=thinking_json,  # Full content for API
        )

        result = formatter.format_message(msg)

        # Content should be used AS-IS from thinking_blocks (not reconstructed)
        assert isinstance(result.content, list)
        assert len(result.content) == 2
        assert result.content[0]["type"] == "thinking"
        assert result.content[0]["thinking"] == "Let me think about this..."
        assert result.content[0]["signature"] == "abc123signature"
        assert result.content[1]["type"] == "text"
        assert result.content[1]["text"] == "The answer is 42."

    def test_assistant_with_thinking_blocks_legacy_text(self):
        """Test fallback for old format (plain text without signature).

        Legacy messages without signatures should return text-only content
        to avoid API errors (signature is required).
        """
        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")
        # Old format: plain text (not JSON)
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="The answer is 42.",
            role=MessageRole.ASSISTANT,
            thinking_blocks="Let me think about this... The user asked...",
        )

        result = formatter.format_message(msg)

        # Legacy format without signature should skip thinking
        # (API requires signature for thinking blocks)
        assert isinstance(result.content, str)
        assert result.content == "The answer is 42."

    def test_assistant_with_thinking_blocks_json_no_signature(self):
        """Test JSON content without signature is used as-is.

        Content preservation is critical - we use saved content exactly
        as received from Claude API. If API requires signature, it will
        reject the request itself.
        """
        import json

        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")
        # JSON content without signature (unlikely but possible)
        thinking_json = json.dumps([
            {
                "type": "thinking",
                "thinking": "Let me think..."
                # No signature field
            },
            {
                "type": "text",
                "text": "The answer is 42."
            }
        ])
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="The answer is 42.",
            role=MessageRole.ASSISTANT,
            thinking_blocks=thinking_json,
        )

        result = formatter.format_message(msg)

        # Content should be used as-is (API will validate signature)
        assert isinstance(result.content, list)
        assert len(result.content) == 2

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

        # Content should be a string
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

        # User messages always return string content
        assert isinstance(result.content, str)
        assert result.content == "User question"

    def test_regression_thinking_blocks_not_modified(self):
        """REGRESSION TEST: Content must be preserved exactly as received.

        Bug: Claude API returned error 'thinking or redacted_thinking blocks
        cannot be modified' because we were reconstructing content from
        separate thinking_blocks and text_content fields.

        Fix: Store and restore the ENTIRE content array as-is.

        See: https://github.com/anthropics/claude-code/issues/XXX
        """
        import json

        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")

        # Simulate EXACT content from Claude API response
        original_content = [{
            "type": "thinking",
            "thinking": "Let me analyze this problem step by step...",
            "signature": "sig_abc123"
        }, {
            "type": "text",
            "text": "Based on my analysis, here is the answer."
        }]

        thinking_json = json.dumps(original_content)
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="Based on my analysis, here is the answer.",
            role=MessageRole.ASSISTANT,
            thinking_blocks=thinking_json,
        )

        result = formatter.format_message(msg)

        # CRITICAL: Content must be EXACTLY the same as original
        # No reconstruction, no modification
        assert result.content == original_content

    def test_regression_redacted_thinking_preserved(self):
        """REGRESSION TEST: redacted_thinking blocks must be preserved.

        Claude API can return redacted_thinking blocks when thinking content
        is filtered. These MUST be preserved exactly or API returns error.
        """
        import json

        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")

        # Content with redacted_thinking (as returned by Claude)
        original_content = [{
            "type": "redacted_thinking",
            "data": "encrypted_data_here"
        }, {
            "type": "thinking",
            "thinking": "Visible thinking...",
            "signature": "sig_xyz789"
        }, {
            "type": "text",
            "text": "The final answer."
        }]

        thinking_json = json.dumps(original_content)
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="The final answer.",
            role=MessageRole.ASSISTANT,
            thinking_blocks=thinking_json,
        )

        result = formatter.format_message(msg)

        # CRITICAL: redacted_thinking must be preserved
        assert result.content == original_content
        assert result.content[0]["type"] == "redacted_thinking"

    def test_regression_tool_use_blocks_preserved(self):
        """REGRESSION TEST: tool_use blocks in content must be preserved.

        During tool loops, assistant messages contain tool_use blocks.
        These must be preserved exactly for context reconstruction.
        """
        import json

        from db.models.message import MessageRole

        formatter = ContextFormatter(chat_type="private")

        # Content with tool_use (as captured during tool loop)
        original_content = [{
            "type": "thinking",
            "thinking": "I need to search the web...",
            "signature": "sig_tool123"
        }, {
            "type": "text",
            "text": "Let me search for that."
        }, {
            "type": "tool_use",
            "id": "tool_abc123",
            "name": "web_search",
            "input": {
                "query": "weather today"
            }
        }]

        thinking_json = json.dumps(original_content)
        msg = create_mock_db_message(
            from_user_id=None,
            text_content="Let me search for that.",
            role=MessageRole.ASSISTANT,
            thinking_blocks=thinking_json,
        )

        result = formatter.format_message(msg)

        # CRITICAL: All blocks including tool_use must be preserved
        assert result.content == original_content
        assert len(result.content) == 3
        assert result.content[2]["type"] == "tool_use"
