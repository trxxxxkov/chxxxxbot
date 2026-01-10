"""Test tool-generated files delivery to forum topics.

This module tests that generated files (images, code outputs) are correctly
sent to the forum topic where the request originated, not to the main chat.

Bug fix regression test: Files were sent to main chat when user requested
from forum topic, because message_thread_id was not passed to send_photo/send_document.

NO __init__.py - use direct import:
    from tests.telegram.handlers.test_claude_tools_forum import (
        test_generated_file_sent_to_forum_topic
    )
"""

from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from aiogram import types
from anthropic.types import ContentBlock
from anthropic.types import TextBlock
from anthropic.types import ToolUseBlock
from anthropic.types import Usage
import pytest


def create_mock_message(content_blocks: list[Any], stop_reason: str) -> Any:
    """Create mock anthropic.types.Message for testing.

    Args:
        content_blocks: List of content blocks (TextBlock, ToolUseBlock).
        stop_reason: Stop reason string.

    Returns:
        Mock Message object.
    """
    mock_msg = MagicMock()
    mock_msg.content = content_blocks
    mock_msg.stop_reason = stop_reason
    mock_msg.usage = Usage(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    # Add type attribute to content blocks
    for block in content_blocks:
        if not hasattr(block, 'type'):
            if hasattr(block, 'text'):
                block.type = 'text'
            elif hasattr(block, 'name'):
                block.type = 'tool_use'
    return mock_msg


@pytest.mark.asyncio
async def test_generated_file_sent_to_forum_topic():
    """Test that generated files are sent to forum topic, not main chat.

    Regression test for bug where files were sent to main chat when user
    requested from forum topic.

    Bug: _handle_with_tools sent files without message_thread_id parameter.
    Fix: Added telegram_thread_id parameter to _handle_with_tools and
         passed it to send_photo/send_document.

    Test scenario:
    1. User sends message from forum topic (message_thread_id=12345)
    2. Claude calls generate_image tool
    3. Tool returns _file_contents
    4. Handler uploads to Files API, saves to DB
    5. Handler sends photo to Telegram WITH message_thread_id=12345
    """
    from core.models import LLMRequest
    from core.models import Message
    from telegram.handlers.claude import _handle_with_tools

    # Mock dependencies
    mock_session = MagicMock()
    mock_user_file_repo = AsyncMock()
    mock_user_file_repo.create = AsyncMock()

    # Mock Telegram message from forum topic
    mock_first_message = MagicMock(spec=types.Message)
    mock_first_message.message_id = 123
    mock_first_message.chat = MagicMock()
    mock_first_message.chat.id = 789
    mock_first_message.answer = AsyncMock()
    mock_first_message.edit_text = AsyncMock()

    # Mock bot for sending files
    mock_bot = AsyncMock()
    mock_bot.send_photo = AsyncMock()
    mock_bot.send_document = AsyncMock()
    mock_first_message.bot = mock_bot

    # Mock ClaudeProvider
    with patch('telegram.handlers.claude.claude_provider') as mock_provider:
        # First call: Claude uses generate_image tool
        tool_use_block = MagicMock(spec=ToolUseBlock)
        tool_use_block.type = "tool_use"
        tool_use_block.id = "toolu_123"
        tool_use_block.name = "generate_image"
        tool_use_block.input = {
            "prompt": "A cute cat",
            "aspect_ratio": "1:1",
            "image_size": "2K"
        }

        text_block = MagicMock(spec=TextBlock)
        text_block.type = "text"
        text_block.text = "I'll generate an image for you."

        mock_response_1 = create_mock_message(
            content_blocks=[text_block, tool_use_block], stop_reason="tool_use")

        # Second call: Claude sends final response after tool execution
        final_text_block = MagicMock(spec=TextBlock)
        final_text_block.type = "text"
        final_text_block.text = "Here's your image!"

        mock_response_2 = create_mock_message(content_blocks=[final_text_block],
                                              stop_reason="end_turn")

        mock_provider.get_message = AsyncMock(
            side_effect=[mock_response_1, mock_response_2])
        mock_provider.get_thinking.return_value = None
        mock_provider.get_stop_reason.return_value = "end_turn"

        # Mock execute_tool to return file contents
        with patch(
                'telegram.handlers.claude.execute_tool') as mock_execute_tool:
            mock_execute_tool.return_value = {
                "success":
                    "true",
                "cost_usd":
                    "0.134",
                "parameters_used": {
                    "aspect_ratio": "1:1",
                    "image_size": "2K"
                },
                "_file_contents": [{
                    "filename": "generated_test.png",
                    "content": b"fake_image_bytes",
                    "mime_type": "image/png",
                }],
            }

            # Mock Files API upload (patching at the source)
            with patch(
                    'core.claude.files_api.upload_to_files_api') as mock_upload:
                mock_upload.return_value = "file_test123"

                # Create request
                request = LLMRequest(
                    messages=[
                        Message(role="user", content="Generate a cat image")
                    ],
                    system_prompt="You are a helpful assistant.",
                    model="claude:sonnet",
                    max_tokens=4096,
                    temperature=1.0,
                    tools=[{
                        "name": "generate_image"
                    }])

                # CRITICAL: Pass telegram_thread_id (forum topic ID)
                telegram_thread_id = 12345
                chat_id = 789
                user_id = 456

                # Execute
                result = await _handle_with_tools(
                    request=request,
                    first_message=mock_first_message,
                    thread_id=999,
                    session=mock_session,
                    user_file_repo=mock_user_file_repo,
                    chat_id=chat_id,
                    user_id=user_id,
                    telegram_thread_id=telegram_thread_id)

                # Verify result
                assert "Here's your image!" in result

                # CRITICAL: Verify send_photo was called with message_thread_id
                mock_bot.send_photo.assert_called_once()
                call_kwargs = mock_bot.send_photo.call_args[1]
                assert call_kwargs["chat_id"] == chat_id
                assert call_kwargs["message_thread_id"] == telegram_thread_id, (
                    "BUG: File sent without message_thread_id! "
                    "It will go to main chat instead of forum topic.")

                # Verify photo content
                assert call_kwargs["photo"].filename == "generated_test.png"

                # Verify file was saved to DB
                mock_user_file_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_generated_file_sent_to_main_chat_when_no_topic():
    """Test that files work correctly in main chat (no forum topic).

    When telegram_thread_id is None, files should still be sent correctly
    to the main chat (Telegram API accepts None for message_thread_id).
    """
    from core.models import LLMRequest
    from core.models import Message
    from telegram.handlers.claude import _handle_with_tools

    # Mock dependencies (same as above test)
    mock_session = MagicMock()
    mock_user_file_repo = AsyncMock()
    mock_user_file_repo.create = AsyncMock()

    mock_first_message = MagicMock(spec=types.Message)
    mock_first_message.message_id = 123
    mock_first_message.chat = MagicMock()
    mock_first_message.chat.id = 789
    mock_first_message.answer = AsyncMock()
    mock_first_message.edit_text = AsyncMock()

    mock_bot = AsyncMock()
    mock_bot.send_photo = AsyncMock()
    mock_first_message.bot = mock_bot

    with patch('telegram.handlers.claude.claude_provider') as mock_provider:
        # First call: Claude uses generate_image tool
        tool_use_block = MagicMock(spec=ToolUseBlock)
        tool_use_block.type = "tool_use"
        tool_use_block.id = "toolu_123"
        tool_use_block.name = "generate_image"
        tool_use_block.input = {"prompt": "A cute dog", "aspect_ratio": "1:1"}

        mock_response_1 = create_mock_message(content_blocks=[tool_use_block],
                                              stop_reason="tool_use")

        # Second call: Claude sends final response after tool execution
        final_text_block = MagicMock(spec=TextBlock)
        final_text_block.type = "text"
        final_text_block.text = "Done!"

        mock_response_2 = create_mock_message(content_blocks=[final_text_block],
                                              stop_reason="end_turn")

        mock_provider.get_message = AsyncMock(
            side_effect=[mock_response_1, mock_response_2])
        mock_provider.get_thinking.return_value = None
        mock_provider.get_stop_reason.return_value = "end_turn"

        with patch(
                'telegram.handlers.claude.execute_tool') as mock_execute_tool:
            mock_execute_tool.return_value = {
                "success":
                    "true",
                "_file_contents": [{
                    "filename": "dog.png",
                    "content": b"dog_bytes",
                    "mime_type": "image/png",
                }],
            }

            with patch(
                    'core.claude.files_api.upload_to_files_api') as mock_upload:
                mock_upload.return_value = "file_dog123"

                request = LLMRequest(
                    messages=[
                        Message(role="user", content="Generate a dog image")
                    ],
                    system_prompt="You are a helpful assistant.",
                    model="claude:sonnet",
                    max_tokens=4096,
                    temperature=1.0,
                    tools=[{
                        "name": "generate_image"
                    }])

                # CRITICAL: telegram_thread_id is None (main chat, no forum)
                telegram_thread_id = None
                chat_id = 789
                user_id = 456

                result = await _handle_with_tools(
                    request=request,
                    first_message=mock_first_message,
                    thread_id=999,
                    session=mock_session,
                    user_file_repo=mock_user_file_repo,
                    chat_id=chat_id,
                    user_id=user_id,
                    telegram_thread_id=telegram_thread_id)

                assert "Done!" in result

                # Verify send_photo called with message_thread_id=None
                mock_bot.send_photo.assert_called_once()
                call_kwargs = mock_bot.send_photo.call_args[1]
                assert call_kwargs["chat_id"] == chat_id
                assert call_kwargs["message_thread_id"] is None
