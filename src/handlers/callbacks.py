import re

from aiogram import Router, types, F
from aiogram.utils.chat_action import ChatActionSender
from aiogram.enums import InputMediaType
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile

import src.templates.tutorial_vids.videos
from src.templates.scripts import scripts
from src.templates.keyboards.inline_kbd import inline_kbd
from src.core.image_generation import variate_image
from src.database.queries import db_update_user, db_get_user
from src.utils.validations import language
from src.utils.formatting import (
    find_latex,
    latex2url,
    svg_to_jpg,
    latex_significant,
    send,
    format,
)
from src.utils.globals import bot, FEE, DALLE2_OUTPUT, GPT4O_INPUT_1K


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
    user["balance"] -= 2 * FEE * DALLE2_OUTPUT
    await db_update_user(user)


@rt.callback_query(F.data == "error")
async def error_callback(callback: types.CallbackQuery):
    text = scripts["err"]["unexpected err"][language(callback)]
    await send(callback.message, text)
    await callback.answer()


@rt.callback_query(F.data == "balance")
async def balance_callback(callback: types.CallbackQuery):
    message = callback.message
    user = await db_get_user(callback.from_user.id)
    text = format(
        scripts["doc"]["balance"][language(callback)].format(
            round(user["balance"] / FEE / GPT4O_INPUT_1K * 1000),
            round(user["balance"], 4),
        )
    )
    text += format(scripts["doc"]["payment"][language(message)].format(FEE))
    kbd = inline_kbd(
        {"back to help": "help-0", "to tokens": "tokens"}, language(message)
    )
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=src.templates.tutorial_vids.videos.videos["balance"],
            caption=text,
        ),
        chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=kbd,
    )
    await callback.answer()


@rt.callback_query(F.data == "tokens")
async def tokens_callback(callback: types.CallbackQuery):
    message = callback.message
    text = format(scripts["doc"]["tokens"][language(callback)])
    kbd = inline_kbd({"to balance": "balance"}, language(message))
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=src.templates.tutorial_vids.videos.videos["tokens"],
            caption=text,
        ),
        chat_id=message.chat.id,
        message_id=message.message_id,
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
    builder.add(l_button, r_button)
    text = format(scripts["doc"]["help"][h_idx][language(callback)])
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=src.templates.tutorial_vids.videos.videos["help"][h_idx],
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
    svg_to_jpg(image_url, local_path)
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
        text = format(scripts["err"]["too old to hide"][language(callback)])
        await bot.send_message(
            message.chat.id, text, reply_to_message_id=message.message_id
        )
    await callback.answer()
