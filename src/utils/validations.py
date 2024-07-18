import json
import time
import tiktoken

from aiogram.types import FSInputFile

import src.templates.tutorial.videos
from src.templates.keyboards.inline_kbd import empty_balance_kbd
from src.utils.analytics.logging import logged
from src.database.queries import db_execute
from src.utils.formatting import send_template_answer, format_tg_msg, get_message_text
from src.utils.globals import (
    bot,
    VISION_USD,
    GPT4O_IN_USD,
    GPT4O_OUT_USD,
    GPT_MEMORY_SEC,
    OWNER_TG_ID,
)


@logged
async def add_user(message):
    bot_users = await db_execute("SELECT id FROM users;")
    if not isinstance(bot_users, list):
        bot_users = [bot_users]
    if message.from_user.id not in [item["id"] for item in bot_users]:
        await db_execute(
            "INSERT INTO users (id, first_name, last_name, username, language) VALUES (%s, %s, %s, %s, %s)",
            [
                message.from_user.id,
                message.from_user.first_name,
                message.from_user.last_name,
                message.from_user.username,
                language(message),
            ],
        )
        await db_execute(
            "INSERT INTO models (user_id) VALUES (%s)",
            [message.from_user.id],
        )


def language(message):
    lang = message.from_user.language_code
    if lang is None or lang != "ru":
        lang = "en"
    return lang


def is_implemented(message):
    if message.pinned_message is not None:
        return False
    else:
        return True


def message_cost(message):
    cost = 0
    encoding = tiktoken.encoding_for_model("gpt-4o")
    if message.photo:
        cost += VISION_USD
    tokens = len(encoding.encode(get_message_text(message)))
    return cost + tokens * GPT4O_IN_USD


@logged
async def is_affordable(message):
    cost = message_cost(message)
    response = await db_execute(
        [
            "DELETE FROM messages WHERE timestamp < TO_TIMESTAMP(%s) and from_user_id = %s;",
            "SELECT tokens FROM messages WHERE from_user_id = %s;",
            "SELECT balance FROM users WHERE id = %s;",
        ],
        [
            [time.time() - GPT_MEMORY_SEC, message.from_user.id],
            [message.from_user.id],
            [message.from_user.id],
        ],
    )
    if isinstance(response, list):
        cost += GPT4O_OUT_USD * sum(item.get("tokens", 0) for item in response[:-1])
        balance = response[-1].get("balance", 0)
    else:
        balance = response.get("balance", 0)
    if balance >= cost * 1.5:
        return True
    else:
        await send_template_answer(
            message, "err", "balance is empty", reply_markup=empty_balance_kbd(message)
        )
        return False


@logged
async def authorized(message):
    if str(message.from_user.id) in [OWNER_TG_ID]:
        return True
    else:
        await send_template_answer(message, "err", "not privileged")
        return False


@logged
async def template_videos2ids():
    hvid0 = await bot.send_animation(
        OWNER_TG_ID, FSInputFile("src/templates/tutorial/prompt.mp4")
    )
    hvid1 = await bot.send_animation(
        OWNER_TG_ID,
        FSInputFile("src/templates/tutorial/recognition.mp4"),
    )
    hvid2 = await bot.send_animation(
        OWNER_TG_ID,
        FSInputFile("src/templates//tutorial/generation.mp4"),
    )
    hvid3 = await bot.send_animation(
        OWNER_TG_ID, FSInputFile("src/templates/tutorial/latex.mp4")
    )
    tokens_vid = await bot.send_animation(
        OWNER_TG_ID, FSInputFile("src/templates/tutorial/tokens.mp4")
    )
    await bot.send_message(
        chat_id=OWNER_TG_ID,
        text=format_tg_msg("_The tutorial videos are successfully uploaded._"),
    )
    src.templates.tutorial.videos.videos = {
        "help": [
            hvid0.video.file_id,
            hvid1.video.file_id,
            hvid2.video.file_id,
            hvid3.video.file_id,
        ],
        "balance": tokens_vid.video.file_id,
        "tokens": tokens_vid.video.file_id,
    }
    with open("src/templates/tutorial/videos.py", "w") as file:
        file.write("videos = ")
        json.dump(src.templates.tutorial.videos.videos, file, indent=4)
