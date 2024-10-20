"""Handlers for commands that are visible from Telegram's Bot Menu interface.

Here are the only commands that you want your users to use. The list is kept short
to avoid users get distracted from the bot's core functionality.
"""

import aiogram

from src.openai import openai_globals
from src.utils import bot_globals


rt = aiogram.Router()


@rt.message(aiogram.filters.Command("forget"))
async def forget_handler(message: aiogram.types.Message) -> None:
    """Delete current user's thread and crate new one instead."""
    user = bot_globals.bot_users[message.from_user.id]
    await openai_globals.client.beta.threads.delete(user["thread_id"])
    empty_thread = await openai_globals.client.beta.threads.create()
    bot_globals.bot_users[message.from_user.id]["thread_id"] = empty_thread


@rt.message()
async def default_handler(message: aiogram.types.Message) -> None:
    """Process all unhandled updates."""
    await bot_globals.bot.send_chat_action(
        message.chat.id, aiogram.enums.ChatAction.TYPING
    )
    user = bot_globals.bot_users[message.from_user.id]
    await openai_globals.client.beta.threads.messages.create(
        thread_id=user["thread_id"],
        role="user",
        content=message.text,
    )
    stream = await openai_globals.client.beta.threads.runs.create(
        thread_id=user["thread_id"], assistant_id=user["assistant_id"], stream=True
    )
    async for event in stream:
        print(event)
