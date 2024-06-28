from aiogram.enums import ChatAction

from src.templates.keyboards.reply_kbd import forget_keyboard
from src.utils.analytics.logging import logged
from src.database.queries import db_get_messages, db_get_model
from src.utils.formatting import is_incomplete, send, num_formulas_before, cut
from src.utils.globals import bot, openai_client, PAR_MIN_LEN


@logged
async def generate_completion(message):
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
    tail = ""
    async for chunk in stream:
        usage = chunk.usage
        if chunk.choices and chunk.choices[0].delta.content is not None:
            tail += chunk.choices[0].delta.content
            response += chunk.choices[0].delta.content
            if tail == response and "\n\n" in tail:
                if not is_incomplete(tail[: tail.rfind("\n\n")]):
                    delim = tail.rfind("\n\n")
                    head, tail = tail[:delim], tail[delim + 2 :]
                    await send(message, head, f_idx=0)
                    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
            if len(tail) > PAR_MIN_LEN and "\n" in chunk.choices[0].delta.content:
                head, tail = cut(tail)
                if head is not None:
                    await send(message, head, f_idx=num_formulas_before(head, response))
                    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    last_message = await send(
        message, tail, forget_keyboard, num_formulas_before(tail, response)
    )
    return response, usage, last_message
