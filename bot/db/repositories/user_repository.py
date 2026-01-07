"""User repository for database operations.

This module provides the UserRepository for working with User model,
including Telegram-specific operations like get_or_create.

NO __init__.py - use direct import:
    from db.repositories.user_repository import UserRepository
"""

from datetime import datetime
from datetime import timezone
from typing import Optional

from db.models.user import User
from db.repositories.base import BaseRepository
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class UserRepository(BaseRepository[User]):
    """Repository for User model operations.

    Provides database operations specific to User model,
    including Telegram user management.

    Attributes:
        session: AsyncSession inherited from BaseRepository.
        model: User model class inherited from BaseRepository.
    """

    def __init__(self, session: AsyncSession):
        """Initialize with User model.

        Args:
            session: AsyncSession for database operations.
        """
        super().__init__(session, User)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID.

        Args:
            telegram_id: Telegram user ID.

        Returns:
            User instance or None if not found.
        """
        logger.debug("user_repository.get_by_telegram_id",
                     telegram_id=telegram_id)
        user = await self.session.get(User, telegram_id)
        logger.debug("user_repository.get_by_telegram_id.result",
                     telegram_id=telegram_id,
                     found=user is not None)
        return user

    async def get_or_create(
        self,
        telegram_id: int,
        is_bot: bool = False,
        first_name: str = "",
        last_name: Optional[str] = None,
        username: Optional[str] = None,
        language_code: Optional[str] = None,
        is_premium: bool = False,
        added_to_attachment_menu: bool = False,
    ) -> tuple[User, bool]:
        """Get existing user or create new one.

        If user exists, updates their profile information.
        If user doesn't exist, creates new user with provided data.

        Args:
            telegram_id: Telegram user ID (required).
            is_bot: Whether this is a bot account. Defaults to False.
            first_name: User's first name. Defaults to empty string.
            last_name: User's last name. Defaults to None.
            username: Telegram username. Defaults to None.
            language_code: IETF language tag. Defaults to None.
            is_premium: Telegram Premium status. Defaults to False.
            added_to_attachment_menu: Bot in attachment menu.
                Defaults to False.

        Returns:
            Tuple of (User instance, was_created boolean).
            - was_created = True: New user created
            - was_created = False: Existing user returned (and updated)
        """
        logger.info("user_repository.get_or_create.start",
                    telegram_id=telegram_id,
                    username=username)

        user = await self.get_by_telegram_id(telegram_id)

        if user:
            # Update user info if changed
            logger.debug("user_repository.get_or_create.updating_existing",
                         telegram_id=telegram_id,
                         username=username)
            user.is_bot = is_bot
            user.first_name = first_name
            user.last_name = last_name
            user.username = username
            user.language_code = language_code
            user.is_premium = is_premium
            user.added_to_attachment_menu = added_to_attachment_menu
            user.last_seen_at = datetime.now(timezone.utc)
            await self.session.flush()

            logger.info("user_repository.get_or_create.complete",
                        telegram_id=telegram_id,
                        username=username,
                        was_created=False)
            return user, False

        # Create new user
        logger.debug("user_repository.get_or_create.creating_new",
                     telegram_id=telegram_id,
                     username=username)
        now = datetime.now(timezone.utc)
        user = User(
            id=telegram_id,
            is_bot=is_bot,
            first_name=first_name,
            last_name=last_name,
            username=username,
            language_code=language_code,
            is_premium=is_premium,
            added_to_attachment_menu=added_to_attachment_menu,
            first_seen_at=now,
            last_seen_at=now,
        )
        self.session.add(user)
        await self.session.flush()

        logger.info("user_repository.get_or_create.complete",
                    telegram_id=telegram_id,
                    username=username,
                    was_created=True)
        return user, True

    async def update_last_seen(self, telegram_id: int) -> None:
        """Update user's last_seen_at timestamp.

        Args:
            telegram_id: Telegram user ID.

        Raises:
            ValueError: If user not found.
        """
        logger.debug("user_repository.update_last_seen",
                     telegram_id=telegram_id)

        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            logger.warning("user_repository.update_last_seen.user_not_found",
                           telegram_id=telegram_id)
            raise ValueError(f"User {telegram_id} not found")

        user.last_seen_at = datetime.now(timezone.utc)
        await self.session.flush()

        logger.debug("user_repository.update_last_seen.complete",
                     telegram_id=telegram_id)

    async def get_users_count(self) -> int:
        """Get total number of users.

        Returns:
            Number of users in database.
        """
        logger.debug("user_repository.get_users_count")

        stmt = select(func.count()).select_from(User)
        result = await self.session.execute(stmt)
        count = result.scalar_one()

        logger.info("user_repository.get_users_count.complete",
                    total_users=count)
        return count
