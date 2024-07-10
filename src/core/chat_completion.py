from aiogram.enums import ChatAction

from src.templates.keyboards.inline_kbd import latex_inline_kbd, inline_kbd
from src.utils.analytics.logging import logged
from src.database.queries import db_get_messages, db_get_model
from src.utils.validations import language
from src.utils.formatting import (
    nformulas_before,
    cut_tg_msg,
    format_tg_msg,
    send_template_answer,
)
from src.utils.globals import openai_client, bot


@logged
async def generate_completion(message):
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    model = await db_get_model(message.from_user.id)
    messages = await db_get_messages(message.from_user.id)
    stream = await openai_client.chat.completions.create(
        model=model["model_name"],
        messages=messages,
        max_tokens=model["max_tokens"],
        temperature=model["temperature"],
        stream=True,
        stream_options={"include_usage": True},
    )
    response = ""
    par = ""
    sended_chunk_size = 40
    delta = 0
    last_msg = None
    async for chunk in stream:
        usage = chunk.usage
        if chunk.choices and chunk.choices[0].delta.content is not None:
            response += chunk.choices[0].delta.content
            par += chunk.choices[0].delta.content
            delta += len(chunk.choices[0].delta.content)
            par, tail = cut_tg_msg(par)
            if tail is None and delta > sended_chunk_size:
                delta = 0
                sended_chunk_size = 100
                if last_msg is None:
                    last_msg = await message.answer(format_tg_msg(par))
                else:
                    last_msg = await last_msg.edit_text(format_tg_msg(par))
            elif tail is not None:
                latex_kbd = latex_inline_kbd(par, nformulas_before(par, response))
                last_msg = await last_msg.edit_text(format_tg_msg(par))
                if latex_kbd is not None:
                    last_msg = await last_msg.edit_reply_markup(reply_markup=latex_kbd)
                par = tail
                delta = 0
                last_msg = await message.answer(format_tg_msg(par))
    latex_kbd = latex_inline_kbd(par, nformulas_before(par, response))
    if last_msg is not None:
        last_msg = await last_msg.edit_text(format_tg_msg(par))
        if latex_kbd is not None:
            last_msg = await last_msg.edit_reply_markup(reply_markup=latex_kbd)
    else:
        last_msg = await message.answer(format_tg_msg(par), reply_markup=latex_kbd)
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
