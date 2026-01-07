"""Base repository with common CRUD operations.

This module provides the base repository class with generic CRUD operations
that can be inherited by specific model repositories.

NO __init__.py - use direct import:
    from db.repositories.base import BaseRepository
"""

from typing import Any, Generic, Optional, TypeVar

from db.models.base import Base
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType", bound=Base)  # pylint: disable=invalid-name


class BaseRepository(Generic[ModelType]):
    """Base repository with common database operations.

    Provides standard CRUD operations that can be inherited by
    specific model repositories. Uses SQLAlchemy 2.0 async patterns.

    Type Parameters:
        ModelType: SQLAlchemy model class bound to Base.

    Attributes:
        session: AsyncSession for database operations.
        model: SQLAlchemy model class.
    """

    def __init__(self, session: AsyncSession, model: type[ModelType]):
        """Initialize repository with session and model class.

        Args:
            session: AsyncSession for database operations.
            model: SQLAlchemy model class.
        """
        self.session = session
        self.model = model

    async def get_by_id(self, id_value: Any) -> Optional[ModelType]:
        """Get entity by primary key.

        Args:
            id_value: Primary key value (can be single value or tuple for
                composite keys).

        Returns:
            Entity instance or None if not found.
        """
        return await self.session.get(self.model, id_value)

    async def get_all(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ModelType]:
        """Get all entities with pagination.

        Args:
            limit: Max number of entities to return. Defaults to 100.
            offset: Number of entities to skip. Defaults to 0.

        Returns:
            List of entity instances.
        """
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, entity: ModelType) -> ModelType:
        """Create new entity.

        Args:
            entity: Entity instance to create.

        Returns:
            Created entity with ID populated.

        Note:
            This method does not commit. Commit is handled by middleware.
        """
        self.session.add(entity)
        await self.session.flush()  # Populate ID without committing
        return entity

    async def update(self, entity: ModelType) -> ModelType:
        """Update existing entity.

        Args:
            entity: Entity instance to update (must be attached to session).

        Returns:
            Updated entity.

        Note:
            This method does not commit. Commit is handled by middleware.
        """
        await self.session.merge(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelType) -> None:
        """Delete entity.

        Args:
            entity: Entity instance to delete.

        Note:
            This method does not commit. Commit is handled by middleware.
        """
        await self.session.delete(entity)
        await self.session.flush()
