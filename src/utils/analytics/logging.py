"""Logging functions and wrappers"""

from openai import OpenAIError

from aiogram.types import Message, FSInputFile
from aiogram import types

from src.utils.globals import bot, OWNER_TG_ID


async def send_error_alert(
    error: Exception, func: function, args: list, kwargs: dict, messages: list
) -> Message:
    """Send Telegram message with error context to the owner's chat.

    Args:
        error: original error object;
        func: function object in which the error occurred;
        args: positional arguments of the function;
        kwargs: named arguments of the function;
        messages: list of previous messages of the user.
    """
    err_record = f"ERROR: {error}\n\n\n \
            FUNCTION: {func}\n\n\n \
            ARGS: {args}\n\n\n \
            KWARGS: {kwargs}\n\n\n \
            PREVIOUS MESSAGES: {messages}"
    path_to_file = "src/utils/temp/documents/unexpected_error.txt"
    with open(path_to_file, "w") as f:
        f.write(err_record)
    return await bot.send_document(OWNER_TG_ID, FSInputFile(path_to_file))


def logged(f):
    """Decorator for async wrapper that catches Exceptions in a function provided."""

    async def wrap(*args, **kwargs):
        """Write errors in a txt file and send them to the bot owner via Telegram."""
        try:
            result = await f(*args, **kwargs)
            return result
        except (Exception, OpenAIError) as e:
            from src.templates.keyboards.inline_kbd import inline_kbd
            from src.database.queries import db_execute
            from src.utils.validations import language

            try:
                alert = "_ERROR\\. Click the button below to see details\\._"
                for arg in args:
                    # If the function has Message or Callback object among its
                    # arguments, notify the user that faced the error.
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
            # Send error summary to the bot owner and pin it to the chat.
            alert = await send_error_alert(e, f.__name__, args, kwargs, messages)
            await bot.pin_chat_message(chat_id=OWNER_TG_ID, message_id=alert.message_id)

    return wrap
