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
    # Use MagicMock for session to avoid sync methods (like add()) returning
    # coroutines. Explicitly set async methods.
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.refresh = AsyncMock()
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

    # Mock sent photo message with photo sizes
    mock_photo_size = MagicMock()
    mock_photo_size.file_id = "AgACAgIAAxkBAAI_test_photo"
    mock_photo_size.file_size = 12345

    mock_sent_msg = MagicMock()
    mock_sent_msg.photo = [mock_photo_size]  # List of photo sizes

    mock_bot.send_photo = AsyncMock(return_value=mock_sent_msg)
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

            # IMPORTANT: Patch where the name is looked up, not where it's
            # defined. The handler imports it as:
            # from core.claude.files_api import upload_to_files_api
            with patch('telegram.handlers.claude.upload_to_files_api'
                      ) as mock_upload:
                mock_upload.return_value = "file_test123"

                # Mock BalanceService to avoid session issues
                with patch('services.balance_service.BalanceService'
                          ) as mock_balance_service:
                    mock_balance_service.return_value.charge_usage = AsyncMock()

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

                    # CRITICAL: Verify send_photo was called with
                    # message_thread_id
                    mock_bot.send_photo.assert_called_once()
                    call_kwargs = mock_bot.send_photo.call_args[1]
                    assert call_kwargs["chat_id"] == chat_id
                    assert call_kwargs["message_thread_id"] == (
                        telegram_thread_id), (
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

            # IMPORTANT: Patch where the name is looked up, not where it's
            # defined. The handler imports it as:
            # from core.claude.files_api import upload_to_files_api
            with patch('telegram.handlers.claude.upload_to_files_api'
                      ) as mock_upload:
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


@pytest.mark.asyncio
async def test_file_delivery_with_empty_error_key():
    """Test that files are delivered when error key is present but empty.

    Regression test for bug where execute_python always returns {"error": ""}
    even on success, and the handler incorrectly treated this as an error.

    Bug: `is_error = "error" in result` was always True because error key exists.
    Fix: `is_error = bool(result.get("error"))` - empty string is falsy.

    Test scenario:
    1. execute_python returns successful result with {"error": "", ...}
    2. Handler should NOT treat this as an error
    3. Handler should deliver generated files
    """
    from core.models import LLMRequest
    from core.models import Message
    from telegram.handlers.claude import _handle_with_tools

    # Mock dependencies
    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_user_file_repo = AsyncMock()
    mock_user_file_repo.create = AsyncMock()

    mock_first_message = MagicMock(spec=types.Message)
    mock_first_message.message_id = 123
    mock_first_message.chat = MagicMock()
    mock_first_message.chat.id = 789
    mock_first_message.answer = AsyncMock()

    mock_bot = AsyncMock()

    # Mock sent photo message with photo sizes
    mock_photo_size = MagicMock()
    mock_photo_size.file_id = "AgACAgIAAxkBAAI_test_photo"
    mock_photo_size.file_size = 12345
    mock_photo_size.file_unique_id = "test_unique"

    mock_sent_msg = MagicMock()
    mock_sent_msg.photo = [mock_photo_size]

    mock_bot.send_photo = AsyncMock(return_value=mock_sent_msg)
    mock_first_message.bot = mock_bot

    with patch('telegram.handlers.claude.claude_provider') as mock_provider:
        # First call: Claude uses execute_python tool
        tool_use_block = MagicMock(spec=ToolUseBlock)
        tool_use_block.type = "tool_use"
        tool_use_block.id = "toolu_exec_123"
        tool_use_block.name = "execute_python"
        tool_use_block.input = {"code": "import matplotlib; ..."}

        mock_response_1 = create_mock_message(content_blocks=[tool_use_block],
                                              stop_reason="tool_use")

        # Second call: Claude sends final response
        final_text_block = MagicMock(spec=TextBlock)
        final_text_block.type = "text"
        final_text_block.text = "Here's your chart!"

        mock_response_2 = create_mock_message(content_blocks=[final_text_block],
                                              stop_reason="end_turn")

        mock_provider.get_message = AsyncMock(
            side_effect=[mock_response_1, mock_response_2])
        mock_provider.get_thinking.return_value = None
        mock_provider.get_stop_reason.return_value = "end_turn"

        with patch(
                'telegram.handlers.claude.execute_tool') as mock_execute_tool:
            # CRITICAL: execute_python returns error="" (empty string, not None)
            # This is the actual format returned by execute_python
            mock_execute_tool.return_value = {
                "stdout":
                    "Plot saved",
                "stderr":
                    "",
                "results":
                    "[]",
                "error":
                    "",  # Empty string, NOT absence of key!
                "success":
                    "true",
                "generated_files":
                    '[{"filename": "chart.png"}]',
                "cost_usd":
                    "0.0001",
                "_file_contents": [{
                    "filename": "chart.png",
                    "content": b"png_bytes_here",
                    "mime_type": "image/png",
                }],
            }

            # IMPORTANT: Patch where the name is looked up, not where it's
            # defined. The handler imports it as:
            # from core.claude.files_api import upload_to_files_api
            with patch('telegram.handlers.claude.upload_to_files_api'
                      ) as mock_upload:
                mock_upload.return_value = "file_chart123"

                with patch('services.balance_service.BalanceService'
                          ) as mock_balance_service:
                    mock_balance_service.return_value.charge_usage = AsyncMock()

                    request = LLMRequest(
                        messages=[
                            Message(role="user", content="Create a chart")
                        ],
                        system_prompt="You are a helpful assistant.",
                        model="claude:sonnet",
                        max_tokens=4096,
                        temperature=1.0,
                        tools=[{
                            "name": "execute_python"
                        }])

                    result = await _handle_with_tools(
                        request=request,
                        first_message=mock_first_message,
                        thread_id=999,
                        session=mock_session,
                        user_file_repo=mock_user_file_repo,
                        chat_id=789,
                        user_id=456,
                        telegram_thread_id=None)

                    # Verify response
                    assert "chart" in result.lower() or "Here" in result

                    # CRITICAL: Verify send_photo WAS called
                    # Bug was: send_photo was NOT called because handler
                    # treated error="" as an error
                    assert mock_bot.send_photo.called, (
                        "BUG REGRESSION: File not delivered! "
                        "Handler incorrectly treated error='' as an error.")

                    # Verify upload to Files API was called
                    mock_upload.assert_called_once()

                    # Verify file was saved to DB
                    mock_user_file_repo.create.assert_called_once()
