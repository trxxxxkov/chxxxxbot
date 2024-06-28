from openai import OpenAIError

from aiogram import Router, types
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.chat_action import ChatActionSender

import src.templates.media.videos
from src.templates.keyboards.reply_kbd import help_keyboard
from src.templates.keyboards.buttons import buttons
from src.templates.dialogs import dialogs
from src.templates.bot_menu import bot_menu
from src.templates.keyboards.inline_kbd import inline_kbd
from src.core.image_generation import generate_image
from src.core.chat_completion import generate_completion
from src.utils.formatting import send_template_answer, format
from src.utils.validations import (
    language,
    add_user,
    prompt_is_accepted,
    lock,
    template_videos2ids,
)
from src.database.queries import (
    db_get_user,
    db_execute,
    db_save_message,
    db_save_user,
    db_save_expenses,
    get_image_url,
    get_message_text,
)
from src.utils.globals import (
    bot,
    GPT4O_OUTPUT_1K,
    FEE,
    DALLE3_OUTPUT,
    GPT4O_INPUT_1K,
)


rt = Router()


@rt.message(Command("start"))
async def start_handler(message: Message) -> None:
    await bot.set_my_commands(
        [
            types.BotCommand(command=key, description=value)
            for key, value in bot_menu[language(message)].items()
        ]
    )
    await add_user(message)
    await send_template_answer(
        message,
        "start",
        message.from_user.first_name,
        reply_markup=help_keyboard,
    )
    if src.templates.media.videos.videos is None:
        await template_videos2ids()


@rt.message(Command("help"))
async def help_handler(message: Message) -> None:
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(
            text=buttons[language(message)]["balance"], callback_data="balance"
        ),
        types.InlineKeyboardButton(
            text=buttons[language(message)]["help"][1] + " ->", callback_data="help-1"
        ),
    )
    text = format(dialogs[language(message)]["help"][0])
    await bot.send_animation(
        message.chat.id,
        src.templates.media.videos.videos["help"][0],
        caption=text,
        reply_markup=builder.as_markup(),
    )


@rt.message(Command("forget", "clear"))
async def forget_handler(message: Message) -> None:
    await db_execute(
        "DELETE FROM messages WHERE from_user_id = %s;", message.from_user.id
    )
    await send_template_answer(message, "forget")


@rt.message(Command("balance"))
async def balance_handler(message: Message) -> None:
    kbd = inline_kbd({"back-to-help": "help-0", "tokens": "tokens"}, language(message))
    user = await db_get_user(message.from_user.id)
    text = format(
        dialogs[language(message)]["balance"].format(
            round(user["balance"], 4),
            round(87 * user["balance"], 2),
            round(user["balance"] / GPT4O_OUTPUT_1K * 1000),
        ),
    )
    text += format(dialogs[language(message)]["payment"].format(FEE))
    await bot.send_animation(
        message.chat.id,
        src.templates.media.videos.videos["balance"],
        caption=text,
        reply_markup=kbd,
    )


@rt.message(Command("draw"))
async def draw_handler(message: Message, command) -> None:
    if await prompt_is_accepted(message):
        await db_save_message(message, "user")
        try:
            if not command.args:
                await send_template_answer(message, "draw")
                return
            async with ChatActionSender.upload_photo(message.chat.id, bot):
                image_url = await generate_image(command.args)
            kbd = inline_kbd({"redraw": "redraw"}, language(message))
            msg = await bot.send_photo(message.chat.id, image_url, reply_markup=kbd)
            await db_execute(
                "INSERT INTO messages (message_id, from_user_id, text, image_url) VALUES (%s, %s, %s, %s);",
                [
                    msg.message_id,
                    message.from_user.id,
                    await get_message_text(msg),
                    await get_image_url(msg),
                ],
            )
            user = await db_get_user(message.from_user.id)
            user["balance"] -= FEE * DALLE3_OUTPUT
            await db_save_user(user)
        except (Exception, OpenAIError) as e:
            await send_template_answer(message, "block")
            await forget_handler(message)


@rt.message()
async def handler(message: Message) -> None:
    if await prompt_is_accepted(message):
        await db_save_message(message, "user")
        await lock(message.from_user.id)
        async with ChatActionSender.typing(message.chat.id, bot):
            response, usage, last_message = await generate_completion(message)
        await db_save_expenses(message, usage)
        await db_execute(
            "INSERT INTO messages \
                (message_id, from_user_id, role, text) \
                VALUES (%s, %s, %s, %s);",
            [
                last_message.message_id,
                message.from_user.id,
                "system",
                response,
            ],
        )
        user = await db_get_user(message.from_user.id)
        user["balance"] -= (
            (
                GPT4O_INPUT_1K * usage.prompt_tokens
                + GPT4O_OUTPUT_1K * usage.completion_tokens
            )
            * FEE
            / 1000
        )
        user["first_name"] = message.from_user.first_name
        user["last_name"] = message.from_user.last_name
        await db_save_user(user)
