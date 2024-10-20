"""Handlers for commands that are hidden from Telegram's Bot Menu interface.

Commands that you don't want your users to know about. 
"""

import aiogram

from src.utils import bot_globals
from src.utils import user_management

rt = aiogram.Router()


@rt.message(aiogram.filters.Command("start"))
async def start_handler(message: aiogram.types.Message) -> None:
    """Send a welcome message to the user and make sure he has an active account."""
    new_user_id = message.from_user.id
    new_user_lang = message.from_user.language_code
    if new_user_id not in bot_globals.bot_users:
        await user_management.user_initialization(new_user_id, new_user_lang)
    else:
        pass  # TODO: Add welcome message
