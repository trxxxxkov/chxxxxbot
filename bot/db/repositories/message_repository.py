"""Message repository for database operations.

This module provides the MessageRepository for working with Message model,
including conversation history management and attachment handling.

Phase 3.2: Uses Redis cache for fast message history retrieval.

NO __init__.py - use direct import:
    from db.repositories.message_repository import MessageRepository
"""

from typing import Optional, Sequence

from cache.thread_cache import cache_messages
from cache.thread_cache import get_cached_messages
from cache.thread_cache import invalidate_messages
from db.models.message import Message
from db.models.message import MessageRole
from db.repositories.base import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


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

    # pylint: disable=too-many-locals,too-many-arguments
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
        thinking_blocks: Optional[str] = None,
        # Context fields (Phase 2.x: Telegram features)
        sender_display: Optional[str] = None,
        forward_origin: Optional[dict] = None,
        reply_snippet: Optional[str] = None,
        reply_sender_display: Optional[str] = None,
        quote_data: Optional[dict] = None,
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
            thinking_blocks: Extended thinking content (Phase 1.4.3). Defaults to None.
            sender_display: @username or "First Last" of sender. Defaults to None.
            forward_origin: Forward origin dict. Defaults to None.
            reply_snippet: First 200 chars of replied message. Defaults to None.
            reply_sender_display: Sender display of replied message. Defaults to None.
            quote_data: Quote dict {text, position, is_manual}. Defaults to None.

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
            # Context fields (Phase 2.x: Telegram features)
            reply_snippet=reply_snippet,
            reply_sender_display=reply_sender_display,
            quote_data=quote_data,
            forward_origin=forward_origin,
            sender_display=sender_display,
            edit_count=0,  # New messages have no edits
            original_content=None,  # Set on first edit
            media_group_id=media_group_id,
            has_photos=has_photos,
            has_documents=has_documents,
            has_voice=has_voice,
            has_video=has_video,
            attachment_count=attachment_count,
            attachments=attachments,
            thinking_blocks=thinking_blocks,  # Phase 1.4.3: Extended Thinking
            created_at=date,  # Use message date as record creation timestamp
        )
        self.session.add(message)
        await self.session.flush()

        # Phase 3.2: Invalidate messages cache after new message
        if thread_id:
            await invalidate_messages(thread_id)

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

        Tracks edit count and saves original content on first edit.

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

        # Save original content on first edit
        if message.edit_count == 0 and message.original_content is None:
            message.original_content = message.text_content or message.caption

        # Increment edit count
        message.edit_count = (message.edit_count or 0) + 1

        if text_content is not None:
            message.text_content = text_content
        if caption is not None:
            message.caption = caption
        if edit_date is not None:
            message.edit_date = edit_date

        await self.session.flush()

    async def update_message_edit(
        self,
        chat_id: int,
        message_id: int,
        text_content: Optional[str] = None,
        caption: Optional[str] = None,
        edit_date: Optional[int] = None,
    ) -> Optional[Message]:
        """Update message for an edit event with tracking.

        This method tracks edit history by:
        - Saving original_content on first edit
        - Incrementing edit_count
        - Updating text/caption and edit_date

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.
            text_content: New text content. Defaults to None.
            caption: New caption. Defaults to None.
            edit_date: Unix timestamp of edit. Defaults to None.

        Returns:
            Updated Message instance or None if message not found.
        """
        message = await self.get_message(chat_id, message_id)
        if not message:
            return None

        # Save original content on first edit
        if message.edit_count == 0 and message.original_content is None:
            message.original_content = message.text_content or message.caption

        # Increment edit count
        message.edit_count = (message.edit_count or 0) + 1

        if text_content is not None:
            message.text_content = text_content
        if caption is not None:
            message.caption = caption
        if edit_date is not None:
            message.edit_date = edit_date

        await self.session.flush()
        return message

    async def get_thread_messages(
        self,
        thread_id: int,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[Message]:
        """Get conversation history for LLM context.

        Returns messages ordered by date ASC (oldest first) for proper
        LLM context construction.

        When limit is specified, returns the MOST RECENT messages (not oldest),
        but still in chronological order for proper context.

        Phase 3.2: Uses Redis cache for fast retrieval. Note: Cache only
        used when limit=None and offset=0 (full history).

        Args:
            thread_id: Internal thread ID.
            limit: Max number of RECENT messages. None = all. Defaults to None.
            offset: Number of messages to skip from the end. Defaults to 0.

        Returns:
            List of Message instances ordered by date ASC.
        """
        # Phase 3.2: Check cache for full message history (no limit/offset)
        # Only cache full history to avoid complexity
        if limit is None and offset == 0:
            cached = await get_cached_messages(thread_id)
            if cached:
                # Reconstruct Message objects from cached data
                # Note: These are not attached to session, read-only
                messages = []
                for msg_data in cached:
                    # Create detached Message objects for LLM context
                    # Only essential fields needed for context
                    msg = Message(
                        chat_id=msg_data["chat_id"],
                        message_id=msg_data["message_id"],
                        thread_id=msg_data.get("thread_id"),
                        from_user_id=msg_data.get("from_user_id"),
                        date=msg_data["date"],
                        role=MessageRole(msg_data["role"]),
                        text_content=msg_data.get("text_content"),
                        caption=msg_data.get("caption"),
                        thinking_blocks=msg_data.get("thinking_blocks"),
                        attachments=msg_data.get("attachments", []),
                        has_photos=msg_data.get("has_photos", False),
                        has_documents=msg_data.get("has_documents", False),
                        has_voice=msg_data.get("has_voice", False),
                        has_video=msg_data.get("has_video", False),
                        attachment_count=msg_data.get("attachment_count", 0),
                        reply_to_message_id=msg_data.get("reply_to_message_id"),
                        reply_snippet=msg_data.get("reply_snippet"),
                        reply_sender_display=msg_data.get(
                            "reply_sender_display"),
                        sender_display=msg_data.get("sender_display"),
                        forward_origin=msg_data.get("forward_origin"),
                        quote_data=msg_data.get("quote_data"),
                        edit_count=msg_data.get("edit_count", 0),
                        created_at=msg_data["date"],
                    )
                    messages.append(msg)
                return messages

        # Cache miss or paginated query - query database
        if limit is not None:
            # Get most recent N messages, but return in chronological order
            # Subquery: get IDs of most recent messages
            subq = (select(Message.chat_id, Message.message_id).where(
                Message.thread_id == thread_id).order_by(
                    Message.date.desc()).limit(limit))
            if offset > 0:
                subq = subq.offset(offset)
            subq = subq.subquery()

            # Main query: get those messages in chronological order
            stmt = (select(Message).where(
                Message.chat_id == subq.c.chat_id,
                Message.message_id == subq.c.message_id,
            ).order_by(Message.date.asc()))
        else:
            # No limit - get all messages in chronological order
            stmt = (select(Message).where(
                Message.thread_id == thread_id).order_by(Message.date.asc()))
            if offset > 0:
                stmt = stmt.offset(offset)

        result = await self.session.execute(stmt)
        messages = list(result.scalars().all())

        # Cache full history for future requests
        if limit is None and offset == 0 and messages:
            # Serialize messages for cache
            messages_data = []
            for msg in messages:
                msg_dict = {
                    "chat_id": msg.chat_id,
                    "message_id": msg.message_id,
                    "thread_id": msg.thread_id,
                    "from_user_id": msg.from_user_id,
                    "date": msg.date,
                    "role": msg.role.value,
                    "text_content": msg.text_content,
                    "caption": msg.caption,
                    "thinking_blocks": msg.thinking_blocks,
                    "attachments": msg.attachments,
                    "has_photos": msg.has_photos,
                    "has_documents": msg.has_documents,
                    "has_voice": msg.has_voice,
                    "has_video": msg.has_video,
                    "attachment_count": msg.attachment_count,
                    "reply_to_message_id": msg.reply_to_message_id,
                    "reply_snippet": msg.reply_snippet,
                    "reply_sender_display": msg.reply_sender_display,
                    "sender_display": msg.sender_display,
                    "forward_origin": msg.forward_origin,
                    "quote_data": msg.quote_data,
                    "edit_count": msg.edit_count,
                }
                messages_data.append(msg_dict)
            await cache_messages(thread_id, messages_data)

        return messages

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
        cache_creation_tokens: Optional[int] = None,
        cache_read_tokens: Optional[int] = None,
        thinking_tokens: Optional[int] = None,
    ) -> None:
        """Track LLM token usage for billing.

        Phase 1.4.2: Includes cache tokens (creation, read).
        Phase 1.4.3: Includes thinking tokens.

        Args:
            chat_id: Telegram chat ID.
            message_id: Telegram message ID.
            input_tokens: Number of input tokens. Defaults to None.
            output_tokens: Number of output tokens. Defaults to None.
            cache_creation_tokens: Cache creation tokens (Phase 1.4.2). Defaults to None.
            cache_read_tokens: Cache read tokens (Phase 1.4.2). Defaults to None.
            thinking_tokens: Extended thinking tokens (Phase 1.4.3). Defaults to None.

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
        if cache_creation_tokens is not None:
            message.cache_creation_input_tokens = cache_creation_tokens
        if cache_read_tokens is not None:
            message.cache_read_input_tokens = cache_read_tokens
        if thinking_tokens is not None:
            message.thinking_tokens = thinking_tokens

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

    async def create_messages_batch(
        self,
        messages_data: Sequence[dict],
    ) -> list[Message]:
        """Create multiple messages in a single batch operation.

        Optimized for bulk inserts - uses single flush instead of per-message flush.
        Ideal for importing conversation history or bulk operations.

        Args:
            messages_data: List of dicts with message parameters.
                Required keys: chat_id, message_id, date, role.
                Optional keys: thread_id, from_user_id, text_content, caption,
                    reply_to_message_id, media_group_id, attachments, edit_date,
                    thinking_blocks, sender_display, forward_origin, reply_snippet,
                    reply_sender_display, quote_data.

        Returns:
            List of created Message instances.

        Note:
            Does NOT invalidate cache per-message for performance.
            Caller should invalidate relevant thread caches after batch insert.
        """
        if not messages_data:
            return []

        messages = []
        thread_ids_to_invalidate: set[int] = set()

        for msg_data in messages_data:
            attachments = msg_data.get("attachments", [])

            # Calculate denormalized flags
            has_photos = any(att.get("type") == "photo" for att in attachments)
            has_documents = any(
                att.get("type") == "document" for att in attachments)
            has_voice = any(att.get("type") == "voice" for att in attachments)
            has_video = any(att.get("type") == "video" for att in attachments)
            attachment_count = len(attachments)

            message = Message(
                chat_id=msg_data["chat_id"],
                message_id=msg_data["message_id"],
                thread_id=msg_data.get("thread_id"),
                from_user_id=msg_data.get("from_user_id"),
                date=msg_data["date"],
                edit_date=msg_data.get("edit_date"),
                role=msg_data["role"],
                text_content=msg_data.get("text_content"),
                caption=msg_data.get("caption"),
                reply_to_message_id=msg_data.get("reply_to_message_id"),
                reply_snippet=msg_data.get("reply_snippet"),
                reply_sender_display=msg_data.get("reply_sender_display"),
                quote_data=msg_data.get("quote_data"),
                forward_origin=msg_data.get("forward_origin"),
                sender_display=msg_data.get("sender_display"),
                edit_count=0,
                original_content=None,
                media_group_id=msg_data.get("media_group_id"),
                has_photos=has_photos,
                has_documents=has_documents,
                has_voice=has_voice,
                has_video=has_video,
                attachment_count=attachment_count,
                attachments=attachments,
                thinking_blocks=msg_data.get("thinking_blocks"),
                created_at=msg_data["date"],
            )
            self.session.add(message)
            messages.append(message)

            # Track thread IDs for cache invalidation
            if msg_data.get("thread_id"):
                thread_ids_to_invalidate.add(msg_data["thread_id"])

        # Single flush for all messages
        await self.session.flush()

        # Invalidate caches for all affected threads
        for thread_id in thread_ids_to_invalidate:
            await invalidate_messages(thread_id)

        logger.info(
            "messages.batch_created",
            count=len(messages),
            threads_invalidated=len(thread_ids_to_invalidate),
        )

        return messages

    async def count_messages_in_thread(self, thread_id: int) -> int:
        """Count messages in a thread by internal thread ID.

        Args:
            thread_id: Internal thread ID (from threads table).

        Returns:
            Number of messages in the thread.
        """
        from sqlalchemy import func

        stmt = select(func.count()).select_from(Message).where(
            Message.thread_id == thread_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0
