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

from mimetypes import guess_type
from dotenv import load_dotenv
from os import getenv
from PIL import Image
from openai import AsyncOpenAI, OpenAIError

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, InputMediaType, ChatAction
from aiogram.filters import Command
from aiogram.utils.chat_action import ChatActionSender
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import Message, InputMediaPhoto, FSInputFile

import keyboards
from dialogues import dialogues
from commands import commands
from videos import videos
from buttons import buttons

load_dotenv()

OWNER_CHAT_ID = 791388236
BOT_TOKEN = getenv("TG_BOT_TOKEN")
OPENAI_KEY = getenv("OPENAI_API_KEY")
# OPENAI API prices per 1K tokens
FEE = 1.6
GPT_MEMORY_SEC = 7200
GPT_MODEL = "gpt-4o"
GPT4O_INPUT_1K = 0.005
GPT4O_OUTPUT_1K = 0.015
DALLE3_OUTPUT = 0.08
DALLE2_OUTPUT = 0.02

PAR_MIN_LEN = 250
PAR_MAX_LEN = 3950

INITIAL_USER_DATA = {
    "balance": 0,
    "lock": False,
    "timestamps": [],
    "latex": {},
    "messages": [],
}

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
dp = Dispatcher()
bot = Bot(
    token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2)
)
client = AsyncOpenAI(
    api_key=OPENAI_KEY,
    base_url="https://api.openai.com/v1",
)


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


def inline_keyboard(keys, lang="en"):
    keyboard = InlineKeyboardBuilder()
    for button, callback in keys.items():
        keyboard.add(
            types.InlineKeyboardButton(
                text=buttons[lang][button], callback_data=callback
            ),
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


def escaped_all(text):
    return re.sub(".", lambda m: "\\" + m.group(), text, flags=re.DOTALL)


def escaped_last(char, text):
    m = re.search(rf"{re.escape(char[::-1])}(?!\\)", text[::-1])
    return text[: len(text) - m.end()] + text[len(text) - m.end() :].replace(
        char, escaped_all(char), 1
    )


def format_markdown(text):
    code = r"(?<!`|\w)```\S*?\n(?:.|\n)*?\n\s*```(?!`|\w)"
    pre = r"(?<!`|\w)`[^`]+?`(?!`|\w)"
    code_and_pre = rf"(?:{pre})|(?:{code})"
    c_entities = re.findall(code, text)
    p_entities = re.findall(pre, text)
    o_entities = re.split(code_and_pre, text)
    for c in c_entities:
        esc_c = r"(?<!\\)[\\`]"
        new_c = "```" + re.sub(esc_c, lambda m: "\\" + m[0], c[3:-3]) + "```"
        text = text.replace(c, new_c)
    for p in p_entities:
        esc_p = esc_c
        new_p = "`" + re.sub(esc_p, lambda m: "\\" + m[0], p[1:-1]) + "`"
        text = text.replace(p, new_p)
    for o in o_entities:
        new_o = o.replace("**", "*")
        new_o = re.sub(r"(?<!\\)[\\[\]()`#+-={}.!]", lambda m: "\\" + m[0], new_o)
        new_o = re.sub(r"(?:(?<!\n)|(?<!\A)|(?<!\\))>", lambda m: "\\" + m[0], new_o)
        new_o = re.sub(r"(?<!\||\\)\|(?!\|)", lambda m: "\\" + m[0], new_o)
        paired = ["*", "_", "__", "~", "||"]
        for char in paired:
            if (new_o.count(char) - new_o.count(escaped_all(char))) % 2 != 0:
                new_o = escaped_last(char, new_o)
        new_o = re.sub(r"(?!\\)\\\\(?!\\)", lambda m: "\\" + m[0], new_o)
        text = text.replace(o, new_o)
    return text


def format(text, *, latex=True, gpt=True, markdown=True):
    if text and markdown:
        text = format_markdown(text)
    return text


def get_latex_image_url(formula):
    image_url = formula[2].replace("\n", "").replace("&", ",").replace("\\\\", ";\,")
    image_url = " ".join([elem for elem in image_url.split(" ") if elem]).replace(
        " ", "\,\!"
    )
    image_url = "https://math.vercel.app?from=" + urllib.parse.quote(image_url)
    return image_url


async def send_latex_formula(message, formula):
    image_url = get_latex_image_url(formula)
    path = f"photos/{message.from_user.id}.jpg"
    svg_to_jpg(image_url, path)
    photo = FSInputFile(path)
    inline = inline_keyboard({"latex-original": "latex-original"}, language(message))
    sent_message = await bot.send_photo(message.chat.id, photo, reply_markup=inline)
    data = await read_user_data(message.from_user.id)
    data["latex"][sent_message.message_id] = formula[3][0] + formula[2] + formula[3][1]
    await write_user_data(message.from_user.id, data)


async def send(message, text, reply_markup=None):
    text = format(text)
    if re.search(r"\w+", text) is not None:
        await bot.send_message(
            message.chat.id,
            text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )


def logged(f):
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except (Exception, OpenAIError) as e:
            alert = format(
                f"*Error:* {e};\n\n*function name =* {f.__name__};\n\n*args =* {args};\n\n*kwargs =* {kwargs};"
            )
            bot.send_message(OWNER_CHAT_ID, alert)
            # inline = inline_keyboard({"error": "error"}, language(message))
            # await bot.send_message(message.chat.id, alert, reply_markup=inline)
            # await clear_handler(message)

    return wrapper


def is_incomplete(par):
    par = par.replace(" ", "")
    return (
        par.startswith("```")
        and par.count("\n```") % 2 == 0
        or not par.startswith("```")
        and par.count("\n```") % 2 != 0
    )


def cut(text):
    if is_incomplete(text) and len(text) > PAR_MAX_LEN:
        if "\n\n" in text:
            delim = text.rfind("\n\n")
            delim_len = 2
        else:
            delim = text.rfind("\n")
            delim_len = 1
        if text.startswith("```"):
            cblock_begin = text[: text.find("\n") + 1]
        else:
            tmp = text[:delim].rfind("\n```")
            cblock_begin = text[tmp + 1 : text.find("\n", tmp + 1) + 1]
        cblock_end = "\n```"
        head = text[:delim] + cblock_end
        tail = cblock_begin + text[delim + delim_len :]
    elif not is_incomplete(text) and len(text) > PAR_MAX_LEN:
        delim = text.rfind("\n")
        head = text[:delim]
        tail = text[delim + 1 :]
    elif not is_incomplete(text) and len(text) > PAR_MIN_LEN and "\n\n" in text:
        delim = text.rfind("\n\n")
        head = text[:delim]
        tail = text[delim + 2 :]
    else:
        head = None
        tail = text
    return head, tail


@logged
async def generate_completion(message):
    data = await read_user_data(message.from_user.id)
    stream = await client.chat.completions.create(
        model=GPT_MODEL,
        messages=data["messages"],
        temperature=0.2,
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
            head, tail = cut(tail)
            if head is not None:
                await send(message, head)
    await send(message, tail, keyboards.forget_keyboard)
    return response, usage


async def read_user_data(user_id) -> None:
    with open(f"data/{user_id}.json", "r") as f:
        data = json.load(f)
    return data


async def add_user(user_id):
    with open("bot_users.json", "r") as f:
        bot_users = json.load(f)
    if user_id not in bot_users:
        bot_users.append(user_id)
        with open("bot_users.json", "w") as f:
            json.dump(bot_users, f)
        with open(f"data/{user_id}.json", "w") as f:
            json.dump(INITIAL_USER_DATA, f)


async def write_user_data(user_id, data) -> None:
    with open(f"data/{user_id}.json", "w") as f:
        json.dump(data, f)


async def lock(user_id):
    data = await read_user_data(user_id)
    data["lock"] = True
    await write_user_data(user_id, data)
    await asyncio.sleep(0.6)
    data = await read_user_data(user_id)
    data["lock"] = False
    await write_user_data(user_id, data)


async def balance_is_sufficient(message) -> bool:
    message_cost = 0
    encoding = tiktoken.encoding_for_model("gpt-4o")
    data = await read_user_data(message.from_user.id)
    if message.photo:
        pre_prompt = dialogues[language(message)]["vision-pre-prompt"]
        text = message.caption if message.caption else pre_prompt
        message_cost += FEE * GPT4O_INPUT_1K
    else:
        text = message.text
    tokens = data["tokens"] + len(encoding.encode(text))
    message_cost += tokens * FEE * GPT4O_INPUT_1K / 1000
    return 2 * message_cost <= data["balance"]


async def forget_outdated_messages(message):
    data = await read_user_data(message.from_user.id)
    now = time.time()
    for i in range(len(data["timestamps"])):
        if now - data["timestamps"][i] < GPT_MEMORY_SEC:
            data["timestamps"] = data["timestamps"][i:]
            data["messages"] = data["messages"][i:]
            break
    await write_user_data(message.from_user.id, data)


async def prompt_is_accepted(message) -> bool:
    if not await balance_is_sufficient(message):
        await send_template_answer(message, "empty")
        return False
    await forget_outdated_messages(message)
    data = await read_user_data(message.from_user.id)
    now = time.time()
    data["timestamps"].append(now)
    if message.photo:
        image_path = f"photos/{message.from_user.id}.jpg"
        await bot.download(message.photo[-1], destination=image_path)
        image_url = local_image_to_data_url(image_path)
        image_caption = (
            message.caption
            if message.caption
            else dialogues[language(message)]["vision-pre-prompt"]
        )
        data["messages"].append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": image_caption},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url, "detail": "high"},
                    },
                ],
            }
        )
    else:
        data["messages"].append({"role": "user", "content": message.text})
    await write_user_data(message.from_user.id, data)
    if not data["lock"]:
        return True
    else:
        return False


def language(message):
    lang = message.from_user.language_code
    if lang is None or lang != "ru":
        lang = "en"
    return lang


async def send_template_answer(message, template, *args, reply_markup=None):
    text = dialogues[language(message)][template]
    if len(args) != 0:
        text = text.format(*args)
    await send(message, text, reply_markup=reply_markup)


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
        add_cmd, user, funds = message.text.split()
        user = int(user)
        with open("bot_users.json", "r") as f:
            bot_users = json.load(f)
        if user in bot_users:
            user_data = await read_user_data(user)
            if funds.startswith(("+", "-")) and funds[1:].replace(".", "", 1).isdigit():
                user_data["balance"] += float(funds)
                await write_user_data(user, user_data)
                await send(message, "_Done._")
            elif funds.replace(".", "", 1).isdigit():
                user_data["balance"] = float(funds)
                await write_user_data(user, user_data)
                await send(message, "_Done._")
            else:
                text = f"_Error: {funds} is not a valid numeric data._"
                await send(message, text)
        else:
            await add_user(user)
            text = f"_The user *{user}* was added._"
            await send(message, text)
            await add_handler(message)


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    await bot.set_my_commands(
        [
            types.BotCommand(command=key, description=value)
            for key, value in commands[language(message)].items()
        ]
    )
    new_user = message.from_user.id
    await add_user(new_user)
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
    data = await read_user_data(message.from_user.id)
    await send_template_answer(message, "forget")
    data["messages"].clear()
    data["latex"].clear()
    data["timestamps"].clear()
    await write_user_data(message.from_user.id, data)


@dp.message(Command("balance"))
async def balance_handler(message: Message) -> None:
    markup = inline_keyboard(
        {"back-to-help": "help-0", "tokens": "tokens"}, language(message)
    )
    data = await read_user_data(message.from_user.id)
    text = format(
        dialogues[language(message)]["balance"].format(
            round(data["balance"], 4),
            round(94 * data["balance"], 2),
            round(data["balance"] / GPT4O_OUTPUT_1K * 1000),
        ),
    )
    text += format(dialogues[language(message)]["payment"].format(FEE))
    await bot.send_animation(
        message.chat.id,
        videos["balance"],
        caption=text,
        reply_markup=markup,
    )


@dp.message(Command("draw"))
async def draw_handler(message: Message) -> None:
    if await prompt_is_accepted(message):
        try:
            prompt = message.text.split("draw")[1].strip()
            if len(prompt) == 0:
                await send_template_answer(message, "draw")
                return
            async with ChatActionSender.upload_photo(message.chat.id, bot):
                image_url = await generate_image(prompt)
            inline = inline_keyboard({"redraw": "redraw"}, language(message))
            await bot.send_photo(message.chat.id, image_url, reply_markup=inline)
            data = await read_user_data(message.from_user.id)
            data["messages"].append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url, "detail": "high"},
                        },
                    ],
                }
            )
            data["balance"] -= FEE * DALLE3_OUTPUT
            await write_user_data(message.from_user.id, data)
        except (Exception, OpenAIError) as e:
            await send_template_answer(message, "block")
            await forget_handler(message)


@dp.message()
async def handler(message: Message) -> None:
    if await prompt_is_accepted(message):
        await lock(message.from_user.id)
        async with ChatActionSender.typing(message.chat.id, bot):
            response, usage = await generate_completion(message)
        data = await read_user_data(message.from_user.id)
        data["timestamps"].append(time.time())
        data["messages"].append({"role": "system", "content": response})
        data["balance"] -= (
            (
                GPT4O_INPUT_1K * usage.prompt_tokens
                + GPT4O_OUTPUT_1K * usage.completion_tokens
            )
            * FEE
            / 1000
        )
        await write_user_data(message.from_user.id, data)


@dp.callback_query(F.data == "redraw")
async def redraw_callback(callback: types.CallbackQuery):
    message = callback.message
    file_name = f"photos/{callback.from_user.id}"
    async with ChatActionSender.upload_photo(message.chat.id, bot):
        await bot.download(message.photo[-1], destination=file_name + ".jpg")
        media = await variate_image(file_name)
    await bot.send_media_group(message.chat.id, media)
    data = await read_user_data(callback.from_user.id)
    data["balance"] -= 2 * FEE * DALLE2_OUTPUT
    await write_user_data(callback.from_user.id, data)


@dp.callback_query(F.data == "error")
async def error_callback(callback: types.CallbackQuery):
    text = dialogues[language(callback)]["error"]
    await send(callback.message, text)


@dp.callback_query(F.data == "balance")
async def balance_callback(callback: types.CallbackQuery):
    message = callback.message
    data = await read_user_data(callback.from_user.id)
    text = format(
        dialogues[language(callback)]["balance"].format(
            round(data["balance"], 4),
            round(94 * data["balance"], 2),
            round(data["balance"] / GPT4O_OUTPUT_1K * 1000),
        )
    )
    text += format(dialogues[language(message)]["payment"].format(FEE))
    inline = inline_keyboard(
        {"back-to-help": "help-0", "tokens": "tokens"}, language(message)
    )
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=videos["balance"],
            caption=text,
        ),
        message.chat.id,
        message.message_id,
        reply_markup=inline,
    )


@dp.callback_query(F.data == "tokens")
async def tokens_callback(callback: types.CallbackQuery):
    message = callback.message
    text = format(dialogues[language(callback)]["tokens"])
    inline = inline_keyboard({"balance": "balance"}, language(message))
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=videos["tokens"],
            caption=text,
        ),
        message.chat.id,
        message.message_id,
        reply_markup=inline,
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
        message.chat.id,
        message.message_id,
        reply_markup=builder.as_markup(),
    )


# @dp.callback_query(F.data == "hide")
# async def hide_callback(callback: types.CallbackQuery):
#     message = callback.message
#     deleted = await bot.delete_message(message.chat.id, message.message_id)
#     if not deleted:
#         text = format(dialogues[language(callback)]["old"])
#         await bot.send_message(
#             message.chat.id, text, reply_to_message_id=message.message_id
#         )


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
