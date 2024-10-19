"""Handlers for commands that are visible from Telegram's Bot Menu interface.

Here are the only commands that you want your users to use. The list is kept short
to avoid users get distracted from the bot's core functionality.
"""

import aiogram

rt = aiogram.Router()


@rt.message()
async def default_handler(message: aiogram.types.Message):
    """Process all unhandled updates."""
