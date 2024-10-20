"""Bot entrypoint"""

import asyncio
import logging
import sys

import aiogram

from src.openai import assistants
from src.utils import bot_globals
from src.handlers import callbacks, hidden_cmds, public_cmds


async def main() -> None:
    """Initialize Bot instance and start polling.

    Initialize Bot instance with default bot properties which will be passed to
    all API calls and run event dispatching.
    """
    dp = aiogram.Dispatcher()
    dp.include_routers(callbacks.rt, hidden_cmds.rt, public_cmds.rt)
    await assistants.initialize_assistants()
    await dp.start_polling(bot_globals.bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
