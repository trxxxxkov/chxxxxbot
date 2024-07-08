import json
import time
import asyncio
import tiktoken

from aiogram.types import FSInputFile

import src.templates.tutorial_vids.videos
from src.templates.scripts import scripts
from src.utils.analytics.logging import logged
from src.database.queries import (
    db_execute,
    db_get_user,
    db_update_user,
    db_get_messages,
)
from src.utils.formatting import send_template_answer
from src.utils.globals import bot, FEE, GPT4O_INPUT_1K, GPT_MEMORY_SEC, OWNER_CHAT_ID


@logged
async def add_user(message):
    bot_users = await db_execute("SELECT id FROM users;")
    if not isinstance(bot_users, list):
        bot_users = [bot_users]
    if message.from_user.id not in [item["id"] for item in bot_users]:
        await db_execute(
            "INSERT INTO users (id, first_name, last_name) VALUES (%s, %s, %s)",
            [
                message.from_user.id,
                message.from_user.first_name,
                message.from_user.last_name,
            ],
        )
        await db_execute(
            "INSERT INTO models (user_id) VALUES (%s)",
            [message.from_user.id],
        )


@logged
async def lock(user_id):
    user = await db_get_user(user_id)
    user["lock"] = True
    await db_update_user(user)
    await asyncio.sleep(0.6)
    user = await db_get_user(user_id)
    user["lock"] = False
    await db_update_user(user)


@logged
async def balance_is_sufficient(message) -> bool:
    message_cost = 0
    encoding = tiktoken.encoding_for_model("gpt-4o")
    if message.photo:
        pre_prompt = scripts["other"]["vision pre-prompt"][language(message)]
        text = message.caption if message.caption else pre_prompt
        message_cost += FEE * GPT4O_INPUT_1K
    else:
        text = message.text
    old_messages = await db_get_messages(message.from_user.id)
    for old_message in old_messages:
        if isinstance(old_message["content"], str):
            text += old_message["content"]
        elif old_message["content"][0]["text"] is not None:
            text += old_message["content"][0]["text"]
            message_cost += FEE * GPT4O_INPUT_1K
    tokens = len(encoding.encode(text))
    message_cost += tokens * FEE * GPT4O_INPUT_1K / 1000
    user = await db_get_user(message.from_user.id)
    return user["balance"] >= 2 * message_cost


@logged
async def forget_outdated_messages(user_id):
    now = time.time()
    await db_execute(
        "DELETE FROM messages WHERE timestamp < TO_TIMESTAMP(%s);", now - GPT_MEMORY_SEC
    )


@logged
async def prompt_is_accepted(message) -> bool:
    if not await balance_is_sufficient(message):
        await send_template_answer(message, "err", "balance is empty")
        return False
    user = await db_get_user(message.from_user.id)
    if user["lock"]:
        return False
    else:
        await forget_outdated_messages(message.from_user.id)
        return True


def language(message):
    lang = message.from_user.language_code
    if lang is None or lang != "ru":
        lang = "en"
    return lang


@logged
async def authorized(message):
    if message.from_user.id == OWNER_CHAT_ID:
        return True
    else:
        await send_template_answer(message, "err", "not privileged")
        return False


@logged
async def template_videos2ids():
    hvid0 = await bot.send_animation(
        OWNER_CHAT_ID, FSInputFile("src/templates/tutorial_vids/prompt.mp4")
    )
    hvid1 = await bot.send_animation(
        OWNER_CHAT_ID,
        FSInputFile("src/templates/tutorial_vids/recognition.mp4"),
    )
    hvid2 = await bot.send_animation(
        OWNER_CHAT_ID,
        FSInputFile("src/templates//tutorial_vids/generation.mp4"),
    )
    hvid3 = await bot.send_animation(
        OWNER_CHAT_ID, FSInputFile("src/templates/tutorial_vids/latex.mp4")
    )
    balance_vid = await bot.send_animation(
        OWNER_CHAT_ID, FSInputFile("src/templates/tutorial_vids/balance.mp4")
    )
    tokens_vid = await bot.send_animation(
        OWNER_CHAT_ID, FSInputFile("src/templates/tutorial_vids/what_are_tokens.mp4")
    )
    src.templates.tutorial_vids.videos.videos = {
        "help": [
            hvid0.video.file_id,
            hvid1.video.file_id,
            hvid2.video.file_id,
            hvid3.video.file_id,
        ],
        "balance": balance_vid.video.file_id,
        "tokens": tokens_vid.video.file_id,
    }
    with open("src/templates/tutorial_vids/videos.py", "w") as file:
        file.write("videos = ")
        json.dump(src.templates.tutorial_vids.videos.videos, file, indent=4)
