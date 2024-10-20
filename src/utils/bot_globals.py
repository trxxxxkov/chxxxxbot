"""Global objects and constants for Telegram Bot API"""

import os

import dotenv
import aiogram
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

dotenv.load_dotenv()

# Main aiogram's API object.
bot = aiogram.Bot(
    token=os.getenv("TG_BOT_TOKEN"),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

# List of bot's admins' telegram ids.
PRIVILEGED_USERS_ID = tuple(
    int(id) for id in os.getenv("PRIVILEGED_USERS_ID").split(",") if id
)

# Temprorary storage for bot users' data.
# The scheme is as following:
# bot_users = {
#     "user_id": {
#         "assistant_id": int,
#         "thread_id": int,
#         "language": str,
#         "balance_usd": float,
#     }
# }
bot_users = {}
