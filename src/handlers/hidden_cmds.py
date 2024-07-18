from aiogram import Router
from aiogram.types import Message, BotCommand, LinkPreviewOptions
from aiogram.filters import Command

import src.templates.tutorial.videos
from src.utils.globals import bot
from src.templates.scripts import scripts
from src.templates.bot_menu import bot_menu
from src.templates.keyboards.inline_kbd import inline_kbd
from src.handlers.public_cmds import help_handler
from src.utils.formatting import send_template_answer, format_tg_msg
from src.utils.validations import add_user, language, template_videos2ids

rt = Router()


@rt.message(Command("start"))
async def start_handler(message: Message) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command=key, description=value[language(message)])
            for key, value in bot_menu.items()
        ]
    )
    kbd = inline_kbd(
        {"back to help": "send help", "to tokens": "sep tokens"}, language(message)
    )
    await message.answer(
        scripts["doc"]["start"][language(message)].format(
            format_tg_msg(message.from_user.first_name)
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=kbd,
    )
    await add_user(message)
    if src.templates.tutorial.videos.videos is None:
        await template_videos2ids()


@rt.message(Command("paysupport"))
async def paysupport_handler(message: Message) -> None:
    await help_handler(message)


@rt.message(Command("privacy"))
async def privacy_handler(message: Message) -> None:
    await message.answer(format_tg_msg("_Your data will be fine._"))
