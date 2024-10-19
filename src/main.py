import asyncio
import logging
import sys
from os import getenv
from dotenv import load_dotenv
from openai import OpenAI

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

load_dotenv()
BOT_TOKEN = getenv("TG_BOT_TOKEN")
client = OpenAI(api_key=getenv("OPENAI_API_KEY"))

dp = Dispatcher()

async def main() -> None:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
