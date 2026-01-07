"""Tests for MessageRepository.

This module contains comprehensive tests for MessageRepository operations,
including JSONB attachments, conversation history, and token tracking.

NO __init__.py - use direct import:
    pytest tests/db/repositories/test_message_repository.py
"""

from db.models.message import MessageRole
from db.repositories.message_repository import MessageRepository
import pytest


@pytest.mark.asyncio
async def test_get_message(test_session, sample_message):
    """Test retrieving message by composite primary key.

    Args:
        test_session: Async session fixture.
        sample_message: Sample message fixture.
    """
    repo = MessageRepository(test_session)

    message = await repo.get_message(
        sample_message.chat_id,
        sample_message.message_id,
    )

    assert message is not None
    assert message.chat_id == sample_message.chat_id
    assert message.message_id == sample_message.message_id
    assert message.text_content == sample_message.text_content


@pytest.mark.asyncio
async def test_create_message_text_only(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message without attachments.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=123,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567890,
        role=MessageRole.USER,
        text_content='Hello, bot!',
    )

    assert message.text_content == 'Hello, bot!'
    assert message.role == MessageRole.USER
    assert message.attachments == []
    assert message.has_photos is False
    assert message.has_documents is False
    assert message.has_voice is False
    assert message.has_video is False
    assert message.attachment_count == 0


@pytest.mark.asyncio
async def test_create_message_with_photo(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with photo attachment.

    Verifies JSONB storage and denormalized flags.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    attachments = [{
        'type': 'photo',
        'file_id': 'AgACAgIAAxkBAAI...',
        'file_unique_id': 'AQADw...',
        'width': 1280,
        'height': 720,
        'file_size': 102400,
    }]

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=124,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567891,
        role=MessageRole.USER,
        text_content='Check this photo',
        attachments=attachments,
    )

    # Verify denormalized flags
    assert message.has_photos is True
    assert message.has_documents is False
    assert message.has_voice is False
    assert message.has_video is False
    assert message.attachment_count == 1

    # Verify JSONB content
    assert len(message.attachments) == 1
    assert message.attachments[0]['type'] == 'photo'
    assert message.attachments[0]['width'] == 1280
    assert message.attachments[0]['height'] == 720


@pytest.mark.asyncio
async def test_create_message_with_document(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with document attachment.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    attachments = [{
        'type': 'document',
        'file_id': 'BQACAgIAAxkBAAI...',
        'file_unique_id': 'AgADw...',
        'file_name': 'report.pdf',
        'mime_type': 'application/pdf',
        'file_size': 524288,
    }]

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=125,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567892,
        role=MessageRole.USER,
        caption='Here is the report',
        attachments=attachments,
    )

    assert message.has_documents is True
    assert message.has_photos is False
    assert message.attachment_count == 1
    assert message.caption == 'Here is the report'
    assert message.attachments[0]['file_name'] == 'report.pdf'


@pytest.mark.asyncio
async def test_create_message_with_voice(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with voice message.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    attachments = [{
        'type': 'voice',
        'file_id': 'AwACAgIAAxkBAAI...',
        'file_unique_id': 'AgADw...',
        'duration': 15,
        'file_size': 8192,
    }]

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=126,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567893,
        role=MessageRole.USER,
        attachments=attachments,
    )

    assert message.has_voice is True
    assert message.has_photos is False
    assert message.has_documents is False
    assert message.has_video is False
    assert message.attachment_count == 1


@pytest.mark.asyncio
async def test_create_message_with_video(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with video attachment.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    attachments = [{
        'type': 'video',
        'file_id': 'BAACAgIAAxkBAAI...',
        'file_unique_id': 'AgADw...',
        'width': 1920,
        'height': 1080,
        'duration': 60,
        'file_size': 2097152,
    }]

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=127,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567894,
        role=MessageRole.USER,
        attachments=attachments,
    )

    assert message.has_video is True
    assert message.has_photos is False
    assert message.attachment_count == 1
    assert message.attachments[0]['duration'] == 60


@pytest.mark.asyncio
async def test_create_message_multiple_attachments(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with multiple attachments.

    Verifies correct flag calculation for mixed attachment types.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    attachments = [
        {
            'type': 'photo',
            'file_id': 'AgACAgIAAxkBAAI1...',
            'width': 800,
            'height': 600,
        },
        {
            'type': 'photo',
            'file_id': 'AgACAgIAAxkBAAI2...',
            'width': 1024,
            'height': 768,
        },
        {
            'type': 'document',
            'file_id': 'BQACAgIAAxkBAAI3...',
            'file_name': 'data.csv',
        },
    ]

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=128,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567895,
        role=MessageRole.USER,
        attachments=attachments,
    )

    assert message.has_photos is True
    assert message.has_documents is True
    assert message.has_voice is False
    assert message.has_video is False
    assert message.attachment_count == 3
    assert len(message.attachments) == 3


@pytest.mark.asyncio
async def test_attachment_flags_calculation(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test that attachment flags are automatically calculated correctly.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    # Create messages with different attachment types
    msg_photo = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=201,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567900,
        role=MessageRole.USER,
        attachments=[{
            'type': 'photo',
            'file_id': 'photo1'
        }],
    )

    msg_doc = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=202,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567901,
        role=MessageRole.USER,
        attachments=[{
            'type': 'document',
            'file_id': 'doc1'
        }],
    )

    msg_voice = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=203,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567902,
        role=MessageRole.USER,
        attachments=[{
            'type': 'voice',
            'file_id': 'voice1'
        }],
    )

    msg_video = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=204,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234567903,
        role=MessageRole.USER,
        attachments=[{
            'type': 'video',
            'file_id': 'video1'
        }],
    )

    # Verify each flag is set correctly
    assert msg_photo.has_photos is True
    assert msg_doc.has_documents is True
    assert msg_voice.has_voice is True
    assert msg_video.has_video is True


@pytest.mark.asyncio
async def test_attachment_count(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test that attachment_count is calculated correctly.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    # No attachments
    msg0 = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=301,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568000,
        role=MessageRole.USER,
        text_content='No attachments',
    )

    # One attachment
    msg1 = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=302,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568001,
        role=MessageRole.USER,
        attachments=[{
            'type': 'photo',
            'file_id': 'p1'
        }],
    )

    # Three attachments
    msg3 = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=303,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568002,
        role=MessageRole.USER,
        attachments=[
            {
                'type': 'photo',
                'file_id': 'p1'
            },
            {
                'type': 'photo',
                'file_id': 'p2'
            },
            {
                'type': 'photo',
                'file_id': 'p3'
            },
        ],
    )

    assert msg0.attachment_count == 0
    assert msg1.attachment_count == 1
    assert msg3.attachment_count == 3


@pytest.mark.asyncio
async def test_update_message(
    test_session,
    sample_message,
):
    """Test updating message text and edit date.

    Args:
        test_session: Async session fixture.
        sample_message: Sample message fixture.
    """
    repo = MessageRepository(test_session)

    await repo.update_message(
        chat_id=sample_message.chat_id,
        message_id=sample_message.message_id,
        text_content='Updated text',
        edit_date=1234567999,
    )

    updated = await repo.get_message(
        sample_message.chat_id,
        sample_message.message_id,
    )

    assert updated.text_content == 'Updated text'
    assert updated.edit_date == 1234567999


@pytest.mark.asyncio
async def test_get_thread_messages(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test retrieving conversation history ordered by date ASC.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    # Create messages in non-chronological order
    msg2 = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=402,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568002,
        role=MessageRole.USER,
        text_content='Message 2',
    )

    msg1 = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=401,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568001,
        role=MessageRole.USER,
        text_content='Message 1',
    )

    msg3 = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=403,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568003,
        role=MessageRole.ASSISTANT,
        text_content='Message 3',
    )

    # Get messages - should be ordered by date ASC
    messages = await repo.get_thread_messages(sample_thread.id)

    assert len(messages) == 3
    assert messages[0].text_content == 'Message 1'
    assert messages[1].text_content == 'Message 2'
    assert messages[2].text_content == 'Message 3'
    assert messages[0].date < messages[1].date < messages[2].date


@pytest.mark.asyncio
async def test_get_thread_messages_limit(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test pagination in get_thread_messages.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    # Create 5 messages
    for i in range(5):
        await repo.create_message(
            chat_id=sample_chat.id,
            message_id=500 + i,
            thread_id=sample_thread.id,
            from_user_id=sample_user.id,
            date=1234568100 + i,
            role=MessageRole.USER,
            text_content=f'Message {i}',
        )

    # Test limit
    messages_limit = await repo.get_thread_messages(sample_thread.id, limit=3)
    assert len(messages_limit) == 3

    # Test offset
    messages_offset = await repo.get_thread_messages(sample_thread.id,
                                                     limit=3,
                                                     offset=2)
    assert len(messages_offset) == 3
    assert messages_offset[0].text_content == 'Message 2'

    # Test no limit (all messages)
    messages_all = await repo.get_thread_messages(sample_thread.id)
    assert len(messages_all) == 5


@pytest.mark.asyncio
async def test_get_recent_messages(
    test_session,
    sample_chat,
    sample_thread,
    sample_user,
):
    """Test retrieving recent messages ordered by date DESC.

    Args:
        test_session: Async session fixture.
        sample_chat: Sample chat fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
    """
    repo = MessageRepository(test_session)

    # Create messages
    for i in range(3):
        await repo.create_message(
            chat_id=sample_chat.id,
            message_id=600 + i,
            thread_id=sample_thread.id,
            from_user_id=sample_user.id,
            date=1234568200 + i,
            role=MessageRole.USER,
            text_content=f'Message {i}',
        )

    # Get recent - should be ordered DESC (newest first)
    messages = await repo.get_recent_messages(sample_chat.id, limit=10)

    assert len(messages) == 3
    assert messages[0].text_content == 'Message 2'  # Newest
    assert messages[1].text_content == 'Message 1'
    assert messages[2].text_content == 'Message 0'  # Oldest
    assert messages[0].date > messages[1].date > messages[2].date


@pytest.mark.asyncio
async def test_add_tokens(
    test_session,
    sample_message,
):
    """Test tracking LLM token usage.

    Args:
        test_session: Async session fixture.
        sample_message: Sample message fixture.
    """
    repo = MessageRepository(test_session)

    await repo.add_tokens(
        chat_id=sample_message.chat_id,
        message_id=sample_message.message_id,
        input_tokens=150,
        output_tokens=250,
    )

    updated = await repo.get_message(
        sample_message.chat_id,
        sample_message.message_id,
    )

    assert updated.input_tokens == 150
    assert updated.output_tokens == 250


@pytest.mark.asyncio
async def test_get_messages_with_attachments(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test filtering messages by attachment type.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    # Create messages with different attachment types
    await repo.create_message(
        chat_id=sample_chat.id,
        message_id=701,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568301,
        role=MessageRole.USER,
        text_content='Text only',
    )

    await repo.create_message(
        chat_id=sample_chat.id,
        message_id=702,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568302,
        role=MessageRole.USER,
        attachments=[{
            'type': 'photo',
            'file_id': 'p1'
        }],
    )

    await repo.create_message(
        chat_id=sample_chat.id,
        message_id=703,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568303,
        role=MessageRole.USER,
        attachments=[{
            'type': 'document',
            'file_id': 'd1'
        }],
    )

    await repo.create_message(
        chat_id=sample_chat.id,
        message_id=704,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568304,
        role=MessageRole.USER,
        attachments=[{
            'type': 'photo',
            'file_id': 'p2'
        }],
    )

    # Get all messages with attachments
    all_attachments = await repo.get_messages_with_attachments(sample_thread.id)
    assert len(all_attachments) == 3  # Excludes text-only

    # Get only photos
    photos = await repo.get_messages_with_attachments(sample_thread.id,
                                                      attachment_type='photo')
    assert len(photos) == 2
    assert all(msg.has_photos for msg in photos)

    # Get only documents
    documents = await repo.get_messages_with_attachments(
        sample_thread.id, attachment_type='document')
    assert len(documents) == 1
    assert documents[0].has_documents is True


@pytest.mark.asyncio
async def test_media_group(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test messages with media_group_id (photo albums).

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    # Create messages in same media group
    media_group_id = 'media_group_123'

    msg1 = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=801,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568401,
        role=MessageRole.USER,
        media_group_id=media_group_id,
        attachments=[{
            'type': 'photo',
            'file_id': 'p1'
        }],
    )

    msg2 = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=802,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234568402,
        role=MessageRole.USER,
        media_group_id=media_group_id,
        attachments=[{
            'type': 'photo',
            'file_id': 'p2'
        }],
    )

    assert msg1.media_group_id == media_group_id
    assert msg2.media_group_id == media_group_id
    assert msg1.media_group_id == msg2.media_group_id
