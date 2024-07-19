"""Handlers of Telegram events caused by inline keyboards' buttons press"""

import re

from aiogram import Router, types, F
from aiogram.utils.chat_action import ChatActionSender
from aiogram.enums import InputMediaType
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile, LabeledPrice

import src.templates.tutorial.videos
from src.templates.scripts import scripts
from src.handlers.public_cmds import help_handler, forget_handler
from src.templates.keyboards.inline_kbd import inline_kbd
from src.core.image_generation import variate_image
from src.database.queries import db_update_user, db_get_user, db_execute
from src.utils.validations import language, tutorial_videos2ids
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
    """Handle "Draw similar images" button's press.

    The button belongs to the image, generated by DALLE using /draw command.
    After the press, two similar images are generated with DALLE-2 variation
    feature and sent to the user. This images are not added to GPT-4o context!
    """
    message = callback.message
    file_name = f"src/utils/temp/images/{callback.from_user.id}"
    async with ChatActionSender.upload_photo(message.chat.id, bot):
        await bot.download(message.photo[-1], destination=file_name + ".jpg")
        media = await variate_image(file_name)
    await bot.send_media_group(message.chat.id, media)
    user = await db_get_user(callback.from_user.id)
    user["balance"] -= 2 * DALLE2_USD
    await db_update_user(user)
    await callback.answer()


@rt.callback_query(F.data == "error")
async def error_callback(callback: types.CallbackQuery):
    """Handle "What now?" button's press.

    The button belongs to the message that indicate user of an unexpected error.
    It should calm down the user and clean the chat context.
    """
    await callback.message.answer(
        format_tg_msg(scripts["err"]["unexpected err"][language(callback)]),
        reply_markup=inline_kbd({"hide": "hide"}, language(callback)),
    )
    await forget_handler(callback)
    await callback.answer()


@rt.callback_query(F.data == "balance")
async def balance_callback(callback: types.CallbackQuery):
    """Handle "Your balance & payment" button's press.

    The button belongs to the /help message. After press message's content and keyboard
    are edited in agreement with /balance command message.
    """
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
    # Add payment button.
    builder.row(mid_button)
    # Add buttons that reference other tutorial messages.
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
    """Handle "What are tokens?" button's press.

    There are two type of buttons with this text:
     - Buttons in one of the /help message's pages (callback data: "tokens");
     - Buttons in other places (callback data: "sep tokens");
    The first category of buttons requires message content to be edited, while
    the second requires a new message to be sent with the same content as messages
    from the first category, but with "Hide" inline keyboard.
    """
    if src.templates.tutorial.videos.videos is None:
        await tutorial_videos2ids()
    message = callback.message
    text = format_tg_msg(scripts["doc"]["tokens"][language(callback)])
    # The message content must be substituted with a new one.
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
    # A new message with "Hide" button must be sent.
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
    """Handle movement between /help menu pages.

     The button should update the message's content with corresponding tutorial page's
     content. The structure of /help menu pages (sometimes referred as tutorial) and
     connections between them is as following:

                          (prompts)  (gener.)    (recogn.)  (LaTeX)
    tokens <-> balance <-> help-0 <-> help-1 <-> help-2 <-> help-3 ---> balance <-> tokens

    Where arrow means that the pages are connected via inline keyboard buttons.
    """
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


@rt.callback_query(F.data == "send help")
async def send_help_callback(callback):
    """Handle /help button's press on non-help messages.

    The button sends new message with /help menu.
    """
    await help_handler(callback)
    await callback.answer()


@rt.callback_query(F.data.startswith("latex-"))
async def latex_callback(callback: types.CallbackQuery):
    """Handle "#x" button's press in message with LaTeX formulas.

    Each button has a corresponding LaTeX formula in the message's text. Callback
    includes number of formula that must be processed. The button must result in
    formula being converted into an image and sent back to the user as a new
    message with a "Hide" inline button.
    """
    # Get index of the formula in the Telegram message, not in the whole response.
    # If the message was cut in to pieces, this will find an index of a formula
    # in the particular piece.
    f_i = int(callback.data.split("-")[1])
    # Obtain i'th formula from the text.
    f = [f for f in find_latex(callback.message.text) if latex_significant(f)][f_i]
    image_url = latex2url(f)
    local_path = f"src/utils/temp/images/{callback.from_user.id}.jpg"
    # Telegram does not support svg format for images so the formula must be
    # converted from svg to jpg format.
    svg2jpg(image_url, local_path)
    photo = FSInputFile(local_path)
    kbd = inline_kbd({"hide": "hide"}, language(callback))
    # Get index of the formula among all other formulas in the response.
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
    """Handle "Hide" button's press - delete the message if less than 48h passed."""
    message = callback.message
    deleted = await bot.delete_message(message.chat.id, message.message_id)
    if not deleted:
        # Telegram does not allow deleting messages that were sent more than 48
        # hours ago. The user will be notified about this.
        await callback.answer(scripts["err"]["too old to hide"][language(callback)])
    await callback.answer()


@rt.callback_query(F.data.startswith("try payment"))
async def try_payment_callback(callback):
    """Handle "Pay ⭐X" button's press.

    If amount is not specified at the end of the callback data, invoice for ⭐1 is sent.
    """
    if callback.data == "try payment":
        amount = 1
    else:
        amount = int(callback.data.split()[-1])
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
    """Handle "Send as file" button's press.

    The button belongs to the message that is sent when the response is longer
    than 4096 characters which resulted in Telegram messages being split into pieces.
    After button press the response is saved in txt file and sent to the user.
    """
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
        # If all messages are cleaned from memory, the user will be notified.
        await callback.answer(scripts["err"]["nothing to convert"][language(callback)])
