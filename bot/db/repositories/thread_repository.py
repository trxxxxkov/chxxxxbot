"""Thread repository for database operations.

This module provides the ThreadRepository for working with Thread model,
including conversation thread management with Telegram thread_id support.

Phase 3.2: Uses Redis cache for fast thread lookups.

NO __init__.py - use direct import:
    from db.repositories.thread_repository import ThreadRepository
"""

from typing import Optional

from cache.thread_cache import cache_thread
from cache.thread_cache import get_cached_thread
from db.models.thread import Thread
from db.repositories.base import BaseRepository
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class ThreadRepository(BaseRepository[Thread]):
    """Repository for Thread model operations.

    Provides database operations specific to Thread model,
    including conversation thread management with Telegram thread_id support.
    Each user has separate threads per topic (forum topic or main chat).

    Attributes:
        session: AsyncSession inherited from BaseRepository.
        model: Thread model class inherited from BaseRepository.
    """

    def __init__(self, session: AsyncSession):
        """Initialize with Thread model.

        Args:
            session: AsyncSession for database operations.
        """
        super().__init__(session, Thread)

    async def get_or_create_thread(
        self,
        chat_id: int,
        user_id: int,
        thread_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> tuple[Thread, bool]:
        """Get existing thread or create new one.

        Respects unique constraint: one thread per user per topic.
        - thread_id = None → main chat (no forum topic)
        - thread_id = 123 → forum topic with ID 123

        If thread exists, updates its metadata (title).
        If thread doesn't exist, creates new thread.

        Note: Model selection is per user (User.model_id), not per thread.
        Note: System prompt will be composed in Phase 1.4.2:
              GLOBAL_SYSTEM_PROMPT + User.custom_prompt + thread.files_context

        Args:
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            thread_id: Telegram thread/topic ID (None for main chat).
            title: Thread title. Defaults to None.

        Returns:
            Tuple of (Thread instance, was_created boolean).
            - was_created = True: New thread created
            - was_created = False: Existing thread returned (and updated)
        """
        thread = await self.get_active_thread(chat_id, user_id, thread_id)

        if thread:
            # Update thread metadata if explicitly provided
            if title is not None:
                thread.title = title
            await self.session.flush()
            return thread, False

        # Create new thread with race condition handling using savepoint
        thread = Thread(
            chat_id=chat_id,
            user_id=user_id,
            thread_id=thread_id,
            title=title,
        )
        try:
            # Use savepoint (nested transaction) so IntegrityError
            # doesn't invalidate the entire transaction
            async with self.session.begin_nested():
                self.session.add(thread)
                await self.session.flush()
            return thread, True
        except IntegrityError:
            # Race condition: another request created the thread
            # Savepoint was rolled back, main transaction still active
            thread = await self.get_active_thread(chat_id, user_id, thread_id)
            if thread:
                return thread, False
            # Should not happen, but re-raise if thread still not found
            raise

    async def get_active_thread(
        self,
        chat_id: int,
        user_id: int,
        thread_id: Optional[int] = None,
    ) -> Optional[Thread]:
        """Get active thread for user in specific chat/topic.

        Finds thread matching (chat_id, user_id, thread_id) combination.
        Uses COALESCE to handle NULL thread_id correctly.

        Phase 3.2: Checks Redis cache first, falls back to DB on miss.

        Args:
            chat_id: Telegram chat ID.
            user_id: Telegram user ID.
            thread_id: Telegram thread/topic ID (None for main chat).

        Returns:
            Thread instance or None if not found.
        """
        # Phase 3.2: Check cache first
        cached = await get_cached_thread(chat_id, user_id, thread_id)
        if cached:
            # Cache hit - get thread by internal ID
            internal_id = cached.get("id")
            if internal_id:
                thread = await self.get_by_id(internal_id)
                if thread:
                    return thread
                # Cache stale - thread deleted, continue to DB

        # Cache miss or stale - query database
        # Use COALESCE to match the unique constraint logic
        stmt = select(Thread).where(
            Thread.chat_id == chat_id,
            Thread.user_id == user_id,
            func.coalesce(Thread.thread_id,
                          0) == (thread_id if thread_id else 0),
        )
        result = await self.session.execute(stmt)
        thread = result.scalar_one_or_none()

        # Cache the result for future lookups
        if thread:
            await cache_thread(
                chat_id=chat_id,
                user_id=user_id,
                thread_id=thread_id,
                internal_id=thread.id,
                title=thread.title,
                files_context=thread.files_context,
            )

        return thread

    async def get_user_threads(
        self,
        user_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Thread]:
        """Get all threads for a user.

        Args:
            user_id: Telegram user ID.
            limit: Max number of threads to return. Defaults to 100.
            offset: Number of threads to skip. Defaults to 0.

        Returns:
            List of Thread instances ordered by updated_at DESC.
        """
        stmt = (select(Thread).where(Thread.user_id == user_id).order_by(
            Thread.updated_at.desc()).limit(limit).offset(offset))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_chat_threads(
        self,
        chat_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Thread]:
        """Get all threads in a chat.

        Args:
            chat_id: Telegram chat ID.
            limit: Max number of threads to return. Defaults to 100.
            offset: Number of threads to skip. Defaults to 0.

        Returns:
            List of Thread instances ordered by updated_at DESC.
        """
        stmt = (select(Thread).where(Thread.chat_id == chat_id).order_by(
            Thread.updated_at.desc()).limit(limit).offset(offset))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_thread(self, thread_id: int) -> None:
        """Delete thread by internal ID.

        Args:
            thread_id: Internal thread ID (not Telegram thread_id).

        Raises:
            ValueError: If thread not found.
        """
        thread = await self.get_by_id(thread_id)
        if not thread:
            raise ValueError(f"Thread {thread_id} not found")

        await self.session.delete(thread)
        await self.session.flush()

    async def get_threads_count(self) -> int:
        """Get total number of threads.

        Returns:
            Total count of all threads in database.
        """
        stmt = select(func.count()).select_from(Thread)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_unique_topic_ids(self, chat_id: int) -> list[int]:
        """Get unique Telegram topic IDs for a chat.

        Returns distinct thread_id values (Telegram forum topic IDs)
        for the given chat, excluding NULL (main chat).

        Args:
            chat_id: Telegram chat ID.

        Returns:
            List of unique Telegram topic IDs (not internal thread IDs).
        """
        stmt = (select(Thread.thread_id).where(
            Thread.chat_id == chat_id, Thread.thread_id.isnot(None)).distinct())
        result = await self.session.execute(stmt)
        return [row[0] for row in result.fetchall()]

    async def delete_threads_by_topic_id(
        self,
        chat_id: int,
        topic_id: int,
    ) -> int:
        """Delete all threads for a specific Telegram topic with cascade.

        Performs cascading delete in order:
        1. user_files - files linked to messages in these threads
        2. messages - all messages in these threads
        3. threads - the thread records themselves

        Args:
            chat_id: Telegram chat ID.
            topic_id: Telegram forum topic ID (thread_id).

        Returns:
            Number of threads deleted.
        """
        from db.models.message import Message
        from db.models.user_file import UserFile
        from sqlalchemy import delete as sql_delete
        from utils.structured_logging import get_logger

        logger = get_logger(__name__)

        # 1. Get all internal thread IDs for this topic
        thread_ids_stmt = select(Thread.id).where(
            Thread.chat_id == chat_id,
            Thread.thread_id == topic_id,
        )
        thread_ids_result = await self.session.execute(thread_ids_stmt)
        thread_ids = [row[0] for row in thread_ids_result.fetchall()]

        if not thread_ids:
            return 0

        # 2. Get all message IDs in these threads
        message_ids_stmt = select(Message.message_id).where(
            Message.chat_id == chat_id,
            Message.thread_id.in_(thread_ids),
        )
        message_ids_result = await self.session.execute(message_ids_stmt)
        message_ids = [row[0] for row in message_ids_result.fetchall()]

        # 3. Delete user_files for these messages
        deleted_files = 0
        if message_ids:
            files_stmt = sql_delete(UserFile).where(
                UserFile.message_id.in_(message_ids))
            files_result = await self.session.execute(files_stmt)
            deleted_files = files_result.rowcount

        # 4. Delete messages in these threads
        deleted_messages = 0
        if thread_ids:
            messages_stmt = sql_delete(Message).where(
                Message.chat_id == chat_id,
                Message.thread_id.in_(thread_ids),
            )
            messages_result = await self.session.execute(messages_stmt)
            deleted_messages = messages_result.rowcount

        # 5. Delete the threads
        threads_stmt = sql_delete(Thread).where(
            Thread.chat_id == chat_id,
            Thread.thread_id == topic_id,
        )
        threads_result = await self.session.execute(threads_stmt)
        deleted_threads = threads_result.rowcount

        await self.session.flush()

        logger.info(
            "thread.cascade_delete",
            chat_id=chat_id,
            topic_id=topic_id,
            deleted_threads=deleted_threads,
            deleted_messages=deleted_messages,
            deleted_files=deleted_files,
        )

        return deleted_threads
