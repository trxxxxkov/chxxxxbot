import json
from openai import OpenAIError

from aiogram.types import Message, FSInputFile
from aiogram import types

from src.utils.globals import bot, OWNER_TG_ID


async def send_error_alert(error, func, args, kwargs, messages):
    path_to_file = "src/utils/temp/documents/unexpected_error.txt"
    err = f"ERROR: {error}\n\n\n \
            FUNCTION: {func}\n\n\n \
            ARGS: {args}\n\n\n \
            KWARGS: {kwargs}\n\n\n \
            PREVIOUS MESSAGES: {messages}"
    with open(path_to_file, "w") as f:
        f.write(err)
    return await bot.send_document(OWNER_TG_ID, FSInputFile(path_to_file))


def logged(f):
    async def wrap(*args, **kwargs):
        try:
            result = await f(*args, **kwargs)
            return result
        except (Exception, OpenAIError) as e:
            from src.templates.keyboards.inline_kbd import inline_kbd
            from src.database.queries import db_execute
            from src.utils.validations import language

            try:
                alert = "_ERROR\. Click the button below to see details\._"
                for arg in args:
                    if isinstance(arg, Message):
                        kbd = inline_kbd({"what now": "error"}, language(arg))
                        await bot.send_message(arg.chat.id, alert, reply_markup=kbd)
                        messages = await db_execute(
                            "SELECT * FROM messages WHERE from_user_id = %s",
                            arg.from_user.id,
                        )
                        await db_execute(
                            "DELETE FROM messages WHERE from_user_id = %s;",
                            arg.from_user.id,
                        )
                        break
                    elif isinstance(arg, types.CallbackQuery):
                        kbd = inline_kbd({"what now": "error"}, language(arg))
                        await bot.send_message(
                            arg.from_user.id,
                            alert,
                            reply_markup=kbd,
                        )
                        messages = await db_execute(
                            "SELECT * FROM messages WHERE from_user_id = %s",
                            arg.from_user.id,
                        )
                        await db_execute(
                            "DELETE FROM messages WHERE from_user_id = %s;",
                            arg.from_user.id,
                        )
                        break
            except Exception:
                messages = "[unavailable because of an error in the logging function]"
            alert = await send_error_alert(e, f.__name__, args, kwargs, messages)
            await bot.pin_chat_message(chat_id=OWNER_TG_ID, message_id=alert.message_id)

    return wrap
