"""Bot entrypoint"""

import asyncio
import logging
import sys

import aiogram

from src.openai import assistants
from src.utils import bot_globals


dp = aiogram.Dispatcher()


async def main() -> None:
    """Initialize Bot instance and start polling.

    Initialize Bot instance with default bot properties which will be passed to
    all API calls and run event dispatching.
    """
    await assistants.initialize_assistants()
    await dp.start_polling(bot_globals.bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
