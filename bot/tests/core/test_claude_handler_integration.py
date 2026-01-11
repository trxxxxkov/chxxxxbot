"""Integration tests for Claude handler.

Tests to prevent regressions in Claude handler's interaction with database
repositories and Claude API client.
"""
# pylint: disable=invalid-name,too-many-locals,too-many-statements
# pylint: disable=unused-argument,import-outside-toplevel

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from telegram.handlers.claude import handle_claude_message


@pytest.mark.asyncio
async def test_claude_handler_uses_correct_chat_type_parameter():
    """Bug fix test: ChatRepository.get_or_create must use chat_type not type.

    Regression test for bug where handler passed 'type' instead of 'chat_type'
    to ChatRepository.get_or_create(), causing TypeError.

    This test ensures the parameter name is correct.
    """
    # Mock message (text-only, no media)
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.from_user.username = "testuser"
    message.from_user.first_name = "Test"
    message.from_user.last_name = "User"
    message.chat = MagicMock()
    message.chat.id = 789012
    message.chat.type = "private"
    message.chat.title = None
    message.message_id = 1
    message.date = MagicMock()
    message.date.timestamp = MagicMock(return_value=1234567890)
    message.text = "Hello"
    message.bot = AsyncMock()
    # Explicitly set media attributes to None (text-only message)
    message.photo = None
    message.document = None
    message.voice = None
    message.audio = None
    message.video = None
    message.video_note = None
    message.caption = None
    message.message_thread_id = None
    message.answer = AsyncMock()

    # Mock session
    session = AsyncMock()

    # Mock message queue manager (Phase 1.4.3+)
    mock_queue_manager = AsyncMock()

    # Mock repositories
    with patch('telegram.handlers.claude.UserRepository') as MockUserRepo, \
         patch('telegram.handlers.claude.ChatRepository') as MockChatRepo, \
         patch('telegram.handlers.claude.ThreadRepository') as MockThreadRepo, \
         patch('telegram.handlers.claude.MessageRepository') as MockMsgRepo, \
         patch('telegram.handlers.claude.UserFileRepository') as MockUserFileRepo, \
         patch('telegram.handlers.claude.claude_provider') as mock_provider, \
         patch('telegram.handlers.claude.message_queue_manager', mock_queue_manager):

        # Setup user repository mock (Phase 1.4.2+: model_id, custom_prompt)
        user_instance = MagicMock()
        user_instance.id = 123456
        user_instance.model_id = 'claude:sonnet'
        user_instance.custom_prompt = None
        MockUserRepo.return_value.get_or_create = AsyncMock(
            return_value=(user_instance, True))
        MockUserRepo.return_value.get_by_id = AsyncMock(
            return_value=user_instance)

        # Setup chat repository mock
        chat_instance = MagicMock()
        chat_instance.id = 789012
        chat_get_or_create = AsyncMock(return_value=(chat_instance, True))
        MockChatRepo.return_value.get_or_create = chat_get_or_create

        # Setup other mocks
        thread_instance = MagicMock()
        thread_instance.id = 1
        thread_instance.files_context = None
        MockThreadRepo.return_value.get_or_create_thread = AsyncMock(
            return_value=(thread_instance, True))
        MockThreadRepo.return_value.get_by_id = AsyncMock(
            return_value=thread_instance)
        MockMsgRepo.return_value.create_message = AsyncMock()
        MockMsgRepo.return_value.add_tokens = AsyncMock()
        MockMsgRepo.return_value.get_thread_messages = AsyncMock(
            return_value=[])

        # Setup user file repository mock (Phase 1.5+)
        MockUserFileRepo.return_value.get_active_files_for_thread = AsyncMock(
            return_value=[])

        # Mock bot message
        bot_message = MagicMock()
        bot_message.message_id = 2
        bot_message.date = MagicMock()
        bot_message.date.timestamp = MagicMock(return_value=1234567891)
        bot_message.edit_text = AsyncMock()
        message.answer = AsyncMock(return_value=bot_message)

        # Setup Claude provider mock
        async def mock_stream(request):
            yield "Hello"
            yield " world"

        mock_provider.stream_message = mock_stream
        mock_provider.get_usage = AsyncMock(
            return_value=MagicMock(input_tokens=10, output_tokens=5))
        mock_provider.get_token_count = AsyncMock(return_value=5)

        # Mock ContextManager
        with patch('telegram.handlers.claude.ContextManager') as MockContextMgr:
            MockContextMgr.return_value.build_context = AsyncMock(
                return_value=[])

            # Call handler
            await handle_claude_message(message, session)

        # CRITICAL CHECK: Verify chat_type parameter was used
        chat_get_or_create.assert_called_once()
        call_kwargs = chat_get_or_create.call_args.kwargs

        # This assertion prevents the bug from reoccurring
        assert 'chat_type' in call_kwargs, \
            "ChatRepository.get_or_create must be called with 'chat_type' parameter"
        assert 'type' not in call_kwargs, \
            "ChatRepository.get_or_create must NOT be called with 'type' parameter"
        assert call_kwargs['chat_type'] == 'private'


@pytest.mark.asyncio
async def test_claude_handler_uses_user_id_not_telegram_id():
    """Bug fix test: User model uses 'id' attribute, not 'telegram_id'.

    Regression test for bug where handler tried to access user.telegram_id
    which doesn't exist (should use user.id).

    This test ensures the correct attribute is used in logging.
    """
    # Mock message (text-only, no media)
    message = MagicMock()
    message.from_user = MagicMock()
    message.from_user.id = 123456
    message.from_user.username = "testuser"
    message.from_user.first_name = "Test"
    message.from_user.last_name = None
    message.chat = MagicMock()
    message.chat.id = 789012
    message.chat.type = "private"
    message.chat.title = None
    message.message_id = 1
    message.date = MagicMock()
    message.date.timestamp = MagicMock(return_value=1234567890)
    message.text = "Test"
    message.bot = AsyncMock()
    # Explicitly set media attributes to None (text-only message)
    message.photo = None
    message.document = None
    message.voice = None
    message.audio = None
    message.video = None
    message.video_note = None
    message.caption = None
    message.message_thread_id = None
    message.answer = AsyncMock()

    # Mock session
    session = AsyncMock()

    # Mock message queue manager (Phase 1.4.3+)
    mock_queue_manager = AsyncMock()

    # Mock repositories
    with patch('telegram.handlers.claude.UserRepository') as MockUserRepo, \
         patch('telegram.handlers.claude.ChatRepository') as MockChatRepo, \
         patch('telegram.handlers.claude.ThreadRepository') as MockThreadRepo, \
         patch('telegram.handlers.claude.MessageRepository') as MockMsgRepo, \
         patch('telegram.handlers.claude.UserFileRepository') as MockUserFileRepo, \
         patch('telegram.handlers.claude.claude_provider') as mock_provider, \
         patch('telegram.handlers.claude.message_queue_manager', mock_queue_manager):

        # Setup user repository mock - user WITHOUT telegram_id attribute
        user_instance = MagicMock(spec=['id', 'model_id', 'custom_prompt'])
        user_instance.id = 123456
        user_instance.model_id = 'claude:sonnet'  # Phase 1.4.2+
        user_instance.custom_prompt = None  # Phase 1.4.2+
        # Explicitly no telegram_id attribute
        if hasattr(user_instance, 'telegram_id'):
            delattr(user_instance, 'telegram_id')

        MockUserRepo.return_value.get_or_create = AsyncMock(
            return_value=(user_instance, True))
        MockUserRepo.return_value.get_by_id = AsyncMock(
            return_value=user_instance)

        # Setup other mocks
        chat_instance = MagicMock()
        chat_instance.id = 789012
        MockChatRepo.return_value.get_or_create = AsyncMock(
            return_value=(chat_instance, True))

        thread_instance = MagicMock()
        thread_instance.id = 1
        thread_instance.files_context = None  # Phase 1.4.2+
        MockThreadRepo.return_value.get_or_create_thread = AsyncMock(
            return_value=(thread_instance, True))
        MockThreadRepo.return_value.get_by_id = AsyncMock(
            return_value=thread_instance)
        MockMsgRepo.return_value.create_message = AsyncMock()
        MockMsgRepo.return_value.add_tokens = AsyncMock()
        MockMsgRepo.return_value.get_thread_messages = AsyncMock(
            return_value=[])

        # Setup user file repository mock (Phase 1.5+)
        MockUserFileRepo.return_value.get_active_files_for_thread = AsyncMock(
            return_value=[])

        # Mock bot message
        bot_message = MagicMock()
        bot_message.message_id = 2
        bot_message.date = MagicMock()
        bot_message.date.timestamp = MagicMock(return_value=1234567891)
        bot_message.edit_text = AsyncMock()
        message.answer = AsyncMock(return_value=bot_message)

        # Setup Claude provider mock
        async def mock_stream(request):
            yield "Response"

        mock_provider.stream_message = mock_stream
        mock_provider.get_usage = AsyncMock(
            return_value=MagicMock(input_tokens=10, output_tokens=5))
        mock_provider.get_token_count = AsyncMock(return_value=5)

        # Mock ContextManager
        with patch('telegram.handlers.claude.ContextManager') as MockContextMgr:
            MockContextMgr.return_value.build_context = AsyncMock(
                return_value=[])

            # Call handler - should NOT raise AttributeError
            try:
                await handle_claude_message(message, session)
            except AttributeError as e:
                if 'telegram_id' in str(e):
                    pytest.fail(
                        f"Handler tried to access user.telegram_id: {e}\n"
                        "Handler must use user.id, not user.telegram_id")
                raise

            # If we got here without AttributeError, test passed
            assert True, "Handler correctly uses user.id instead of user.telegram_id"
