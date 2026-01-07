"""Chat repository for database operations.

This module provides the ChatRepository for working with Chat model,
including Telegram-specific operations like get_or_create.

NO __init__.py - use direct import:
    from db.repositories.chat_repository import ChatRepository
"""

from typing import Optional

from db.models.chat import Chat
from db.repositories.base import BaseRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class ChatRepository(BaseRepository[Chat]):
    """Repository for Chat model operations.

    Provides database operations specific to Chat model,
    including Telegram chat management (private/group/supergroup/channel).

    Attributes:
        session: AsyncSession inherited from BaseRepository.
        model: Chat model class inherited from BaseRepository.
    """

    def __init__(self, session: AsyncSession):
        """Initialize with Chat model.

        Args:
            session: AsyncSession for database operations.
        """
        super().__init__(session, Chat)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[Chat]:
        """Get chat by Telegram ID.

        Args:
            telegram_id: Telegram chat ID.

        Returns:
            Chat instance or None if not found.
        """
        return await self.session.get(Chat, telegram_id)

    async def get_or_create(
        self,
        telegram_id: int,
        chat_type: str,
        title: Optional[str] = None,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        is_forum: bool = False,
    ) -> tuple[Chat, bool]:
        """Get existing chat or create new one.

        If chat exists, updates its information.
        If chat doesn't exist, creates new chat with provided data.

        Args:
            telegram_id: Telegram chat ID (required).
            chat_type: Chat type (private/group/supergroup/channel).
            title: Chat title (for groups/channels). Defaults to None.
            username: Public username (@chatname). Defaults to None.
            first_name: First name (private chats only). Defaults to None.
            last_name: Last name (private chats only). Defaults to None.
            is_forum: Whether supergroup has topics enabled.
                Defaults to False.

        Returns:
            Tuple of (Chat instance, was_created boolean).
            - was_created = True: New chat created
            - was_created = False: Existing chat returned (and updated)
        """
        logger.info("chat_repository.get_or_create.start",
                    telegram_id=telegram_id,
                    chat_type=chat_type,
                    username=username)

        chat = await self.get_by_telegram_id(telegram_id)

        if chat:
            # Update chat info if changed
            logger.debug("chat_repository.get_or_create.updating_existing",
                         telegram_id=telegram_id,
                         chat_type=chat_type)
            chat.type = chat_type
            chat.title = title
            chat.username = username
            chat.first_name = first_name
            chat.last_name = last_name
            chat.is_forum = is_forum
            await self.session.flush()

            logger.info("chat_repository.get_or_create.complete",
                        telegram_id=telegram_id,
                        chat_type=chat_type,
                        was_created=False)
            return chat, False

        # Create new chat
        logger.debug("chat_repository.get_or_create.creating_new",
                     telegram_id=telegram_id,
                     chat_type=chat_type)
        chat = Chat(
            id=telegram_id,
            type=chat_type,
            title=title,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_forum=is_forum,
        )
        self.session.add(chat)
        await self.session.flush()

        logger.info("chat_repository.get_or_create.complete",
                    telegram_id=telegram_id,
                    chat_type=chat_type,
                    was_created=True)
        return chat, True

    async def get_by_username(self, username: str) -> Optional[Chat]:
        """Get chat by username.

        Args:
            username: Chat username (without @ prefix).

        Returns:
            Chat instance or None if not found.
        """
        stmt = select(Chat).where(Chat.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_type(
        self,
        chat_type: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Chat]:
        """Get chats by type.

        Args:
            chat_type: Chat type to filter by
                (private/group/supergroup/channel).
            limit: Max number of chats to return. Defaults to 100.
            offset: Number of chats to skip. Defaults to 0.

        Returns:
            List of Chat instances.
        """
        stmt = (select(Chat).where(
            Chat.type == chat_type).limit(limit).offset(offset))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_forum_chats(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Chat]:
        """Get chats with forum/topics enabled.

        Args:
            limit: Max number of chats to return. Defaults to 100.
            offset: Number of chats to skip. Defaults to 0.

        Returns:
            List of Chat instances with is_forum=True.
        """
        stmt = (select(Chat).where(
            Chat.is_forum.is_(True)).limit(limit).offset(offset))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
