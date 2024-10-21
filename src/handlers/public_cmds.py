"""Handlers for commands that are visible from Telegram's Bot Menu interface.

Here are the only commands that you want your users to use. The list is kept short
to avoid users get distracted from the bot's core functionality.
"""

import aiogram

from src.openai import openai_globals, tools
from src.utils import bot_globals, user_management, text_formatting


rt = aiogram.Router()


@rt.message(aiogram.filters.Command("forget"))
async def forget_handler(message: aiogram.types.Message) -> None:
    """Delete current user's thread and crate a new one instead."""
    user = bot_globals.bot_users[message.from_user.id]
    await openai_globals.client.beta.threads.delete(user["thread_id"])
    empty_thread = await openai_globals.client.beta.threads.create()
    bot_globals.bot_users[message.from_user.id]["thread_id"] = empty_thread.id


@rt.message()
async def default_handler(message: aiogram.types.Message) -> None:
    """Process all unhandled updates."""
    if not user_management.is_allowed(message):
        return
    user = bot_globals.bot_users[message.from_user.id]
    thread_message = {
        "thread_id": user["thread_id"],
        "role": "user",
        "content": text_formatting.extract_text(message),
    }
    if message.document:
        uploaded_file_id = await tools.upload_file(message.document, "assistants")
        thread_message["attachments"] = [
            {"file_id": uploaded_file_id, "tools": [{"type": "file_search"}]}
        ]
    await openai_globals.client.beta.threads.messages.create(**thread_message)
    await tools.stream_events(message, user)
