"""Manual test script for PostgreSQL validation.

This script tests the live PostgreSQL database after deployment.
It creates test data, verifies all CRUD operations, and cleans up.

Usage:
    # From inside bot container
    python tests/manual_test_script.py

    # Or via docker
    docker compose exec bot python tests/manual_test_script.py

NO __init__.py - use direct import.
"""

import asyncio
from datetime import datetime
from datetime import timezone
import sys

from config import get_database_url
from db.engine import dispose_db
from db.engine import get_session
from db.engine import init_db
from db.models.message import MessageRole
from db.repositories.chat_repository import ChatRepository
from db.repositories.message_repository import MessageRepository
from db.repositories.thread_repository import ThreadRepository
from db.repositories.user_repository import UserRepository


class Colors:
    """ANSI color codes for terminal output."""

    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_success(message: str) -> None:
    """Print success message in green.

    Args:
        message: Success message to print.
    """
    print(f'{Colors.GREEN}✓{Colors.RESET} {message}')


def print_error(message: str) -> None:
    """Print error message in red.

    Args:
        message: Error message to print.
    """
    print(f'{Colors.RED}✗{Colors.RESET} {message}')


def print_info(message: str) -> None:
    """Print info message in blue.

    Args:
        message: Info message to print.
    """
    print(f'{Colors.BLUE}ℹ{Colors.RESET} {message}')


def print_section(title: str) -> None:
    """Print section header.

    Args:
        title: Section title.
    """
    print(f'\n{Colors.BOLD}{Colors.BLUE}=== {title} ==={Colors.RESET}')


async def test_user_operations() -> bool:
    """Test UserRepository operations.

    Returns:
        True if all tests passed, False otherwise.
    """
    print_section('Testing UserRepository')

    try:
        async with get_session() as session:
            repo = UserRepository(session)

            # Test 1: Create new user
            user, was_created = await repo.get_or_create(
                telegram_id=999000001,
                first_name='Manual',
                last_name='Test',
                username='manual_test_user',
                language_code='en',
                is_premium=False,
            )
            assert was_created is True
            assert user.id == 999000001
            print_success('Created new user')

            # Test 2: Get existing user
            user2, was_created = await repo.get_or_create(
                telegram_id=999000001,
                first_name='Manual',
                username='manual_test_user',
            )
            assert was_created is False
            assert user2.id == user.id
            print_success('Retrieved existing user')

            # Test 3: Update profile
            user3, _ = await repo.get_or_create(
                telegram_id=999000001,
                first_name='Updated',
                username='updated_user',
                is_premium=True,
            )
            assert user3.first_name == 'Updated'
            assert user3.is_premium is True
            print_success('Updated user profile')

            # Test 4: Count users
            count = await repo.get_users_count()
            assert count > 0
            print_success(f'User count: {count}')

            await session.commit()
            return True

    except Exception as e:
        print_error(f'UserRepository tests failed: {e}')
        return False


async def test_chat_operations() -> bool:
    """Test ChatRepository operations.

    Returns:
        True if all tests passed, False otherwise.
    """
    print_section('Testing ChatRepository')

    try:
        async with get_session() as session:
            repo = ChatRepository(session)

            # Test all chat types
            chat_types = [
                ('private', 999000001, 'Manual', 'Test'),
                ('group', 999000002, None, None),
                ('supergroup', 999000003, None, None),
                ('channel', 999000004, None, None),
            ]

            for chat_type, chat_id, first_name, last_name in chat_types:
                chat, was_created = await repo.get_or_create(
                    telegram_id=chat_id,
                    chat_type=chat_type,
                    title=f'Test {chat_type}'
                    if chat_type != 'private' else None,
                    first_name=first_name,
                    last_name=last_name,
                )
                assert was_created is True
                assert chat.type == chat_type
                print_success(f'Created {chat_type} chat')

            # Test forum supergroup
            forum, was_created = await repo.get_or_create(
                telegram_id=999000005,
                chat_type='supergroup',
                title='Forum Test',
                is_forum=True,
            )
            assert forum.is_forum is True
            print_success('Created forum supergroup')

            # Test get by username
            chat_with_username, _ = await repo.get_or_create(
                telegram_id=999000006,
                chat_type='supergroup',
                title='Public Group',
                username='public_test_group',
            )
            found = await repo.get_by_username('public_test_group')
            assert found is not None
            assert found.id == chat_with_username.id
            print_success('Found chat by username')

            await session.commit()
            return True

    except Exception as e:
        print_error(f'ChatRepository tests failed: {e}')
        return False


async def test_thread_operations() -> bool:
    """Test ThreadRepository operations.

    Returns:
        True if all tests passed, False otherwise.
    """
    print_section('Testing ThreadRepository')

    try:
        async with get_session() as session:
            repo = ThreadRepository(session)

            # Test main chat thread
            thread1, was_created = await repo.get_or_create_thread(
                chat_id=999000001,
                user_id=999000001,
                thread_id=None,  # Main chat
                model_name='claude-3-5-sonnet-20241022',
            )
            assert was_created is True
            assert thread1.thread_id is None
            print_success('Created main chat thread')

            # Test forum topic thread
            thread2, was_created = await repo.get_or_create_thread(
                chat_id=999000005,  # Forum supergroup
                user_id=999000001,
                thread_id=12345,
                title='Test Topic',
                model_name='claude-3-5-sonnet-20241022',
            )
            assert was_created is True
            assert thread2.thread_id == 12345
            print_success('Created forum topic thread')

            # Test unique constraint
            thread3, was_created = await repo.get_or_create_thread(
                chat_id=999000001,
                user_id=999000001,
                thread_id=None,  # Same as thread1
            )
            assert was_created is False
            assert thread3.id == thread1.id
            print_success('Verified unique constraint')

            # Test update model
            await repo.update_thread_model(thread1.id, 'openai')
            updated = await repo.get_by_id(thread1.id)
            assert updated.model_name == 'openai'
            print_success('Updated thread model')

            # Test get user threads
            user_threads = await repo.get_user_threads(999000001)
            assert len(user_threads) >= 2
            print_success(f'Found {len(user_threads)} user threads')

            await session.commit()
            return True

    except Exception as e:
        print_error(f'ThreadRepository tests failed: {e}')
        return False


async def test_message_operations() -> bool:
    """Test MessageRepository operations.

    Returns:
        True if all tests passed, False otherwise.
    """
    print_section('Testing MessageRepository')

    try:
        async with get_session() as session:
            msg_repo = MessageRepository(session)
            thread_repo = ThreadRepository(session)

            # Get test thread
            thread = await thread_repo.get_active_thread(
                chat_id=999000001,
                user_id=999000001,
                thread_id=None,
            )
            assert thread is not None

            # Test text message
            msg1 = await msg_repo.create_message(
                chat_id=999000001,
                message_id=9001,
                thread_id=thread.id,
                from_user_id=999000001,
                date=int(datetime.now(timezone.utc).timestamp()),
                role=MessageRole.USER,
                text_content='Test message',
            )
            assert msg1.text_content == 'Test message'
            print_success('Created text message')

            # Test message with photo
            msg2 = await msg_repo.create_message(
                chat_id=999000001,
                message_id=9002,
                thread_id=thread.id,
                from_user_id=999000001,
                date=int(datetime.now(timezone.utc).timestamp()) + 1,
                role=MessageRole.USER,
                text_content='Photo message',
                attachments=[{
                    'type': 'photo',
                    'file_id': 'test_photo_id',
                    'width': 1280,
                    'height': 720,
                }],
            )
            assert msg2.has_photos is True
            assert msg2.attachment_count == 1
            print_success('Created message with photo')

            # Test message with document
            msg3 = await msg_repo.create_message(
                chat_id=999000001,
                message_id=9003,
                thread_id=thread.id,
                from_user_id=999000001,
                date=int(datetime.now(timezone.utc).timestamp()) + 2,
                role=MessageRole.USER,
                attachments=[{
                    'type': 'document',
                    'file_id': 'test_doc_id',
                    'file_name': 'test.pdf',
                    'file_size': 1024,
                }],
            )
            assert msg3.has_documents is True
            print_success('Created message with document')

            # Test get thread messages
            history = await msg_repo.get_thread_messages(thread.id)
            assert len(history) >= 3
            print_success(f'Retrieved {len(history)} messages from thread')

            # Test pagination
            limited = await msg_repo.get_thread_messages(thread.id, limit=2)
            assert len(limited) == 2
            print_success('Pagination works correctly')

            # Test message update
            await msg_repo.update_message(
                chat_id=999000001,
                message_id=9001,
                text_content='Updated message',
                edit_date=int(datetime.now(timezone.utc).timestamp()),
            )
            updated = await msg_repo.get_message(999000001, 9001)
            assert updated.text_content == 'Updated message'
            print_success('Updated message')

            # Test token tracking
            await msg_repo.add_tokens(
                chat_id=999000001,
                message_id=9001,
                input_tokens=100,
                output_tokens=50,
            )
            with_tokens = await msg_repo.get_message(999000001, 9001)
            assert with_tokens.input_tokens == 100
            assert with_tokens.output_tokens == 50
            print_success('Added token tracking')

            # Test get messages with attachments
            with_attachments = await msg_repo.get_messages_with_attachments(
                thread.id)
            assert len(with_attachments) >= 2
            print_success(
                f'Found {len(with_attachments)} messages with attachments')

            # Test filter by type
            photos = await msg_repo.get_messages_with_attachments(
                thread.id,
                attachment_type='photo',
            )
            assert len(photos) >= 1
            assert all(msg.has_photos for msg in photos)
            print_success('Filtered messages by attachment type')

            await session.commit()
            return True

    except Exception as e:
        print_error(f'MessageRepository tests failed: {e}')
        return False


async def cleanup_test_data() -> bool:
    """Clean up test data from database.

    Returns:
        True if cleanup succeeded, False otherwise.
    """
    print_section('Cleaning up test data')

    try:
        async with get_session() as session:
            # Delete test messages
            from db.models.message import Message
            from sqlalchemy import delete

            stmt = delete(Message).where(
                Message.chat_id.in_([
                    999000001, 999000002, 999000003, 999000004, 999000005,
                    999000006
                ]))
            result = await session.execute(stmt)
            print_info(f'Deleted {result.rowcount} test messages')

            # Delete test threads
            from db.models.thread import Thread

            stmt = delete(Thread).where(
                Thread.chat_id.in_([
                    999000001, 999000002, 999000003, 999000004, 999000005,
                    999000006
                ]))
            result = await session.execute(stmt)
            print_info(f'Deleted {result.rowcount} test threads')

            # Delete test chats
            from db.models.chat import Chat

            stmt = delete(Chat).where(
                Chat.id.in_([
                    999000001, 999000002, 999000003, 999000004, 999000005,
                    999000006
                ]))
            result = await session.execute(stmt)
            print_info(f'Deleted {result.rowcount} test chats')

            # Delete test users
            from db.models.user import User

            stmt = delete(User).where(User.id == 999000001)
            result = await session.execute(stmt)
            print_info(f'Deleted {result.rowcount} test users')

            await session.commit()
            print_success('Cleanup completed successfully')
            return True

    except Exception as e:
        print_error(f'Cleanup failed: {e}')
        return False


async def main() -> int:
    """Run all manual tests.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    print(f'{Colors.BOLD}Manual PostgreSQL Test Script{Colors.RESET}')
    print_info('This script will test the live PostgreSQL database')
    print_info('Test data will be created and then cleaned up\n')

    # Initialize database
    try:
        database_url = get_database_url()
        init_db(database_url, echo=False)
        print_success('Database connection initialized')
    except Exception as e:
        print_error(f'Failed to initialize database: {e}')
        return 1

    # Run tests
    results = []

    try:
        results.append(('UserRepository', await test_user_operations()))
        results.append(('ChatRepository', await test_chat_operations()))
        results.append(('ThreadRepository', await test_thread_operations()))
        results.append(('MessageRepository', await test_message_operations()))

    except Exception as e:
        print_error(f'Unexpected error during tests: {e}')
        results.append(('Unexpected', False))

    finally:
        # Always try to cleanup
        cleanup_success = await cleanup_test_data()

        # Dispose database
        await dispose_db()
        print_success('Database connection closed')

    # Print summary
    print_section('Test Summary')

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        if result:
            print_success(f'{test_name}: PASSED')
        else:
            print_error(f'{test_name}: FAILED')

    print(
        f'\n{Colors.BOLD}Results: {passed}/{total} tests passed{Colors.RESET}')

    if not cleanup_success:
        print_error('Warning: Cleanup failed, test data may remain in database')

    if passed == total and cleanup_success:
        print(f'\n{Colors.GREEN}{Colors.BOLD}✅ All tests passed!{Colors.RESET}')
        return 0
    else:
        print(f'\n{Colors.RED}{Colors.BOLD}❌ Some tests failed{Colors.RESET}')
        return 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
