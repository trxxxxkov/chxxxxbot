"""Message repository for database operations.

This module provides the MessageRepository for working with Message model,
including conversation history management and attachment handling.

NO __init__.py - use direct import:
    from db.repositories.message_repository import MessageRepository
"""

from typing import Optional

from db.models.message import Message
from db.models.message import MessageRole
from db.repositories.base import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class MessageRepository(BaseRepository[Message]):
    """Repository for Message model operations.

    Provides database operations specific to Message model,
    including conversation history, attachment handling, and token tracking.

    Attributes:
        session: AsyncSession inherited from BaseRepository.
        model: Message model class inherited from BaseRepository.
    """

    def __init__(self, session: AsyncSession):
        """Initialize with Message model.

        Args:
            session: AsyncSession for database operations.
        """
        super().__init__(session, Message)

    async def get_message(
        self,
        chat_id: int,
        message_id: int,
    ) -> Optional[Message]:
        """Get message by composite primary key.

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.

        Returns:
            Message instance or None if not found.
        """
        return await self.session.get(Message, (chat_id, message_id))

    # pylint: disable=too-many-locals
    async def create_message(
        self,
        chat_id: int,
        message_id: int,
        thread_id: Optional[int],
        from_user_id: Optional[int],
        date: int,
        role: MessageRole,
        text_content: Optional[str] = None,
        caption: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        media_group_id: Optional[str] = None,
        attachments: Optional[list[dict]] = None,
        edit_date: Optional[int] = None,
    ) -> Message:
        """Create new message with attachments.

        Automatically sets denormalized flags (has_photos, has_documents, etc.)
        based on attachments list.

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.
            thread_id: Internal thread ID (from threads table).
            from_user_id: Telegram user ID of sender.
            date: Unix timestamp when sent.
            role: Message role (USER/ASSISTANT/SYSTEM).
            text_content: Text content. Defaults to None.
            caption: Media caption. Defaults to None.
            reply_to_message_id: Replied message ID. Defaults to None.
            media_group_id: Media group ID. Defaults to None.
            attachments: List of attachment dicts. Defaults to None.
            edit_date: Unix timestamp of last edit. Defaults to None.

        Returns:
            Created Message instance.

        Note:
            Attachments format:
            [
                {
                    "type": "photo",
                    "file_id": "AgACAgIAAxkBAAI...",
                    "file_unique_id": "AQADw...",
                    "width": 1280,
                    "height": 720,
                    "file_size": 102400
                },
                ...
            ]
        """
        attachments = attachments or []

        # Calculate denormalized flags
        has_photos = any(att.get("type") == "photo" for att in attachments)
        has_documents = any(
            att.get("type") == "document" for att in attachments)
        has_voice = any(att.get("type") == "voice" for att in attachments)
        has_video = any(att.get("type") == "video" for att in attachments)
        attachment_count = len(attachments)

        message = Message(
            chat_id=chat_id,
            message_id=message_id,
            thread_id=thread_id,
            from_user_id=from_user_id,
            date=date,
            edit_date=edit_date,
            role=role,
            text_content=text_content,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
            media_group_id=media_group_id,
            has_photos=has_photos,
            has_documents=has_documents,
            has_voice=has_voice,
            has_video=has_video,
            attachment_count=attachment_count,
            attachments=attachments,
            created_at=date,  # Use message date as record creation timestamp
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def update_message(
        self,
        chat_id: int,
        message_id: int,
        text_content: Optional[str] = None,
        caption: Optional[str] = None,
        edit_date: Optional[int] = None,
    ) -> None:
        """Update message text/caption (for edited messages).

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.
            text_content: New text content. Defaults to None.
            caption: New caption. Defaults to None.
            edit_date: Unix timestamp of edit. Defaults to None.

        Raises:
            ValueError: If message not found.
        """
        message = await self.get_message(chat_id, message_id)
        if not message:
            raise ValueError(f"Message ({chat_id}, {message_id}) not found")

        if text_content is not None:
            message.text_content = text_content
        if caption is not None:
            message.caption = caption
        if edit_date is not None:
            message.edit_date = edit_date

        await self.session.flush()

    async def get_thread_messages(
        self,
        thread_id: int,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[Message]:
        """Get conversation history for LLM context.

        Returns messages ordered by date ASC (oldest first) for proper
        LLM context construction.

        Args:
            thread_id: Internal thread ID.
            limit: Max number of messages. None = all. Defaults to None.
            offset: Number of messages to skip. Defaults to 0.

        Returns:
            List of Message instances ordered by date ASC.
        """
        stmt = (select(Message).where(Message.thread_id == thread_id).order_by(
            Message.date.asc()))

        if limit is not None:
            stmt = stmt.limit(limit)
        if offset > 0:
            stmt = stmt.offset(offset)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent_messages(
        self,
        chat_id: int,
        limit: int = 100,
    ) -> list[Message]:
        """Get recent messages in chat.

        Returns messages ordered by date DESC (newest first).

        Args:
            chat_id: Telegram chat ID.
            limit: Max number of messages. Defaults to 100.

        Returns:
            List of Message instances ordered by date DESC.
        """
        stmt = (select(Message).where(Message.chat_id == chat_id).order_by(
            Message.date.desc()).limit(limit))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_tokens(
        self,
        chat_id: int,
        message_id: int,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
    ) -> None:
        """Track LLM token usage for billing.

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.
            input_tokens: Number of input tokens. Defaults to None.
            output_tokens: Number of output tokens. Defaults to None.

        Raises:
            ValueError: If message not found.
        """
        message = await self.get_message(chat_id, message_id)
        if not message:
            raise ValueError(f"Message ({chat_id}, {message_id}) not found")

        if input_tokens is not None:
            message.input_tokens = input_tokens
        if output_tokens is not None:
            message.output_tokens = output_tokens

        await self.session.flush()

    async def get_messages_with_attachments(
        self,
        thread_id: int,
        attachment_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[Message]:
        """Get messages with attachments from thread.

        Args:
            thread_id: Internal thread ID.
            attachment_type: Filter by type (photo/document/voice/video).
                None = all attachments. Defaults to None.
            limit: Max number of messages. Defaults to 100.

        Returns:
            List of Message instances with attachments.
        """
        stmt = (select(Message).where(
            Message.thread_id == thread_id,
            Message.attachment_count > 0,
        ).order_by(Message.date.desc()).limit(limit))

        # Add type-specific filter if requested
        if attachment_type == "photo":
            stmt = stmt.where(Message.has_photos.is_(True))
        elif attachment_type == "document":
            stmt = stmt.where(Message.has_documents.is_(True))
        elif attachment_type == "voice":
            stmt = stmt.where(Message.has_voice.is_(True))
        elif attachment_type == "video":
            stmt = stmt.where(Message.has_video.is_(True))

        result = await self.session.execute(stmt)
        return list(result.scalars().all())
