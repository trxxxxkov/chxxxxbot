from openai import OpenAIError

from aiogram import Router, types
from aiogram.types import Message, LabeledPrice
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.chat_action import ChatActionSender
from aiogram.exceptions import TelegramBadRequest

import src.templates.tutorial_vids.videos
from src.templates.keyboards.buttons import buttons
from src.templates.dialogs import dialogs
from src.templates.keyboards.inline_kbd import inline_kbd
from src.core.image_generation import generate_image
from src.core.chat_completion import generate_completion
from src.utils.formatting import send_template_answer, format
from src.utils.validations import language, prompt_is_accepted, lock
from src.database.queries import (
    db_execute,
    db_save_message,
    db_update_user,
    db_save_expenses,
    db_get_user,
    db_get_purchase,
)
from src.utils.globals import (
    bot,
    GPT4O_OUTPUT_1K,
    FEE,
    DALLE3_OUTPUT,
    GPT4O_INPUT_1K,
    XTR2USD_COEF,
)


rt = Router()


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
                "INSERT INTO messages (message_id, from_user_id, image_url) VALUES (%s, %s, %s);",
                [
                    msg.message_id,
                    message.from_user.id,
                    image_url,
                ],
            )
            user = await db_get_user(message.from_user.id)
            user["balance"] -= FEE * DALLE3_OUTPUT
            await db_update_user(user)
        except (Exception, OpenAIError) as e:
            await send_template_answer(message, "block")
            await forget_handler(message)


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
            round(user["balance"] / FEE / GPT4O_INPUT_1K * 1000),
            round(user["balance"], 4),
        ),
    )
    text += format(dialogs[language(message)]["payment"].format(FEE))
    await bot.send_animation(
        message.chat.id,
        src.templates.tutorial_vids.videos.videos["balance"],
        caption=text,
        reply_markup=kbd,
    )


@rt.message(Command("donate"))
async def donate_handler(message: Message, command) -> None:
    if (
        command.args is None
        or not command.args.isdigit()
        or not 1 <= int(command.args) <= 2500
    ):
        await send_template_answer(message, "donate")
    else:
        amount = int(command.args)
        prices = [LabeledPrice(label="XTR", amount=amount)]
        kbd = (
            InlineKeyboardBuilder()
            .add(
                types.InlineKeyboardButton(
                    text=buttons[language(message)]["donate"].format(amount), pay=True
                )
            )
            .as_markup()
        )
        await bot.send_invoice(
            chat_id=message.chat.id,
            title=dialogs[language(message)]["donate-title"],
            description=dialogs[language(message)]["donate-description"].format(
                round(XTR2USD_COEF * amount / FEE / GPT4O_INPUT_1K * 1000),
                round(XTR2USD_COEF * amount, 4),
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
        await send_template_answer(message, "refund")
    else:
        purchase = await db_get_purchase(purchase_id)
        user = await db_get_user(message.from_user.id)
        if purchase and user["balance"] >= purchase["amount"] * XTR2USD_COEF:
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
                                user["balance"] - purchase["amount"] * XTR2USD_COEF,
                                user["id"],
                            ],
                            [purchase["id"]],
                        ],
                    )
            except TelegramBadRequest as e:
                if "CHARGE_ALREADY_REFUNDED" in e.message:
                    text = "refund already refunded"
                else:
                    text = "refund not found"
                await bot.send_message(message.chat.id, text)
        else:
            await bot.send_message(message.chat.id, "refund expired")


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
        src.templates.tutorial_vids.videos.videos["help"][0],
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
            (
                GPT4O_INPUT_1K * usage.prompt_tokens
                + GPT4O_OUTPUT_1K * usage.completion_tokens
            )
            * FEE
            / 1000
        )
        user["first_name"] = message.from_user.first_name
        user["last_name"] = message.from_user.last_name
        await db_update_user(user)
