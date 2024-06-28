import json
from openai import OpenAIError

from aiogram.types import Message
from aiogram import types


def write_error(error, func, args, kwargs, messages, path="errors.json"):
    with open(path, "r") as f:
        try:
            errors = json.load(f)
        except Exception:
            errors = list()
    errors.append(
        {
            "error": f"{error}",
            "function": f"{func}",
            "args": f"{args}",
            "kwargs": f"{kwargs}",
            "messages": f"{messages}",
        }
    )
    with open(path, "w") as f:
        json.dump(errors, f)


def logged(f):
    async def wrap(*args, **kwargs):
        try:
            result = await f(*args, **kwargs)
            return result
        except (Exception, OpenAIError) as e:
            alert = format(f"_ERROR: {e}_")
            await bot.send_message(OWNER_CHAT_ID, alert)
            messages = None
            try:
                for arg in args:
                    if isinstance(arg, Message):
                        kbd = inline_kbd({"error": "error"}, language(arg))
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
                        kbd = inline_kbd({"error": "error"}, language(arg))
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
            write_error(e, f.__name__, args, kwargs, messages)

    return wrap


if __name__ == "__main__":
    from src.templates.keyboards.inline_kbd import inline_kbd
    from src.database.queries import db_execute
    from src.utils.validations import language
    from src.utils.globals import bot, OWNER_CHAT_ID
