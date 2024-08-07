"""Handlers for commands that should be available only for bot owner and privileged users."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.utils.validations import authorized
from src.database.queries import db_execute, db_get_user, db_update_user
from src.utils.formatting import format_tg_msg

rt = Router()


@rt.message(Command("add"))
async def add_handler(message: Message) -> None:
    """Change user's balance by relative or absolute values in USD.

    The command's syntax:

    /add [USER_ID] [+,-]FUNDS

    where FUNDS is a float or integer value of USD you want to add/substract from
    the account of a user with user_id equal USER_ID (it must be already in the
    database).
     If there is a '+' or '-' before FUNDS, then the FUNDS is a relative change.
    Otherwise the user's balance will be set exactly to FUNDS USD.
    """
    # If user is not privileged, notify him
    if await authorized(message):
        if len(message.text.split()) != 3:
            text = "_Error: the command must have the following syntax:_ `/add USER_ID [+/-]FUNDS`."
            await message.answer(format_tg_msg(text))
            return
        _, user_id, funds = message.text.split()
        user_id = int(user_id)
        bot_users = await db_execute("SELECT id FROM users;")
        if not isinstance(bot_users, list):
            bot_users = [bot_users]
        if user_id in [item["id"] for item in bot_users]:
            user = await db_get_user(user_id)
            if funds.startswith(("+", "-")) and funds[1:].replace(".", "", 1).isdigit():
                user["balance"] += float(funds)
                await db_update_user(user)
                await message.answer(format_tg_msg("_Done._"))
            elif funds.replace(".", "", 1).isdigit():
                user["balance"] = float(funds)
                await db_update_user(user)
                await message.answer(format_tg_msg("_Done._"))
            else:
                await message.answer(
                    format_tg_msg(f"_Error: {funds} is not a valid numeric data._")
                )
        else:
            await message.answer(
                format_tg_msg(f"_The user *{user_id}* is not found in the database._")
            )
