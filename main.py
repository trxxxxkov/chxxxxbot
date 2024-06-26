import asyncio
import logging
import sys
import json
import time
import os
import base64
import tiktoken
import cairosvg
import urllib.parse
import re

import psycopg
from psycopg.rows import dict_row

from mimetypes import guess_type
from dotenv import load_dotenv
from os import getenv
from PIL import Image
from openai import AsyncOpenAI, OpenAIError

from aiohttp import web

from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, InputMediaType, ChatAction
from aiogram.filters import Command
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import Message, InputMediaPhoto, FSInputFile
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


import keyboards
from dialogues import dialogues
from commands import commands
from videos import videos
from buttons import buttons

load_dotenv()

WEB_SERVER_HOST = "127.0.0.1"
WEB_SERVER_PORT = 8080
WEBHOOK_PATH = "/var/www/chxxxxbot"
WEBHOOK_SECRET = "mysecret"
BASE_WEBHOOK_URL = "https://trxxxxkov.net"

IMAGES_PATH = "images"

OWNER_CHAT_ID = 791388236
BOT_TOKEN = getenv("TG_BOT_TOKEN")
OPENAI_KEY = getenv("OPENAI_API_KEY")
DATABASE_PASSWORD = getenv("POSTGRESQL_DB_PASSWORD")
DATABASE_NAME = getenv("POSTGRESQL_DB_NAME")
DATABASE_USER = getenv("POSTGRESQL_DB_USER")
DATABASE_HOST = "localhost"
DATABASE_PORT = "5432"
DSN = f"host={DATABASE_HOST} \
        port={DATABASE_PORT} \
        dbname={DATABASE_NAME} \
        user={DATABASE_USER} \
        password={DATABASE_PASSWORD}"
# OPENAI API prices per 1K tokens
FEE = 1.6
GPT_MEMORY_SEC = 7200
GPT_MODEL = "gpt-4o"
GPT4O_INPUT_1K = 0.005
GPT4O_OUTPUT_1K = 0.015
DALLE3_OUTPUT = 0.08
DALLE2_OUTPUT = 0.02

PAR_MIN_LEN = 500
PAR_MAX_LEN = 3950

INITIAL_USER_DATA = {
    "balance": 0,
    "lock": False,
    "timestamps": [],
    "messages": [],
}

CODE_PATTERN = re.compile(
    r"(?<!`|\w)(?<!\\)```\S*?\n(?:(?:.|\n)*?\S(?:.|\n)*?)(?:\s+)```(?!`|\w)"
)
PRE_PATTERN = re.compile(
    r"(?<!`|\w)(?<!\\)`(?:(?:[^`])|(?:[^`]*?\\`[^`]*?))*?(?<!\\)`(?!`|\w)"
)
CODE_AND_PRE_PATTERN = re.compile(
    rf"(?:{PRE_PATTERN.pattern})|(?:{CODE_PATTERN.pattern})"
)
ESCAPED_IN_C_DEFAULT = re.compile(r"(?<!\\)[\\`]")
ESCAPED_IN_O_DEFAULT = re.compile(r"(?<!\\)[\\[\]()`#+-={}.!]")
ESCAPED_IN_O_TIGHT = re.compile(r"(?<=\w)(?<!_)[*_~|](?!_)(?=\w)")
ESCAPED_IN_O_QUOTE = re.compile(r"(?<!\n)(?<!\A)(?<!\\)>")
ESCAPED_IN_O_SINGLE = re.compile(r"(?<!\|)(?<!\\)\|(?!\|)")
LATEX_PATTERN = re.compile(
    r"(?:\$\$|\\\[|\\\(|\\begin\{\w+\*?\})(?:.|\n)*?(?:\$\$|\\\]|\\\)|\\end\{\w+\*?\})"
)
LATEX_BODY_PATTERN = re.compile(
    r"(?:\$\$|\\\[|\\\(|\\begin\{\w+\*?\})((?:.|\n)*?)(?:\$\$|\\\]|\\\)|\\end\{\w+\*?\})"
)
INCOMPLETE_CODE_PATTERN = re.compile(
    rf"(?:(?:{CODE_PATTERN.pattern})|(?:[^`])|(?:``?)(?!`)|(?:````+)|(?<=\w|\\)```|```(?!\n)\s)*"
)

client = AsyncOpenAI(
    api_key=OPENAI_KEY,
    base_url="https://api.openai.com/v1",
)

dp = Dispatcher()


def write_error(error, func, args, kwargs, messages, path="errors.json"):
    with open(path, "r") as f:
        try:
            errors = json.load(f)
        except Exception:
            errors = list()
    errors.append(
        {
            "error": f"{error}",
            "function": f"{func}",
            "args": f"{args}",
            "kwargs": f"{kwargs}",
            "messages": f"{messages}",
        }
    )
    with open(path, "w") as f:
        json.dump(errors, f)


def logged(f):
    async def wrap(*args, **kwargs):
        try:
            result = await f(*args, **kwargs)
            return result
        except (Exception, OpenAIError) as e:
            alert = format(f"_ERROR: {e}_")
            await bot.send_message(OWNER_CHAT_ID, alert)
            messages = None
            try:
                for arg in args:
                    if isinstance(arg, Message):
                        kbd = inline_kbd({"error": "error"}, language(arg))
                        await bot.send_message(arg.chat.id, alert, reply_markup=kbd)
                        messages = await db_execute(
                            "SELECT * FROM messages WHERE from_user_id = %s",
                            arg.from_user.id,
                        )
                        await db_execute(
                            "DELETE FROM messages WHERE from_user_id = %s;",
                            arg.from_user.id,
                        )
                        break
                    elif isinstance(arg, types.CallbackQuery):
                        kbd = inline_kbd({"error": "error"}, language(arg))
                        await bot.send_message(
                            arg.from_user.id,
                            alert,
                            reply_markup=kbd,
                        )
                        messages = await db_execute(
                            "SELECT * FROM messages WHERE from_user_id = %s",
                            arg.from_user.id,
                        )
                        await db_execute(
                            "DELETE FROM messages WHERE from_user_id = %s;",
                            arg.from_user.id,
                        )
                        break
            except Exception:
                messages = "[unavailable because of an error in the logging function]"
            write_error(e, f.__name__, args, kwargs, messages)

    return wrap


# Function to encode a local image into data URL
def local_image_to_data_url(image_path):
    # Guess the MIME type of the image based on the file extension
    mime_type, _ = guess_type(image_path)
    if mime_type is None:
        mime_type = "application/octet-stream"  # Default MIME type if none is found

    # Read and encode the image file
    with open(image_path, "rb") as image_file:
        base64_encoded_data = base64.b64encode(image_file.read()).decode("utf-8")

    # Construct the data URL
    return f"data:{mime_type};base64,{base64_encoded_data}"


def svg_to_jpg(svg_file_path, output_file_path):
    cairosvg.svg2png(
        url=svg_file_path,
        write_to=output_file_path,
        output_width=512,
        output_height=128,
    )


def inline_kbd(keys, lang=None):
    keyboard = InlineKeyboardBuilder()
    if lang is not None:
        for button, callback in keys.items():
            keyboard.add(
                types.InlineKeyboardButton(
                    text=buttons[lang][button], callback_data=callback
                ),
            )
    else:
        for button, callback in keys.items():
            keyboard.add(
                types.InlineKeyboardButton(text=button, callback_data=callback),
            )
    return keyboard.as_markup()


async def generate_image(prompt):
    response = await client.images.generate(
        prompt=prompt,
        n=1,
        size="1024x1024",
        quality="standard",
        style="vivid",
        model="dall-e-3",
    )
    return response.data[0].url


@logged
async def variate_image(path_to_image):
    img = Image.open(f"{path_to_image}.jpg")
    img.save(f"{path_to_image}.png")
    os.remove(f"{path_to_image}.jpg")
    response = await client.images.create_variation(
        image=open(f"{path_to_image}.png", "rb"),
        n=2,
        size="1024x1024",
        model="dall-e-2",
    )
    media = [
        InputMediaPhoto(type=InputMediaType.PHOTO, media=response.data[0].url),
        InputMediaPhoto(type=InputMediaType.PHOTO, media=response.data[1].url),
    ]
    return media


def escaped(text, pattern=".", group_idx=0):
    if isinstance(pattern, re.Pattern):
        return pattern.sub(lambda m: "".join(["\\" + i for i in m[group_idx]]), text)
    else:
        return re.sub(
            pattern,
            lambda m: "".join(["\\" + i for i in m[group_idx]]),
            text,
            flags=re.DOTALL,
        )


def escaped_last(pattern, text):
    if isinstance(pattern, re.Pattern):
        for m in pattern.finditer(text):
            pass
        else:
            return text[: m.start()] + escaped(text[m.start() :], pattern=pattern)
    for m in re.finditer(pattern, text):
        pass
    else:
        return text[: m.start()] + escaped(text[m.start() :], pattern=pattern)


def format_markdown(text):
    t_split = CODE_PATTERN.split(text)
    c_entities = CODE_PATTERN.findall(text)
    text = t_split[0]
    for idx, c in enumerate(c_entities):
        c = "```" + escaped(c[3:-3], pattern=ESCAPED_IN_C_DEFAULT) + "```"
        c_entities[idx] = c
        text += c_entities[idx] + t_split[idx + 1]

    t_split = PRE_PATTERN.split(text)
    p_entities = PRE_PATTERN.findall(text)
    text = t_split[0]
    for idx, p in enumerate(p_entities):
        p = "`" + escaped(p[1:-1], pattern=ESCAPED_IN_C_DEFAULT) + "`"
        p_entities[idx] = p
        text += p_entities[idx] + t_split[idx + 1]

    t_split = CODE_AND_PRE_PATTERN.findall(text) + [""]
    o_entities = CODE_AND_PRE_PATTERN.split(text)
    text = ""
    for idx, o in enumerate(o_entities):
        o = o.replace("**", "*")
        o = escaped(o, pattern=ESCAPED_IN_O_DEFAULT)
        o = escaped(o, pattern=ESCAPED_IN_O_TIGHT)
        o = escaped(o, pattern=ESCAPED_IN_O_QUOTE)
        o = escaped(o, pattern=ESCAPED_IN_O_SINGLE)
        paired = ["*", "_", "__", "~", "||"]
        for char in paired:
            if (o.count(char) - o.count(escaped(char))) % 2 != 0:
                o = escaped_last(rf"(?<!\\){re.escape(char)}", o)
        o_entities[idx] = o
        text += o_entities[idx] + t_split[idx]
    return re.sub(r"\\\\+", lambda m: "\\\\\\", text)


def find_latex(text):
    other = CODE_AND_PRE_PATTERN.split(text)
    result = []
    for o in other:
        result += LATEX_PATTERN.findall(o)
    return result


def latex_significant(latex):
    multiline = "begin" in latex and "end" in latex
    tricky = len(re.findall(r"\\\w+", latex)) >= 2
    return multiline or tricky


def format_latex(text, f_idx=0):
    latex = find_latex(text)
    p = 0
    for formula in latex:
        p = text.find(formula, p)
        if latex_significant(formula):
            new_f = f"*#{f_idx + 1}:*\n`{formula}`"
            f_idx += 1
        else:
            new_f = f"`{formula}`"
        text = text[:p] + text[p:].replace(formula, new_f, 1)
        p += len(formula)
    return text


def format(text, f_idx=0):
    if not text:
        return text
    else:
        return format_markdown(format_latex(text, f_idx))


def latex2url(formula):
    body = LATEX_BODY_PATTERN.search(formula)[1]
    image_url = body.replace("\n", "").replace("&", ",").replace("\\\\", ";\,")
    image_url = " ".join([elem for elem in image_url.split(" ") if elem])
    image_url = image_url.replace(" ", "\,\!")
    return "https://math.vercel.app?from=" + urllib.parse.quote(image_url)


@logged
async def send(message, text, reply_markup=None, f_idx=0):
    if re.search(r"\w+", text) is not None:
        if fnum := len([f for f in find_latex(text) if latex_significant(f)]):
            reply_markup = inline_kbd(
                {f"#{f_idx+1+i}": f"latex-{i}" for i in range(fnum)}
            )
        if len(text) > PAR_MAX_LEN:
            head, tail = cut(text)
            await send(message, head, reply_markup, f_idx)
            await send(message, tail, reply_markup, 0)
        else:
            msg = await bot.send_message(
                message.chat.id,
                format(text, f_idx),
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
    return msg


def is_incomplete(par):
    return INCOMPLETE_CODE_PATTERN.search(par).end() != len(par)


def cut(text):
    if is_incomplete(text[:PAR_MAX_LEN]) and len(text) > PAR_MAX_LEN:
        if "\n\n" in text[:PAR_MAX_LEN]:
            delim = text.rfind("\n\n", 0, PAR_MAX_LEN)
            delim_len = 2
        else:
            delim = text.rfind("\n", 0, PAR_MAX_LEN)
            delim_len = 1
        if text.startswith("```"):
            cblock_begin = text[: text.find("\n") + 1]
        else:
            tmp = text[:delim].rfind("\n```")
            cblock_begin = text[tmp + 1 : text.find("\n", tmp + 1) + 1]
        cblock_end = "\n```"
        head = text[:delim] + cblock_end
        tail = cblock_begin + text[delim + delim_len :]
    elif not is_incomplete(text[:PAR_MAX_LEN]) and len(text) > PAR_MAX_LEN:
        delim = text.rfind("\n", 0, PAR_MAX_LEN)
        head = text[:delim]
        tail = text[delim + 1 :]
    elif not is_incomplete(text) and len(text) > PAR_MIN_LEN:
        delim = text.rfind("\n")
        head = text[:delim]
        tail = text[delim + 1 :]
    else:
        head = None
        tail = text
    return head, tail


def num_formulas_before(head, text):
    return len([f for f in find_latex(text[: text.find(head)]) if latex_significant(f)])


@logged
async def generate_completion(message):
    model = await db_get_model(message.from_user.id)
    messages = await db_get_messages(message.from_user.id)
    stream = await client.chat.completions.create(
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
        message, tail, keyboards.forget_keyboard, num_formulas_before(tail, response)
    )
    return response, usage, last_message


@logged
async def db_execute(queries, args=None):
    response = []
    if not isinstance(queries, list):
        queries = [queries]
        args = [args]
    async with await psycopg.AsyncConnection.connect(
        DSN, row_factory=dict_row
    ) as aconn:
        async with aconn.cursor() as cur:
            for i in range(min(len(queries), len(args))):
                if not isinstance(args[i], list) and args[i] is not None:
                    args[i] = [args[i]]
                try:
                    await cur.execute(queries[i], args[i])
                    response.extend(await cur.fetchall())
                except Exception as e:
                    if "the last operation didn't produce a result" in str(e):
                        pass
                    else:
                        raise e
    if len(response) == 1:
        return response[0]
    else:
        return response


async def db_get_user(user_id):
    user = await db_execute("SELECT * FROM users WHERE id = %s;", user_id)
    return user


async def db_get_model(user_id):
    model = await db_execute("SELECT * FROM models WHERE user_id = %s;", user_id)
    return model


async def db_get_messages(user_id):
    data = await db_execute(
        "SELECT * FROM messages WHERE from_user_id = %s ORDER BY timestamp;",
        user_id,
    )
    if not isinstance(data, list):
        data = [data]
    messages = []
    for msg in data:
        messages.append(
            {
                "role": msg["role"],
                "content": [
                    {"type": "text", "text": msg["text"]},
                ],
            }
        )
        if msg["image_url"] is not None:
            messages[-1]["content"].append(
                {"type": "image_url", "image_url": {"url": msg["image_url"]}}
            )
    return messages


async def db_save_user(user):
    await db_execute(
        "UPDATE users SET \
                first_name = %s, \
                last_name = %s, \
                balance = %s, \
                lock = %s \
                WHERE id = %s;",
        [
            user["first_name"],
            user["last_name"],
            user["balance"],
            user["lock"],
            user["id"],
        ],
    )


async def db_save_model(model):
    await db_execute(
        "UPDATE models SET \
                model_name = %s, \
                max_tokens = %s, \
                temperature = %s, \
                WHERE user_id = %s;",
        [
            model["model_name"],
            model["max_tokens"],
            model["temperature"],
            model["user_id"],
        ],
    )


async def db_save_message(message, role):
    await db_execute(
        "INSERT INTO messages (message_id, from_user_id, timestamp, role, text, image_url) VALUES (%s, %s, %s, %s, %s, %s);",
        [
            message.message_id,
            message.from_user.id,
            message.date,
            role,
            await get_message_text(message),
            await get_image_url(message),
        ],
    )


async def db_save_expenses(message, usage):
    await db_execute(
        "INSERT INTO transactions (user_id, prompt_tokens, completion_tokens, cost) VALUES (%s, %s, %s, %s);",
        [
            message.from_user.id,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.prompt_tokens * GPT4O_INPUT_1K / 1000
            + usage.completion_tokens * GPT4O_OUTPUT_1K / 1000,
        ],
    )


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
    await db_save_user(user)
    await asyncio.sleep(0.6)
    user = await db_get_user(user_id)
    user["lock"] = False
    await db_save_user(user)


@logged
async def balance_is_sufficient(message) -> bool:
    message_cost = 0
    encoding = tiktoken.encoding_for_model("gpt-4o")
    if message.photo:
        pre_prompt = dialogues[language(message)]["vision-pre-prompt"]
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
        "DELETE FROM messages WHERE from_user_id = %s and timestamp < TO_TIMESTAMP(%s);",
        [user_id, now - GPT_MEMORY_SEC],
    )


@logged
async def prompt_is_accepted(message) -> bool:
    if not await balance_is_sufficient(message):
        await send_template_answer(message, "empty")
        return False
    user = await db_get_user(message.from_user.id)
    if user["lock"]:
        return False
    else:
        await forget_outdated_messages(message.from_user.id)
        return True


async def get_image_url(message):
    if message.photo:
        image_path = f"{IMAGES_PATH}/{message.from_user.id}.jpg"
        await bot.download(message.photo[-1], destination=image_path)
        return local_image_to_data_url(image_path)
    else:
        return None


async def get_message_text(message):
    if message.photo:
        if message.caption:
            return message.caption
        else:
            return ""
    else:
        return message.text


def language(message):
    lang = message.from_user.language_code
    if lang is None or lang != "ru":
        lang = "en"
    return lang


@logged
async def send_template_answer(message, template, *args, reply_markup=None):
    text = dialogues[language(message)][template]
    if len(args) != 0:
        text = text.format(*args)
    await send(message, text, reply_markup=reply_markup)


@logged
async def authorized(message):
    if message.from_user.id == OWNER_CHAT_ID:
        return True
    else:
        await send_template_answer(message, "root")
        return False


@dp.message(Command("add"))
async def add_handler(message: Message) -> None:
    if await authorized(message):
        if len(message.text.split()) != 3:
            text = "_Error: the command must have following syntax:_ `/add USER_ID [+/-]FUNDS`."
            await send(message, text)
            return
        add_cmd, user_id, funds = message.text.split()
        user_id = int(user_id)
        bot_users = await db_execute("SELECT id FROM users;")
        if not isinstance(bot_users, list):
            bot_users = [bot_users]
        if user_id in [item["id"] for item in bot_users]:
            user = await db_get_user(user_id)
            if funds.startswith(("+", "-")) and funds[1:].replace(".", "", 1).isdigit():
                user["balance"] += float(funds)
                await db_save_user(user)
                await send(message, "_Done._")
            elif funds.replace(".", "", 1).isdigit():
                user["balance"] = float(funds)
                await db_save_user(user)
                await send(message, "_Done._")
            else:
                await send(message, f"_Error: {funds} is not a valid numeric data._")
        else:
            await add_user(message)
            await send(message, f"_The user *{user_id}* was added._")
            await add_handler(message)


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    await bot.set_my_commands(
        [
            types.BotCommand(command=key, description=value)
            for key, value in commands[language(message)].items()
        ]
    )
    await add_user(message)
    await send_template_answer(
        message,
        "start",
        message.from_user.first_name,
        reply_markup=keyboards.help_keyboard,
    )


@dp.message(Command("help"))
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
    text = format(dialogues[language(message)]["help"][0])
    await bot.send_animation(
        message.chat.id,
        videos["help"][0],
        caption=text,
        reply_markup=builder.as_markup(),
    )


@dp.message(Command("forget", "clear"))
async def forget_handler(message: Message) -> None:
    await db_execute(
        "DELETE FROM messages WHERE from_user_id = %s;", message.from_user.id
    )
    await send_template_answer(message, "forget")


@dp.message(Command("balance"))
async def balance_handler(message: Message) -> None:
    kbd = inline_kbd({"back-to-help": "help-0", "tokens": "tokens"}, language(message))
    user = await db_get_user(message.from_user.id)
    text = format(
        dialogues[language(message)]["balance"].format(
            round(user["balance"], 4),
            round(87 * user["balance"], 2),
            round(user["balance"] / GPT4O_OUTPUT_1K * 1000),
        ),
    )
    text += format(dialogues[language(message)]["payment"].format(FEE))
    await bot.send_animation(
        message.chat.id,
        videos["balance"],
        caption=text,
        reply_markup=kbd,
    )


@dp.message(Command("draw"))
async def draw_handler(message: Message) -> None:
    if await prompt_is_accepted(message):
        await db_save_message(message, "user")
        try:
            prompt = message.text.split("draw")[1].strip()
            if len(prompt) == 0:
                await send_template_answer(message, "draw")
                return
            async with ChatActionSender.upload_photo(message.chat.id, bot):
                image_url = await generate_image(prompt)
            kbd = inline_kbd({"redraw": "redraw"}, language(message))
            msg = await bot.send_photo(message.chat.id, image_url, reply_markup=kbd)
            await db_execute(
                "INSERT INTO messages (message_id, from_user_id, text, image_url) VALUES (%s, %s, %s, %s);",
                [
                    msg.message_id,
                    message.from_user.id,
                    await get_message_text(msg),
                    await get_image_url(msg),
                ],
            )
            user = await db_get_user(message.from_user.id)
            user["balance"] -= FEE * DALLE3_OUTPUT
            await db_save_user(user)
        except (Exception, OpenAIError) as e:
            await send_template_answer(message, "block")
            await forget_handler(message)


@dp.message()
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
        await db_save_user(user)


@dp.callback_query(F.data == "redraw")
async def redraw_callback(callback: types.CallbackQuery):
    message = callback.message
    file_name = f"images/{callback.from_user.id}"
    async with ChatActionSender.upload_photo(message.chat.id, bot):
        await bot.download(message.photo[-1], destination=file_name + ".jpg")
        media = await variate_image(file_name)
    await bot.send_media_group(message.chat.id, media)
    user = await db_get_user(callback.from_user.id)
    user["balance"] -= 2 * FEE * DALLE2_OUTPUT
    await db_save_user(user)


@dp.callback_query(F.data == "error")
async def error_callback(callback: types.CallbackQuery):
    text = dialogues[language(callback)]["error"]
    await send(callback.message, text)


@dp.callback_query(F.data == "balance")
async def balance_callback(callback: types.CallbackQuery):
    message = callback.message
    user = await db_get_user(callback.from_user.id)
    text = format(
        dialogues[language(callback)]["balance"].format(
            round(user["balance"], 4),
            round(87 * user["balance"], 2),
            round(user["balance"] / GPT4O_OUTPUT_1K * 1000),
        )
    )
    text += format(dialogues[language(message)]["payment"].format(FEE))
    kbd = inline_kbd({"back-to-help": "help-0", "tokens": "tokens"}, language(message))
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=videos["balance"],
            caption=text,
        ),
        chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=kbd,
    )


@dp.callback_query(F.data == "tokens")
async def tokens_callback(callback: types.CallbackQuery):
    message = callback.message
    text = format(dialogues[language(callback)]["tokens"])
    kbd = inline_kbd({"balance": "balance"}, language(message))
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=videos["tokens"],
            caption=text,
        ),
        chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=kbd,
    )


@dp.callback_query(F.data.startswith("help-"))
async def help_callback(callback: types.CallbackQuery):
    message = callback.message
    h_idx = int(callback.data.split("-")[1])
    payment_button = types.InlineKeyboardButton(
        text=buttons[language(callback)]["balance"], callback_data="balance"
    )
    if h_idx == 0:
        l_button = payment_button
    else:
        l_button = types.InlineKeyboardButton(
            text="<- " + buttons[language(callback)]["help"][h_idx - 1],
            callback_data=f"help-{h_idx-1}",
        )
    if h_idx == len(buttons[language(callback)]["help"]) - 1:
        r_button = payment_button
    else:
        r_button = types.InlineKeyboardButton(
            text=buttons[language(callback)]["help"][h_idx + 1] + " ->",
            callback_data=f"help-{h_idx+1}",
        )
    builder = InlineKeyboardBuilder()
    builder.add(l_button, r_button)
    text = format(dialogues[language(callback)]["help"][h_idx])
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION, media=videos["help"][h_idx], caption=text
        ),
        chat_id=message.chat.id,
        message_id=message.message_id,
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data.startswith("latex-"))
async def latex_callback(callback: types.CallbackQuery):
    f_i = int(callback.data.split("-")[1])
    f = [f for f in find_latex(callback.message.text) if latex_significant(f)][f_i]
    image_url = latex2url(f)
    local_path = f"images/{callback.from_user.id}.jpg"
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


@dp.callback_query(F.data == "hide")
async def hide_callback(callback: types.CallbackQuery):
    message = callback.message
    deleted = await bot.delete_message(message.chat.id, message.message_id)
    if not deleted:
        text = format(dialogues[language(callback)]["old"])
        await bot.send_message(
            message.chat.id, text, reply_to_message_id=message.message_id
        )


async def on_startup(bot: Bot) -> None:
    # If you have a self-signed SSL certificate, then you will need to send a public
    # certificate to Telegram
    await bot.set_webhook(
        f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET
    )


# Initialize Bot instance with default bot properties which will be passed to all API calls
bot = Bot(
    token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2)
)


def main() -> None:
    # Dispatcher is a root router

    # Register startup hook to initialize webhook
    dp.startup.register(on_startup)

    # Create aiohttp.web.Application instance
    app = web.Application()

    # Create an instance of request handler,
    # aiogram has few implementations for different cases of usage
    # In this example we use SimpleRequestHandler which is designed to handle simple cases
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    # Register webhook handler on application
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # Mount dispatcher startup and shutdown hooks to aiohttp application
    setup_application(app, dp, bot=bot)

    # And finally start webserver
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    main()
