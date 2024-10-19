"""Bot entrypoint"""

import logging
import sys
import os

import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from dotenv import load_dotenv


load_dotenv()

dp = Dispatcher()

async def main() -> None:
    """Initialize Bot instance and start polling.

    Initialize Bot instance with default bot properties which will be passed to
    all API calls and run event dispatching.
    """
    tg_bot_token = os.getenv("TG_BOT_TOKEN")
    bot = Bot(
        token=tg_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
