from aiogram import Router, types
from aiogram.types import Message
from aiogram.filters import Command

from src.database.queries import db_get_messages

rt = Router()


@rt.message(Command("as_file"))
async def as_file_handler(message: Message) -> None:
    messages = db_get_messages(message.from_user.id)
    if messages:
        pass
    else:
        pass
