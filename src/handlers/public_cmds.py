from openai import OpenAIError
import debugpy

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
    format_tg_msg,
    xtr2usd,
    usd2tok,
)
from src.utils.validations import (
    language,
    template_videos2ids,
    is_implemented,
    is_affordable,
    message_cost,
)
from src.database.queries import (
    db_execute,
    db_save_message,
    db_update_user,
    db_get_user,
    db_get_purchase,
)
from src.utils.globals import bot, GPT4O_OUT_USD, DALLE3_USD, GPT4O_IN_USD


rt = Router()
BUSY_USERS = set()


@rt.message(Command("draw"))
async def draw_handler(message: Message, command) -> None:
    if not command.args:
        await send_template_answer(message, "doc", "draw")
    else:
        if await is_affordable(message):
            await db_save_message(message, "user", False)
            try:
                async with ChatActionSender.upload_photo(message.chat.id, bot):
                    image_url = await generate_image(command.args)
                kbd = inline_kbd({"redraw": "redraw"}, language(message))
                msg = await bot.send_photo(message.chat.id, image_url, reply_markup=kbd)
                await db_execute(
                    "INSERT INTO messages (message_id, from_user_id, tokens, image_url, pending) \
                        VALUES (%s, %s, %s, %s, %s);",
                    [msg.message_id, message.from_user.id, 1000, image_url, False],
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
    BUSY_USERS.discard(message.from_user.id)
    await send_template_answer(message, "info", "forget success")


@rt.message(Command("balance"))
async def balance_handler(message: Message) -> None:
    if src.templates.tutorial.videos.videos is None:
        await template_videos2ids()
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
    text = format_tg_msg(
        scripts["doc"]["payment"][language(message)].format(
            usd2tok(user["balance"]), usd2tok(xtr2usd(1))
        )
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
        await send_template_answer(message, "doc", "pay", usd2tok(xtr2usd(1)))
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
    if src.templates.tutorial.videos.videos is None:
        await template_videos2ids()
    builder = InlineKeyboardBuilder()
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
    text = format_tg_msg(scripts["doc"]["help"][0][language(message)])
    await bot.send_animation(
        message.chat.id,
        src.templates.tutorial.videos.videos["help"][0],
        caption=text,
        reply_markup=builder.as_markup(),
    )


@rt.message()
async def handler(message: Message, *, recursive=False) -> None:
    if is_implemented(message) and await is_affordable(message):
        if not recursive:
            input_tokens = usd2tok(message_cost(message) + 2 * GPT4O_OUT_USD)
            await db_save_message(message, input_tokens, "user", True)
        if message.from_user.id in BUSY_USERS:
            return
        BUSY_USERS.add(message.from_user.id)
        try:
            response, usage, last_message = await generate_completion(message)
            await db_execute(
                "INSERT INTO messages \
                    (message_id, from_user_id, tokens, role, text) \
                    VALUES (%s, %s, %s, %s, %s);",
                [
                    last_message.message_id,
                    message.from_user.id,
                    usage.completion_tokens,
                    "system",
                    response,
                ],
            )
            user = await db_get_user(message.from_user.id)
            user["balance"] -= (
                GPT4O_IN_USD * usage.prompt_tokens
                + GPT4O_OUT_USD * usage.completion_tokens
            )
            user["first_name"] = message.from_user.first_name
            user["last_name"] = message.from_user.last_name
            user["username"] = message.from_user.username
            user["language"] = language(message)
            await db_update_user(user)
            BUSY_USERS.discard(message.from_user.id)
            pending = await db_execute(
                "SELECT message_id FROM messages WHERE pending = TRUE and from_user_id = %s;",
                message.from_user.id,
            )
            if pending:
                await handler(message, recursive=True)
            else:
                await bot.set_my_commands(
                    [
                        types.BotCommand(
                            command=key, description=value[language(message)]
                        )
                        for key, value in bot_menu.items()
                    ]
                )
        except Exception:
            BUSY_USERS.discard(message.from_user.id)
