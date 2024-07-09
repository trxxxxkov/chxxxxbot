from openai import OpenAIError

from aiogram import Router, types
from aiogram.types import Message, LabeledPrice
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.chat_action import ChatActionSender
from aiogram.exceptions import TelegramBadRequest

import src.templates.tutorial.videos
from src.templates.bot_menu import bot_menu
from src.templates.scripts import scripts
from src.templates.keyboards.inline_kbd import inline_kbd
from src.core.image_generation import generate_image
from src.core.chat_completion import generate_completion
from src.utils.formatting import (
    send_template_answer,
    format,
    xtr2usd,
    usd2tok,
)
from src.utils.validations import language, prompt_is_accepted, lock
from src.database.queries import (
    db_execute,
    db_save_message,
    db_update_user,
    db_save_expenses,
    db_get_user,
    db_get_purchase,
)
from src.utils.globals import bot, GPT4O_OUT_USD, DALLE3_USD, GPT4O_IN_USD


rt = Router()


@rt.message(Command("draw"))
async def draw_handler(message: Message, command) -> None:
    if await prompt_is_accepted(message):
        try:
            if not command.args:
                await send_template_answer(message, "doc", "draw")
                return
            await db_save_message(message, "user")
            async with ChatActionSender.upload_photo(message.chat.id, bot):
                image_url = await generate_image(command.args)
            kbd = inline_kbd({"redraw": "redraw"}, language(message))
            msg = await bot.send_photo(message.chat.id, image_url, reply_markup=kbd)
            await db_execute(
                "INSERT INTO messages (message_id, from_user_id, image_url) VALUES (%s, %s, %s);",
                [
                    msg.message_id,
                    message.from_user.id,
                    image_url,
                ],
            )
            user = await db_get_user(message.from_user.id)
            user["balance"] -= DALLE3_USD
            await db_update_user(user)
        except (Exception, OpenAIError) as e:
            await send_template_answer(message, "err", "policy block")
            await forget_handler(message)


@rt.message(Command("forget", "clear"))
async def forget_handler(message: Message) -> None:
    await db_execute(
        "DELETE FROM messages WHERE from_user_id = %s;", message.from_user.id
    )
    await send_template_answer(message, "info", "forget success")


@rt.message(Command("balance"))
async def balance_handler(message: Message) -> None:
    builder = InlineKeyboardBuilder()
    mid_button = types.InlineKeyboardButton(
        text=scripts["bttn"]["try payment"][language(message)],
        callback_data=f"try payment",
    )
    builder.row(mid_button)
    builder.row(
        types.InlineKeyboardButton(
            text=scripts["bttn"]["back to help"][language(message)],
            callback_data="help-0",
        ),
        types.InlineKeyboardButton(
            text=scripts["bttn"]["to tokens"][language(message)] + " ->",
            callback_data="tokens",
        ),
    )
    user = await db_get_user(message.from_user.id)
    text = format(
        scripts["doc"]["payment"][language(message)].format(usd2tok(user["balance"]))
    )
    await bot.send_animation(
        message.chat.id,
        src.templates.tutorial.videos.videos["tokens"],
        caption=text,
        reply_markup=builder.as_markup(),
    )


@rt.message(Command("pay"))
async def pay_handler(message: Message, command) -> None:
    if (
        command.args is None
        or not command.args.isdigit()
        or not 1 <= int(command.args) <= 2500
    ):
        await send_template_answer(message, "doc", "pay")
    else:
        amount = int(command.args)
        prices = [LabeledPrice(label="XTR", amount=amount)]
        kbd = (
            InlineKeyboardBuilder()
            .add(
                types.InlineKeyboardButton(
                    text=scripts["bttn"]["pay"][language(message)].format(amount),
                    pay=True,
                ),
                types.InlineKeyboardButton(
                    text=scripts["bttn"]["to tokens"][language(message)],
                    callback_data="sep tokens",
                ),
            )
            .as_markup()
        )
        await bot.send_invoice(
            chat_id=message.chat.id,
            title=scripts["other"]["payment title"][language(message)],
            description=scripts["doc"]["payment description"][language(message)].format(
                usd2tok(xtr2usd(amount))
            ),
            payload=f"{message.from_user.id} {amount}",
            currency="XTR",
            prices=prices,
            reply_markup=kbd,
        )


@rt.message(Command("refund"))
async def refund_handler(message: Message, command) -> None:
    purchase_id = command.args
    if purchase_id is None:
        await send_template_answer(message, "doc", "refund")
    else:
        purchase = await db_get_purchase(purchase_id)
        user = await db_get_user(message.from_user.id)
        if purchase:
            if user["balance"] < xtr2usd(purchase["amount"]):
                await send_template_answer(message, "err", "invalid purchase id")
                return
            try:
                result = await bot.refund_star_payment(
                    user_id=message.from_user.id, telegram_payment_charge_id=purchase_id
                )
                if result:
                    await db_execute(
                        [
                            "UPDATE users SET balance = %s WHERE id = %s;",
                            "UPDATE purchases SET refunded = True WHERE id = %s;",
                        ],
                        [
                            [
                                user["balance"] - xtr2usd(purchase["amount"]),
                                user["id"],
                            ],
                            [purchase["id"]],
                        ],
                    )
            except TelegramBadRequest as e:
                if "CHARGE_ALREADY_REFUNDED" in e.message:
                    await send_template_answer(message, "err", "already refunded")
                else:
                    await send_template_answer(message, "err", "invalid purchase id")
        else:
            await send_template_answer(message, "err", "refund expired")


@rt.message(Command("help"))
async def help_handler(message: Message) -> None:
    builder = InlineKeyboardBuilder()
    mid_button = types.InlineKeyboardButton(
        text=scripts["bttn"]["try help"][0][language(message)],
        callback_data=f"try help-{0}",
    )
    builder.row(mid_button)
    builder.row(
        types.InlineKeyboardButton(
            text=scripts["bttn"]["to balance"][language(message)],
            callback_data="balance",
        ),
        types.InlineKeyboardButton(
            text=scripts["bttn"]["to help"][1][language(message)] + " ->",
            callback_data="help-1",
        ),
    )
    text = format(scripts["doc"]["help"][0][language(message)])
    await bot.send_animation(
        message.chat.id,
        src.templates.tutorial.videos.videos["help"][0],
        caption=text,
        reply_markup=builder.as_markup(),
    )


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
            GPT4O_IN_USD * usage.prompt_tokens + GPT4O_OUT_USD * usage.completion_tokens
        )
        user["first_name"] = message.from_user.first_name
        user["last_name"] = message.from_user.last_name
        user["language"] = language(message)
        await bot.set_my_commands(
            [
                types.BotCommand(command=key, description=value[language(message)])
                for key, value in bot_menu.items()
            ]
        )
        await db_update_user(user)
