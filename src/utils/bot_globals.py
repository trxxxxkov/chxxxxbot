"""Global objects and constants for Telegram Bot API"""

import os

import dotenv
import aiogram
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

dotenv.load_dotenv()

bot = aiogram.Bot(
    token=os.getenv("TG_BOT_TOKEN"),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
