"""Initialize database schema.

Creates all tables defined in SQLAlchemy models.
Run once after creating new database.
"""

import asyncio

from config import get_database_url
# Import all models to ensure they're registered
# pylint: disable=unused-import
from db.models.balance_operation import BalanceOperation  # noqa: F401
from db.models.base import Base
from db.models.chat import Chat  # noqa: F401
from db.models.message import Message  # noqa: F401
from db.models.payment import Payment  # noqa: F401
from db.models.thread import Thread  # noqa: F401
from db.models.user import User  # noqa: F401
from db.models.user_file import UserFile  # noqa: F401
# pylint: enable=unused-import
from sqlalchemy.ext.asyncio import create_async_engine


async def init_database():
    """Create all database tables."""
    database_url = get_database_url()
    engine = create_async_engine(database_url, echo=True)

    print("Creating database tables...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await engine.dispose()

    print("✅ Database tables created successfully!")


if __name__ == "__main__":
    asyncio.run(init_database())
