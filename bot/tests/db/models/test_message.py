"""Tests for Message model.

Comprehensive tests for db/models/message.py:
- MessageRole enum
- Message model creation and constraints
- Composite primary key (chat_id, message_id)
- Foreign key relationships
- JSONB fields (attachments, quote_data, forward_origin)
- Denormalized attachment flags
- Token tracking fields
- Indexes
"""

import random
import time
from unittest.mock import MagicMock

from db.models.chat import Chat
from db.models.message import Message
from db.models.message import MessageRole
from db.models.thread import Thread
from db.models.user import User
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def pg_sample_chat(pg_session):
    """Create sample chat for message tests with unique ID."""
    # Generate unique chat ID to avoid conflicts between test runs
    unique_id = random.randint(100000000, 999999999)
    chat = Chat(
        id=unique_id,
        type="private",
        first_name="Test",
        last_name="User",
    )
    pg_session.add(chat)
    await pg_session.flush()
    return chat


@pytest.fixture
async def pg_sample_thread(pg_session, pg_sample_user, pg_sample_chat):
    """Create sample thread for message tests."""
    thread = Thread(
        chat_id=pg_sample_chat.id,
        user_id=pg_sample_user.id,
        thread_id=None,
    )
    pg_session.add(thread)
    await pg_session.flush()
    return thread


# ============================================================================
# Tests for MessageRole enum
# ============================================================================


class TestMessageRole:
    """Tests for MessageRole enum."""

    def test_role_values(self):
        """Should have correct string values."""
        assert MessageRole.USER.value == "user"
        assert MessageRole.ASSISTANT.value == "assistant"
        assert MessageRole.SYSTEM.value == "system"

    def test_role_is_string_enum(self):
        """Should be usable as string."""
        assert str(MessageRole.USER) == "MessageRole.USER"
        assert MessageRole.USER == "user"

    def test_all_roles_defined(self):
        """Should have exactly 3 roles."""
        roles = list(MessageRole)
        assert len(roles) == 3


# ============================================================================
# Tests for Message model creation
# ============================================================================


@pytest.mark.asyncio
class TestMessageCreation:
    """Tests for Message model creation."""

    async def test_create_user_message(
        self,
        pg_session,
        pg_sample_user,
        pg_sample_chat,
        pg_sample_thread,
    ):
        """Should create user message with required fields."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=1,
            thread_id=pg_sample_thread.id,
            from_user_id=pg_sample_user.id,
            date=now,
            role=MessageRole.USER,
            text_content="Hello, world!",
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()
        await pg_session.refresh(message)

        assert message.chat_id == pg_sample_chat.id
        assert message.message_id == 1
        assert message.role == MessageRole.USER
        assert message.text_content == "Hello, world!"

    async def test_create_assistant_message(
        self,
        pg_session,
        pg_sample_user,
        pg_sample_chat,
        pg_sample_thread,
    ):
        """Should create assistant message with token tracking."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=2,
            thread_id=pg_sample_thread.id,
            from_user_id=None,  # Assistant messages have no user
            date=now,
            role=MessageRole.ASSISTANT,
            text_content="Hello! How can I help?",
            input_tokens=100,
            output_tokens=50,
            model_id="claude-sonnet-4-5",
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.role == MessageRole.ASSISTANT
        assert message.input_tokens == 100
        assert message.output_tokens == 50
        assert message.model_id == "claude-sonnet-4-5"

    async def test_create_message_with_caption(
        self,
        pg_session,
        pg_sample_chat,
        pg_sample_thread,
        pg_sample_user,
    ):
        """Should support caption for media messages."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=3,
            thread_id=pg_sample_thread.id,
            from_user_id=pg_sample_user.id,
            date=now,
            role=MessageRole.USER,
            text_content=None,
            caption="Photo caption",
            has_photos=True,
            attachment_count=1,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.text_content is None
        assert message.caption == "Photo caption"
        assert message.has_photos is True

    async def test_create_message_minimal_fields(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should create message with only required fields."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=4,
            date=now,
            role=MessageRole.USER,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        # Check defaults
        assert message.thread_id is None
        assert message.from_user_id is None
        assert message.text_content is None
        assert message.has_photos is False
        assert message.has_documents is False
        assert message.has_voice is False
        assert message.has_video is False
        assert message.attachment_count == 0
        assert message.edit_count == 0


# ============================================================================
# Tests for composite primary key
# ============================================================================


@pytest.mark.asyncio
class TestCompositePrimaryKey:
    """Tests for composite primary key (chat_id, message_id)."""

    async def test_same_message_id_different_chats(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should allow same message_id in different chats."""
        # Create second chat
        chat2 = Chat(id=987654321, type="private", first_name="Other")
        pg_session.add(chat2)
        await pg_session.flush()

        now = int(time.time())

        # Same message_id=1 in both chats should work
        msg1 = Message(
            chat_id=pg_sample_chat.id,
            message_id=1,
            date=now,
            role=MessageRole.USER,
            text_content="Chat 1",
            created_at=now,
        )
        msg2 = Message(
            chat_id=chat2.id,
            message_id=1,  # Same message_id
            date=now,
            role=MessageRole.USER,
            text_content="Chat 2",
            created_at=now,
        )

        pg_session.add_all([msg1, msg2])
        await pg_session.flush()

        assert msg1.text_content == "Chat 1"
        assert msg2.text_content == "Chat 2"

    async def test_duplicate_message_in_same_chat_fails(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should reject duplicate (chat_id, message_id) pair."""
        now = int(time.time())

        msg1 = Message(
            chat_id=pg_sample_chat.id,
            message_id=100,
            date=now,
            role=MessageRole.USER,
            created_at=now,
        )
        pg_session.add(msg1)
        await pg_session.flush()

        # Try to create duplicate
        msg2 = Message(
            chat_id=pg_sample_chat.id,
            message_id=100,  # Duplicate!
            date=now,
            role=MessageRole.USER,
            created_at=now,
        )
        pg_session.add(msg2)

        with pytest.raises(IntegrityError):
            await pg_session.flush()

        await pg_session.rollback()


# ============================================================================
# Tests for JSONB fields
# ============================================================================


@pytest.mark.asyncio
class TestJSONBFields:
    """Tests for JSONB fields (attachments, quote_data, forward_origin)."""

    async def test_attachments_jsonb(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should store attachments as JSONB array."""
        now = int(time.time())
        attachments = [
            {
                "type": "photo",
                "file_id": "AgACAgIAAxkBAAI",
                "width": 1920,
                "height": 1080,
            },
            {
                "type": "photo",
                "file_id": "AgACAgIAAxkBAAJ",
                "width": 640,
                "height": 480,
            },
        ]

        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=10,
            date=now,
            role=MessageRole.USER,
            attachments=attachments,
            has_photos=True,
            attachment_count=2,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()
        await pg_session.refresh(message)

        assert len(message.attachments) == 2
        assert message.attachments[0]["type"] == "photo"
        assert message.attachments[0]["width"] == 1920

    async def test_quote_data_jsonb(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should store quote_data as JSONB."""
        now = int(time.time())
        quote_data = {
            "text": "This is the quoted text",
            "position": 0,
            "is_manual": True,
        }

        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=11,
            date=now,
            role=MessageRole.USER,
            text_content="My reply",
            reply_to_message_id=5,
            quote_data=quote_data,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()
        await pg_session.refresh(message)

        assert message.quote_data["text"] == "This is the quoted text"
        assert message.quote_data["is_manual"] is True

    async def test_forward_origin_jsonb(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should store forward_origin as JSONB."""
        now = int(time.time())
        forward_origin = {
            "type": "user",
            "display": "@original_user",
            "date": now - 3600,
        }

        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=12,
            date=now,
            role=MessageRole.USER,
            text_content="Forwarded message",
            forward_origin=forward_origin,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()
        await pg_session.refresh(message)

        assert message.forward_origin["type"] == "user"
        assert message.forward_origin["display"] == "@original_user"


# ============================================================================
# Tests for denormalized attachment flags
# ============================================================================


@pytest.mark.asyncio
class TestAttachmentFlags:
    """Tests for denormalized attachment flags."""

    async def test_has_photos_flag(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should set has_photos flag correctly."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=20,
            date=now,
            role=MessageRole.USER,
            has_photos=True,
            has_documents=False,
            has_voice=False,
            has_video=False,
            attachment_count=3,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.has_photos is True
        assert message.has_documents is False

    async def test_has_documents_flag(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should set has_documents flag correctly."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=21,
            date=now,
            role=MessageRole.USER,
            has_photos=False,
            has_documents=True,
            attachment_count=1,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.has_documents is True

    async def test_has_voice_flag(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should set has_voice flag correctly."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=22,
            date=now,
            role=MessageRole.USER,
            has_voice=True,
            attachment_count=1,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.has_voice is True

    async def test_has_video_flag(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should set has_video flag correctly."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=23,
            date=now,
            role=MessageRole.USER,
            has_video=True,
            attachment_count=1,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.has_video is True

    async def test_multiple_attachment_types(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should support multiple attachment types."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=24,
            date=now,
            role=MessageRole.USER,
            has_photos=True,
            has_documents=True,
            has_voice=False,
            has_video=True,
            attachment_count=5,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.has_photos is True
        assert message.has_documents is True
        assert message.has_voice is False
        assert message.has_video is True
        assert message.attachment_count == 5


# ============================================================================
# Tests for token tracking
# ============================================================================


@pytest.mark.asyncio
class TestTokenTracking:
    """Tests for LLM token tracking fields."""

    async def test_basic_token_tracking(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should track input and output tokens."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=30,
            date=now,
            role=MessageRole.ASSISTANT,
            text_content="Response",
            input_tokens=500,
            output_tokens=150,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.input_tokens == 500
        assert message.output_tokens == 150

    async def test_cache_token_tracking(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should track cache creation and read tokens."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=31,
            date=now,
            role=MessageRole.ASSISTANT,
            text_content="Response",
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=200,
            cache_read_input_tokens=300,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.cache_creation_input_tokens == 200
        assert message.cache_read_input_tokens == 300

    async def test_thinking_token_tracking(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should track extended thinking tokens."""
        now = int(time.time())
        thinking_content = "Let me think about this...\n\n" * 100

        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=32,
            date=now,
            role=MessageRole.ASSISTANT,
            text_content="The answer is 42.",
            thinking_tokens=5000,
            thinking_blocks=thinking_content,
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.thinking_tokens == 5000
        assert "Let me think" in message.thinking_blocks


# ============================================================================
# Tests for reply fields
# ============================================================================


@pytest.mark.asyncio
class TestReplyFields:
    """Tests for reply-related fields."""

    async def test_reply_to_message_id(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should store reply_to_message_id."""
        now = int(time.time())

        # Create original message
        original = Message(
            chat_id=pg_sample_chat.id,
            message_id=40,
            date=now,
            role=MessageRole.USER,
            text_content="Original message",
            created_at=now,
        )
        pg_session.add(original)
        await pg_session.flush()

        # Create reply
        reply = Message(
            chat_id=pg_sample_chat.id,
            message_id=41,
            date=now,
            role=MessageRole.USER,
            text_content="Reply message",
            reply_to_message_id=40,
            reply_snippet="Original message",
            reply_sender_display="@user123",
            created_at=now,
        )
        pg_session.add(reply)
        await pg_session.flush()

        assert reply.reply_to_message_id == 40
        assert reply.reply_snippet == "Original message"
        assert reply.reply_sender_display == "@user123"


# ============================================================================
# Tests for edit tracking
# ============================================================================


@pytest.mark.asyncio
class TestEditTracking:
    """Tests for message edit tracking."""

    async def test_edit_count_default(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should default edit_count to 0."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=50,
            date=now,
            role=MessageRole.USER,
            text_content="Original",
            created_at=now,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.edit_count == 0
        assert message.edit_date is None
        assert message.original_content is None

    async def test_edit_tracking_fields(
        self,
        pg_session,
        pg_sample_chat,
    ):
        """Should track edit history."""
        now = int(time.time())
        message = Message(
            chat_id=pg_sample_chat.id,
            message_id=51,
            date=now - 100,
            edit_date=now,
            role=MessageRole.USER,
            text_content="Edited content",
            original_content="Original content",
            edit_count=2,
            created_at=now - 100,
        )

        pg_session.add(message)
        await pg_session.flush()

        assert message.edit_count == 2
        assert message.edit_date == now
        assert message.original_content == "Original content"
        assert message.text_content == "Edited content"


# ============================================================================
# Tests for __repr__
# ============================================================================


class TestMessageRepr:
    """Tests for Message.__repr__()."""

    def test_repr_format(self):
        """Should return readable representation."""
        message = Message(
            chat_id=123,
            message_id=456,
            date=int(time.time()),
            role=MessageRole.USER,
            created_at=int(time.time()),
        )

        repr_str = repr(message)

        assert "chat_id=123" in repr_str
        assert "message_id=456" in repr_str
        assert "role=user" in repr_str

    def test_repr_different_roles(self):
        """Should show correct role in repr."""
        now = int(time.time())

        user_msg = Message(chat_id=1,
                           message_id=1,
                           date=now,
                           role=MessageRole.USER,
                           created_at=now)
        assistant_msg = Message(chat_id=1,
                                message_id=2,
                                date=now,
                                role=MessageRole.ASSISTANT,
                                created_at=now)
        system_msg = Message(chat_id=1,
                             message_id=3,
                             date=now,
                             role=MessageRole.SYSTEM,
                             created_at=now)

        assert "role=user" in repr(user_msg)
        assert "role=assistant" in repr(assistant_msg)
        assert "role=system" in repr(system_msg)
