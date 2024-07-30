"""Handlers for bot commands that are hidden from user interface.

To show a command to a user, the command must be added to the list of commands. 
Otherwise the command will work, but the user will not get any syntax tips while
typing it.
 The following commands are intended to onetime usage or are so rare that they
were hidden to save free space in Bot Menu in Telegram interface.
"""

from aiogram import Router
from aiogram.types import Message, BotCommand, LinkPreviewOptions
from aiogram.filters import Command

import src.templates.tutorial.videos
from src.utils.globals import bot
from src.templates.scripted_dialogues import dialogues
from src.templates.bot_menu import bot_menu
from src.templates.keyboards.inline_kbd import inline_kbd
from src.handlers.public_cmds import balance_handler, help_handler
from src.utils.formatting import format_tg_msg
from src.utils.validations import add_user, language, tutorial_videos2ids

rt = Router()


@rt.message(Command("start"))
async def start_handler(message: Message) -> None:
    """Initialize user's account with language, Bot Menu commands and welcome gift.

    This command is not intended for multiple uses. All of its functionality is
    duplicated by default message handler which ensures that the user's data
    will be always up-to-date.
    During user's initialization the following happens:
     - User's system language is determined and the corresponding Bot Menu commands
     are chosen;
     - /help message is shown;
     - User is added to the 'users' table in the database;
     - Videos used in /help messages are sent to the bot owner and their file_id's
     are written into /src/templates/tutorial/videos.py dictionary.

     Because most of the data collected changes over time, it is updated each
     time the user send prompts to GPT.
    """
    await bot.set_my_commands(
        [
            BotCommand(command=key, description=value[language(message)])
            for key, value in bot_menu.items()
        ]
    )
    await help_handler(message)
    # If user not yet in the database, which means he never used /start command,
    # add the user to the database with an initial balance of $0.015
    await add_user(message)
    # If tutorial videos were never sended, send them and save their file_ids.
    if src.templates.tutorial.videos.videos is None:
        await tutorial_videos2ids()


@rt.message(Command("paysupport"))
async def paysupport_handler(message: Message) -> None:
    """Telegram requires support of this command that does the same things as /balance"""
    await balance_handler(message)


@rt.message(Command("privacy"))
async def privacy_handler(message: Message) -> None:
    """Telegram requires support of this command.

    TODO: add required information to this handler.
    Probably, this will help-  https://www.privacypolicygenerator.info/
    """
    await message.answer(format_tg_msg("_Your data will be fine._"))
