"""GPT-4o API usage for text completion"""

import asyncio

from aiogram.types import Message, LinkPreviewOptions
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest

from src.templates.keyboards.inline_kbd import latex_inline_kbd, inline_kbd
from src.utils.analytics.logging import logged
from src.database.queries import (
    db_get_messages,
    db_get_model,
    db_execute,
)
from src.utils.validations import language
from src.utils.formatting import (
    nformulas_before,
    cut_tg_msg,
    format_tg_msg,
    send_template_answer,
)
from src.utils.globals import openai_client, bot, MAX_INCREMENT, MIN_INCREMENT


@logged
async def generate_completion(message: Message):
    """Wrapper over OpenAI's async streaming completion API call.

    Collect completion data and send it to user by editing the response multiple
    times after enough symbols is collected. If the resulted message is longer than
    4096 symbols (Telegram's restriction), split it into pieces and suggest to send
    the whole text at once as a txt file.

    Returns:
        tuple[response, usage, last_msg], where
            response - non-formatted completion text;
            usage - OpenAI's usage object containing number of tokens used;
            last_msg - sent response's Message object;
    """
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    model = await db_get_model(message.from_user.id)
    # If a user's message was splitted by Telegram into pieces, some time to
    # receive and write those pieces into the database is needed.
    await asyncio.sleep(0.1)
    messages = await db_get_messages(message.from_user.id)
    await db_execute(
        "UPDATE messages SET pending = FALSE WHERE pending = TRUE AND from_user_id = %s;",
        message.from_user.id,
    )
    stream = await openai_client.chat.completions.create(
        model=model["model_name"],
        messages=messages,
        max_tokens=model["max_tokens"],
        temperature=model["temperature"],
        stream=True,
        stream_options={"include_usage": True},
    )
    # Completion text
    response = ""
    # Text available to be sent with the Telegram message. If a completion is
    # longer than 4096 symbols and is cut into pieces, it contains only the last
    # piece of it.
    par = ""
    # Length of a completion piece that the Telegram message will be updated with.
    # The first update (which results in Telegram message sending) happens right
    # after the streaming starts.
    msg_increment = 0
    # Current difference between text in Telegram message and collected response.
    # Is a subject to compare with msg_increment.
    delta = 0
    last_msg = None
    async for chunk in stream:
        usage = chunk.usage
        if chunk.choices and chunk.choices[0].delta.content is not None:
            response += chunk.choices[0].delta.content
            par += chunk.choices[0].delta.content
            delta += len(chunk.choices[0].delta.content)
            # If message is longer than 4096 chars, which is restricted, it is
            # cutted into to pieces, where par is guaranteed to be shorter than 4096.
            # If no cut happens, tail is None
            par, tail = cut_tg_msg(par)
            try:
                if tail is None and delta > msg_increment:
                    delta = 0
                    # First updates are performed frequently to provide smooth
                    # experience to the user. Then frequence of updates is slowly
                    # increases to the one that will not result in temporary block.
                    msg_increment = min(MAX_INCREMENT, MIN_INCREMENT + len(par) / 10)
                    if last_msg is None:
                        last_msg = await message.answer(
                            format_tg_msg(par),
                            link_preview_options=LinkPreviewOptions(is_disabled=True),
                        )
                    else:
                        last_msg = await last_msg.edit_text(format_tg_msg(par))
                # The completion was cut into pieces.
                elif tail is not None:
                    latex_kbd = latex_inline_kbd(par, nformulas_before(par, response))
                    last_msg = await last_msg.edit_text(format_tg_msg(par))
                    if latex_kbd is not None:
                        last_msg = await last_msg.edit_reply_markup(
                            reply_markup=latex_kbd
                        )
                    par = tail
                    delta = 0
                    last_msg = await message.answer(
                        format_tg_msg(par),
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
            except TelegramBadRequest as e:
                # Sometimes Telegram seems to have problems even with not that
                # frequent updates. The error should not bother the user though.
                if "is not modified" in e.message:
                    pass
    latex_kbd = latex_inline_kbd(par, nformulas_before(par, response))
    try:
        if last_msg is not None:
            last_msg = await last_msg.edit_text(format_tg_msg(par))
            if latex_kbd is not None:
                last_msg = await last_msg.edit_reply_markup(reply_markup=latex_kbd)
        else:
            last_msg = await message.answer(
                format_tg_msg(par),
                reply_markup=latex_kbd,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    except TelegramBadRequest as e:
        if "is not modified" in e.message:
            pass
    # If message has been cutted, suggest user to have is sent as a file.
    if len(response) != len(par):
        await send_template_answer(
            message,
            "info",
            "long message",
            reply_markup=inline_kbd(
                {"send as file": "send as file"}, language(message)
            ),
        )
    return response, usage, last_msg
