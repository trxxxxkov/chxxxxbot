from aiogram import Router, types
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.types import FSInputFile

from src.utils.globals import bot
from src.utils.formatting import send_template_answer
from src.database.queries import db_execute

rt = Router()


@rt.message(Command("as_file"))
async def as_file_handler(message: Message) -> None:
    messages = await db_execute(
        "SELECT * FROM messages WHERE from_user_id = %s ORDER BY timestamp;",
        message.from_user.id,
    )
    if messages and isinstance(messages, list):
        last_msg = messages[-1]
        prompt = messages[-2]
        path_to_file = f"src/utils/temp/markdown/{message.from_user.id}-as_file.md"
        with open(path_to_file, "w") as f:
            f.write(last_msg["text"])
        await bot.send_document(
            message.chat.id,
            FSInputFile(path_to_file),
            reply_to_message_id=prompt["message_id"],
        )
    else:
        await send_template_answer(message, "as_file")
