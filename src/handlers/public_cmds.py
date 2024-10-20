"""Handlers for commands that are visible from Telegram's Bot Menu interface.

Here are the only commands that you want your users to use. The list is kept short
to avoid users get distracted from the bot's core functionality.
"""

import aiogram

from src.openai import openai_globals
from src.utils import bot_globals

rt = aiogram.Router()


@rt.message()
async def default_handler(message: aiogram.types.Message) -> None:
    """Process all unhandled updates."""
    user = bot_globals.bot_users[message.from_user.id]
    message = await openai_globals.client.beta.threads.messages.create(
        thread_id=user["thread_id"],
        role="user",
        content=message.text,
    )
    run = await openai_globals.client.beta.threads.runs.create_and_poll(
        thread_id=user["thread_id"],
        assistant_id=user["assistant_id"],
    )
    if run.status == "completed":
        messages = await openai_globals.client.beta.threads.messages.list(
            thread_id=user["thread_id"]
        )
        print(messages)
    else:
        print(run.status)
