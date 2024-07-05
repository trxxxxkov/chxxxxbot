from aiogram import Router, types
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.types import FSInputFile

from src.database.queries import db_execute
from src.utils.globals import bot

rt = Router()


@rt.message(Command("as_file"))
async def as_file_handler(message: Message) -> None:
    messages = await db_execute(
        "SELECT * FROM messages WHERE from_user_id = %s ORDER BY timestamp;",
        message.from_user.id,
    )
    if messages:
        if isinstance(messages, list):
            last_msg = messages[-1]
        else:
            last_msg = message
        path_to_file = f"src/utils/temp/markdown/{last_msg['message_id']}-as_file.md"
        with open(path_to_file, "w") as f:
            f.write(last_msg["text"])
        await bot.send_document(
            message.chat.id,
            FSInputFile(path_to_file),
            reply_to_message_id=last_msg["message_id"],
        )
    else:
        await bot.send_message(message.chat.id, "no messages")
