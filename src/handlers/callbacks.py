import asyncio
import re

from aiogram import Router, types, F
from aiogram.utils.chat_action import ChatActionSender
from aiogram.enums import InputMediaType
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile, LabeledPrice

import src.templates.tutorial.videos
from src.templates.scripts import scripts
from src.templates.keyboards.inline_kbd import inline_kbd
from src.core.image_generation import variate_image
from src.database.queries import db_update_user, db_get_user, db_execute
from src.utils.validations import language, template_videos2ids
from src.utils.formatting import (
    find_latex,
    latex2url,
    svg2jpg,
    latex_significant,
    format_tg_msg,
    usd2tok,
    xtr2usd,
)
from src.utils.globals import bot, DALLE2_USD


rt = Router()


@rt.callback_query(F.data == "redraw")
async def redraw_callback(callback: types.CallbackQuery):
    message = callback.message
    file_name = f"src/utils/temp/images/{callback.from_user.id}"
    async with ChatActionSender.upload_photo(message.chat.id, bot):
        await bot.download(message.photo[-1], destination=file_name + ".jpg")
        media = await variate_image(file_name)
    await bot.send_media_group(message.chat.id, media)
    user = await db_get_user(callback.from_user.id)
    user["balance"] -= 2 * DALLE2_USD
    await db_update_user(user)


@rt.callback_query(F.data == "error")
async def error_callback(callback: types.CallbackQuery):
    await callback.message.answer(
        format_tg_msg(scripts["err"]["unexpected err"][language(callback)]),
        reply_markup=inline_kbd({"hide": "hide"}, language(callback)),
    )
    await callback.answer()


@rt.callback_query(F.data == "balance")
async def balance_callback(callback: types.CallbackQuery):
    message = callback.message
    user = await db_get_user(callback.from_user.id)
    text = format_tg_msg(
        scripts["doc"]["payment"][language(callback)].format(
            usd2tok(user["balance"]), usd2tok(xtr2usd(1))
        )
    )
    builder = InlineKeyboardBuilder()
    mid_button = types.InlineKeyboardButton(
        text=scripts["bttn"]["try payment"][language(callback)],
        callback_data=f"try payment",
    )
    builder.row(mid_button)
    builder.row(
        types.InlineKeyboardButton(
            text=scripts["bttn"]["back to help"][language(callback)],
            callback_data="help-0",
        ),
        types.InlineKeyboardButton(
            text=scripts["bttn"]["to tokens"][language(callback)] + " ->",
            callback_data="tokens",
        ),
    )
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=src.templates.tutorial.videos.videos["tokens"],
            caption=text,
        ),
        chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@rt.callback_query(F.data.endswith("tokens"))
async def tokens_callback(callback: types.CallbackQuery):
    if src.templates.tutorial.videos.videos is None:
        await template_videos2ids()
    message = callback.message
    text = format_tg_msg(scripts["doc"]["tokens"][language(callback)])
    if callback.data == "tokens":
        kbd = inline_kbd({"to balance": "balance"}, language(message))
        await bot.edit_message_media(
            types.InputMediaAnimation(
                type=InputMediaType.ANIMATION,
                media=src.templates.tutorial.videos.videos["tokens"],
                caption=text,
            ),
            chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=kbd,
        )
    elif callback.data == "sep tokens":
        kbd = inline_kbd({"hide": "hide"}, language(callback))
        await bot.send_animation(
            message.chat.id,
            src.templates.tutorial.videos.videos["tokens"],
            caption=text,
            reply_markup=kbd,
        )
        await callback.answer()


@rt.callback_query(F.data.startswith("help-"))
async def help_callback(callback: types.CallbackQuery):
    message = callback.message
    h_idx = int(callback.data.split("-")[1])
    payment_button = types.InlineKeyboardButton(
        text=scripts["bttn"]["to balance"][language(callback)], callback_data="balance"
    )
    if h_idx == 0:
        l_button = payment_button
    else:
        l_button = types.InlineKeyboardButton(
            text="<- " + scripts["bttn"]["to help"][h_idx - 1][language(callback)],
            callback_data=f"help-{h_idx-1}",
        )
    if h_idx == len(scripts["bttn"]["to help"]) - 1:
        r_button = payment_button
    else:
        r_button = types.InlineKeyboardButton(
            text=scripts["bttn"]["to help"][h_idx + 1][language(callback)] + " ->",
            callback_data=f"help-{h_idx+1}",
        )
    builder = InlineKeyboardBuilder()
    builder.row(l_button, r_button)
    text = format_tg_msg(scripts["doc"]["help"][h_idx][language(callback)])
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=src.templates.tutorial.videos.videos["help"][h_idx],
            caption=text,
        ),
        chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@rt.callback_query(F.data.startswith("latex-"))
async def latex_callback(callback: types.CallbackQuery):
    f_i = int(callback.data.split("-")[1])
    f = [f for f in find_latex(callback.message.text) if latex_significant(f)][f_i]
    image_url = latex2url(f)
    local_path = f"src/utils/temp/images/{callback.from_user.id}.jpg"
    svg2jpg(image_url, local_path)
    photo = FSInputFile(local_path)
    kbd = inline_kbd({"hide": "hide"}, language(callback))
    f_idx = re.findall(r"(?<=#)\d\d?(?=:\n)", callback.message.text)[f_i]
    await bot.send_photo(
        callback.from_user.id,
        photo,
        reply_to_message_id=callback.message.message_id,
        reply_parameters=types.ReplyParameters(
            message_id=callback.message.message_id, quote=f"*\\#{f_idx}:*"
        ),
        reply_markup=kbd,
    )
    await callback.answer()


@rt.callback_query(F.data == "hide")
async def hide_callback(callback: types.CallbackQuery):
    message = callback.message
    deleted = await bot.delete_message(message.chat.id, message.message_id)
    if not deleted:
        await callback.answer(scripts["err"]["too old to hide"][language(callback)])
    await callback.answer()


@rt.callback_query(F.data == "try payment")
async def try_payment_callback(callback):
    amount = 1
    prices = [LabeledPrice(label="XTR", amount=amount)]
    kbd = (
        InlineKeyboardBuilder()
        .add(
            types.InlineKeyboardButton(
                text=scripts["bttn"]["pay"][language(callback)].format(amount),
                pay=True,
            ),
            types.InlineKeyboardButton(
                text=scripts["bttn"]["to tokens"][language(callback)],
                callback_data="sep tokens",
            ),
        )
        .as_markup()
    )
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=scripts["other"]["payment title"][language(callback)],
        description=scripts["doc"]["payment description"][language(callback)].format(
            usd2tok(xtr2usd(amount))
        ),
        payload=f"{callback.from_user.id} {amount}",
        currency="XTR",
        prices=prices,
        reply_markup=kbd,
    )
    await callback.answer()


@rt.callback_query(F.data == "send as file")
async def as_file_handler(callback) -> None:
    messages = await db_execute(
        "SELECT * FROM messages WHERE from_user_id = %s ORDER BY timestamp;",
        callback.from_user.id,
    )
    if messages and isinstance(messages, list):
        last_msg = messages[-1]
        prompt = messages[-2]
        path_to_file = f"src/utils/temp/documents/{callback.from_user.id}-as_file.txt"
        with open(path_to_file, "w") as f:
            f.write(last_msg["text"])
        await bot.send_document(
            callback.message.chat.id,
            FSInputFile(path_to_file),
            reply_to_message_id=prompt["message_id"],
        )
        await callback.answer()
    else:
        await callback.answer(scripts["err"]["nothing to convert"][language(callback)])
