from aiogram import Router, types
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.types import FSInputFile

import src.templates.tutorial.videos
from src.utils.globals import bot
from src.templates.bot_menu import bot_menu
from src.templates.keyboards.reply_kbd import help_keyboard
from src.handlers.public_cmds import help_handler
from src.utils.formatting import send_template_answer
from src.utils.validations import add_user, language, template_videos2ids
from src.database.queries import db_execute

rt = Router()


@rt.message(Command("start"))
async def start_handler(message: Message) -> None:
    await bot.set_my_commands(
        [
            types.BotCommand(command=key, description=value[language(message)])
            for key, value in bot_menu.items()
        ]
    )
    await add_user(message)
    await send_template_answer(
        message,
        "doc",
        "start",
        message.from_user.first_name,
        reply_markup=help_keyboard,
    )
    if src.templates.tutorial.videos.videos is None:
        await template_videos2ids()


@rt.message(Command("paysupport"))
async def paysupport_handler(message: Message) -> None:
    await help_handler(message)


@rt.message(Command("privacy"))
async def privacy_handler(message: Message) -> None:
    await bot.send_message(message.chat.id, "Your data will be fine.")
