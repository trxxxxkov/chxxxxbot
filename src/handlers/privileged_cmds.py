from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.utils.validations import authorized
from src.database.queries import db_execute, db_get_user, db_update_user
from src.utils.formatting import send

rt = Router()


@rt.message(Command("add"))
async def add_handler(message: Message) -> None:
    if await authorized(message):
        if len(message.text.split()) != 3:
            text = "_Error: the command must have the following syntax:_ `/add USER_ID [+/-]FUNDS`."
            await send(message, text)
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
                await send(message, "_Done._")
            elif funds.replace(".", "", 1).isdigit():
                user["balance"] = float(funds)
                await db_update_user(user)
                await send(message, "_Done._")
            else:
                await send(message, f"_Error: {funds} is not a valid numeric data._")
        else:
            await send(message, f"_The user *{user_id}* is not found._")
