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
    # Mock message
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

    # Mock session
    session = AsyncMock()

    # Mock repositories
    with patch('telegram.handlers.claude.UserRepository') as MockUserRepo, \
         patch('telegram.handlers.claude.ChatRepository') as MockChatRepo, \
         patch('telegram.handlers.claude.ThreadRepository') as MockThreadRepo, \
         patch('telegram.handlers.claude.MessageRepository') as MockMsgRepo, \
         patch('telegram.handlers.claude.claude_provider') as mock_provider:

        # Setup user repository mock
        user_instance = MagicMock()
        user_instance.id = 123456
        MockUserRepo.return_value.get_or_create = AsyncMock(
            return_value=(user_instance, True))

        # Setup chat repository mock
        chat_instance = MagicMock()
        chat_instance.id = 789012
        chat_get_or_create = AsyncMock(return_value=(chat_instance, True))
        MockChatRepo.return_value.get_or_create = chat_get_or_create

        # Setup other mocks
        thread_instance = MagicMock()
        thread_instance.id = 1
        MockThreadRepo.return_value.get_or_create_thread = AsyncMock(
            return_value=(thread_instance, True))
        MockMsgRepo.return_value.create_message = AsyncMock()
        MockMsgRepo.return_value.add_tokens = AsyncMock()
        MockMsgRepo.return_value.get_thread_messages = AsyncMock(
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
    # Mock message
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

    # Mock session
    session = AsyncMock()

    # Mock repositories
    with patch('telegram.handlers.claude.UserRepository') as MockUserRepo, \
         patch('telegram.handlers.claude.ChatRepository') as MockChatRepo, \
         patch('telegram.handlers.claude.ThreadRepository') as MockThreadRepo, \
         patch('telegram.handlers.claude.MessageRepository') as MockMsgRepo, \
         patch('telegram.handlers.claude.claude_provider') as mock_provider:

        # Setup user repository mock - user WITHOUT telegram_id attribute
        user_instance = MagicMock(spec=['id'])  # Only 'id' attribute
        user_instance.id = 123456
        # Explicitly no telegram_id attribute
        if hasattr(user_instance, 'telegram_id'):
            delattr(user_instance, 'telegram_id')

        MockUserRepo.return_value.get_or_create = AsyncMock(
            return_value=(user_instance, True))

        # Setup other mocks
        chat_instance = MagicMock()
        chat_instance.id = 789012
        MockChatRepo.return_value.get_or_create = AsyncMock(
            return_value=(chat_instance, True))

        thread_instance = MagicMock()
        thread_instance.id = 1
        MockThreadRepo.return_value.get_or_create_thread = AsyncMock(
            return_value=(thread_instance, True))
        MockMsgRepo.return_value.create_message = AsyncMock()
        MockMsgRepo.return_value.add_tokens = AsyncMock()
        MockMsgRepo.return_value.get_thread_messages = AsyncMock(
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


@pytest.mark.asyncio
async def test_claude_handler_passes_role_to_create_message():
    """Bug fix test: MessageRepository.create_message requires role parameter.

    Regression test for bug where handler called create_message() without
    the required 'role' parameter, causing TypeError.

    This test ensures role is passed for both user and assistant messages.
    """
    # Mock message
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
    message.text = "Test message"
    message.bot = AsyncMock()

    # Mock bot message for response
    bot_message = MagicMock()
    bot_message.message_id = 2
    bot_message.date = MagicMock()
    bot_message.date.timestamp = MagicMock(return_value=1234567891)
    bot_message.edit_text = AsyncMock()
    message.answer = AsyncMock(return_value=bot_message)

    # Mock session
    session = AsyncMock()

    # Mock repositories
    with patch('telegram.handlers.claude.UserRepository') as MockUserRepo, \
         patch('telegram.handlers.claude.ChatRepository') as MockChatRepo, \
         patch('telegram.handlers.claude.ThreadRepository') as MockThreadRepo, \
         patch('telegram.handlers.claude.MessageRepository') as MockMsgRepo, \
         patch('telegram.handlers.claude.claude_provider') as mock_provider, \
         patch('telegram.handlers.claude.ContextManager') as MockContextMgr:

        # Setup mocks
        user_instance = MagicMock()
        user_instance.id = 123456
        MockUserRepo.return_value.get_or_create = AsyncMock(
            return_value=(user_instance, False))

        chat_instance = MagicMock()
        chat_instance.id = 789012
        MockChatRepo.return_value.get_or_create = AsyncMock(
            return_value=(chat_instance, False))

        thread_instance = MagicMock()
        thread_instance.id = 1
        MockThreadRepo.return_value.get_or_create_thread = AsyncMock(
            return_value=(thread_instance, False))

        create_message_mock = AsyncMock()
        add_tokens_mock = AsyncMock()
        MockMsgRepo.return_value.create_message = create_message_mock
        MockMsgRepo.return_value.add_tokens = add_tokens_mock
        MockMsgRepo.return_value.get_thread_messages = AsyncMock(
            return_value=[])

        # Setup Claude provider mock
        async def mock_stream(request):
            yield "Response text"

        mock_provider.stream_message = mock_stream
        mock_provider.get_usage = AsyncMock(
            return_value=MagicMock(input_tokens=10, output_tokens=5))

        # Setup context manager mock
        MockContextMgr.return_value.build_context = AsyncMock(return_value=[])

        # Call handler
        await handle_claude_message(message, session)

        # CRITICAL CHECK: Verify role parameter in both create_message calls
        assert create_message_mock.call_count == 2, \
            "create_message should be called twice (user + assistant)"

        # First call: user message
        first_call_kwargs = create_message_mock.call_args_list[0].kwargs
        assert 'role' in first_call_kwargs, \
            "create_message for user message must have 'role' parameter"

        # Import MessageRole to check value
        from db.models.message import MessageRole
        assert first_call_kwargs['role'] == MessageRole.USER, \
            "User message must have role=MessageRole.USER"

        # Second call: assistant message
        second_call_kwargs = create_message_mock.call_args_list[1].kwargs
        assert 'role' in second_call_kwargs, \
            "create_message for assistant message must have 'role' parameter"
        assert second_call_kwargs['role'] == MessageRole.ASSISTANT, \
            "Assistant message must have role=MessageRole.ASSISTANT"


@pytest.mark.asyncio
async def test_claude_handler_creates_thread_before_saving_message():
    """Bug fix test: Thread must be created before saving user message.

    Regression test for bug where handler tried to save message with
    thread_id before creating the thread, causing missing thread_id.

    This test ensures correct execution order.
    """
    # Mock message
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

    # Mock bot message
    bot_message = MagicMock()
    bot_message.message_id = 2
    bot_message.date = MagicMock()
    bot_message.date.timestamp = MagicMock(return_value=1234567891)
    bot_message.edit_text = AsyncMock()
    message.answer = AsyncMock(return_value=bot_message)

    # Mock session
    session = AsyncMock()

    # Track call order
    call_order = []

    # Mock repositories
    with patch('telegram.handlers.claude.UserRepository') as MockUserRepo, \
         patch('telegram.handlers.claude.ChatRepository') as MockChatRepo, \
         patch('telegram.handlers.claude.ThreadRepository') as MockThreadRepo, \
         patch('telegram.handlers.claude.MessageRepository') as MockMsgRepo, \
         patch('telegram.handlers.claude.claude_provider') as mock_provider, \
         patch('telegram.handlers.claude.ContextManager') as MockContextMgr:

        # Setup mocks that track call order
        user_instance = MagicMock()
        user_instance.id = 123456
        MockUserRepo.return_value.get_or_create = AsyncMock(
            return_value=(user_instance, False))

        chat_instance = MagicMock()
        chat_instance.id = 789012
        MockChatRepo.return_value.get_or_create = AsyncMock(
            return_value=(chat_instance, False))

        thread_instance = MagicMock()
        thread_instance.id = 1

        async def track_thread_creation(*args, **kwargs):
            call_order.append('thread_created')
            return (thread_instance, True)

        async def track_message_creation(*args, **kwargs):
            call_order.append('message_created')
            return MagicMock()

        MockThreadRepo.return_value.get_or_create_thread = AsyncMock(
            side_effect=track_thread_creation)
        MockMsgRepo.return_value.create_message = AsyncMock(
            side_effect=track_message_creation)
        MockMsgRepo.return_value.add_tokens = AsyncMock()
        MockMsgRepo.return_value.get_thread_messages = AsyncMock(
            return_value=[])

        # Setup Claude provider mock
        async def mock_stream(request):
            yield "Response"

        mock_provider.stream_message = mock_stream
        mock_provider.get_usage = AsyncMock(
            return_value=MagicMock(input_tokens=10, output_tokens=5))

        # Setup context manager mock
        MockContextMgr.return_value.build_context = AsyncMock(return_value=[])

        # Call handler
        await handle_claude_message(message, session)

        # CRITICAL CHECK: Thread must be created BEFORE first message
        assert len(call_order) >= 2, "Both thread and messages must be created"
        assert call_order[0] == 'thread_created', \
            "Thread must be created BEFORE saving user message"
        assert call_order[1] == 'message_created', \
            "User message must be saved AFTER thread is created"
