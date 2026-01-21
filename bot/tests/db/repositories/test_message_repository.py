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

    # Test limit - should get 3 most recent messages in chronological order
    messages_limit = await repo.get_thread_messages(sample_thread.id, limit=3)
    assert len(messages_limit) == 3
    # Most recent 3 are [2, 3, 4], returned in chronological order
    assert messages_limit[0].text_content == 'Message 2'
    assert messages_limit[1].text_content == 'Message 3'
    assert messages_limit[2].text_content == 'Message 4'

    # Test offset - skips N most recent, then gets limit
    # With offset=2, limit=3: skip 2 most recent (4, 3), get next 3 (2, 1, 0)
    messages_offset = await repo.get_thread_messages(sample_thread.id,
                                                     limit=3,
                                                     offset=2)
    assert len(messages_offset) == 3
    # Returns [0, 1, 2] in chronological order
    assert messages_offset[0].text_content == 'Message 0'
    assert messages_offset[1].text_content == 'Message 1'
    assert messages_offset[2].text_content == 'Message 2'

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


# Context fields tests (Telegram features)


@pytest.mark.asyncio
async def test_create_message_with_sender_display(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with sender display.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=901,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234569001,
        role=MessageRole.USER,
        text_content="Hello from @john_doe",
        sender_display="@john_doe",
    )

    assert message.sender_display == "@john_doe"


@pytest.mark.asyncio
async def test_create_message_with_reply_context(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with reply context.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=902,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234569002,
        role=MessageRole.USER,
        text_content="This is my reply",
        reply_to_message_id=901,
        reply_snippet="Original message here",
        reply_sender_display="@original_user",
    )

    assert message.reply_to_message_id == 901
    assert message.reply_snippet == "Original message here"
    assert message.reply_sender_display == "@original_user"


@pytest.mark.asyncio
async def test_create_message_with_quote_data(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with quote data.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    quote_data = {
        "text": "This is the quoted text",
        "position": 10,
        "is_manual": True,
    }

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=903,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234569003,
        role=MessageRole.USER,
        text_content="My response to the quote",
        quote_data=quote_data,
    )

    assert message.quote_data is not None
    assert message.quote_data["text"] == "This is the quoted text"
    assert message.quote_data["position"] == 10
    assert message.quote_data["is_manual"] is True


@pytest.mark.asyncio
async def test_create_message_with_forward_origin(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with forward origin.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    forward_origin = {
        "type": "channel",
        "display": "@news_channel",
        "date": 1234560000,
        "chat_id": -1001234567890,
        "message_id": 12345,
    }

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=904,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234569004,
        role=MessageRole.USER,
        text_content="Forwarded news",
        forward_origin=forward_origin,
    )

    assert message.forward_origin is not None
    assert message.forward_origin["type"] == "channel"
    assert message.forward_origin["display"] == "@news_channel"
    assert message.forward_origin["chat_id"] == -1001234567890


@pytest.mark.asyncio
async def test_create_message_edit_count_default(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test that new messages have edit_count=0.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=905,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234569005,
        role=MessageRole.USER,
        text_content="New message",
    )

    assert message.edit_count == 0
    assert message.original_content is None


@pytest.mark.asyncio
async def test_update_message_tracks_edit_count(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test that update_message increments edit_count and saves original.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    # Create message
    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=906,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234569006,
        role=MessageRole.USER,
        text_content="Original text",
    )

    # First edit
    await repo.update_message(
        chat_id=sample_chat.id,
        message_id=906,
        text_content="First edit",
        edit_date=1234569106,
    )

    updated = await repo.get_message(sample_chat.id, 906)
    assert updated.edit_count == 1
    assert updated.original_content == "Original text"
    assert updated.text_content == "First edit"

    # Second edit
    await repo.update_message(
        chat_id=sample_chat.id,
        message_id=906,
        text_content="Second edit",
        edit_date=1234569206,
    )

    updated2 = await repo.get_message(sample_chat.id, 906)
    assert updated2.edit_count == 2
    assert updated2.original_content == "Original text"  # Still original
    assert updated2.text_content == "Second edit"


@pytest.mark.asyncio
async def test_update_message_edit_returns_message(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test that update_message_edit returns the updated message.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    # Create message
    await repo.create_message(
        chat_id=sample_chat.id,
        message_id=907,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234569007,
        role=MessageRole.USER,
        text_content="Original",
    )

    # Edit and get returned message
    result = await repo.update_message_edit(
        chat_id=sample_chat.id,
        message_id=907,
        text_content="Edited",
        edit_date=1234569107,
    )

    assert result is not None
    assert result.text_content == "Edited"
    assert result.edit_count == 1
    assert result.original_content == "Original"


@pytest.mark.asyncio
async def test_update_message_edit_not_found(test_session,):
    """Test that update_message_edit returns None for missing message.

    Args:
        test_session: Async session fixture.
    """
    repo = MessageRepository(test_session)

    result = await repo.update_message_edit(
        chat_id=99999,
        message_id=99999,
        text_content="Won't be saved",
        edit_date=1234569999,
    )

    assert result is None


@pytest.mark.asyncio
async def test_create_message_with_all_context_fields(
    test_session,
    sample_thread,
    sample_user,
    sample_chat,
):
    """Test creating message with all context fields.

    Args:
        test_session: Async session fixture.
        sample_thread: Sample thread fixture.
        sample_user: Sample user fixture.
        sample_chat: Sample chat fixture.
    """
    repo = MessageRepository(test_session)

    forward_origin = {
        "type": "user",
        "display": "@forwarded_from",
        "date": 1234560000,
    }

    quote_data = {
        "text": "quoted",
        "position": 0,
        "is_manual": False,
    }

    message = await repo.create_message(
        chat_id=sample_chat.id,
        message_id=908,
        thread_id=sample_thread.id,
        from_user_id=sample_user.id,
        date=1234569008,
        role=MessageRole.USER,
        text_content="Full context message",
        sender_display="@full_user",
        forward_origin=forward_origin,
        reply_to_message_id=100,
        reply_snippet="Reply snippet here",
        reply_sender_display="@reply_target",
        quote_data=quote_data,
    )

    assert message.sender_display == "@full_user"
    assert message.forward_origin["type"] == "user"
    assert message.reply_to_message_id == 100
    assert message.reply_snippet == "Reply snippet here"
    assert message.reply_sender_display == "@reply_target"
    assert message.quote_data["text"] == "quoted"
    assert message.edit_count == 0
