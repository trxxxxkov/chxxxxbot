import asyncio
import logging
import sys
import json
import time
import re
import os
import base64
import tiktoken
import openai
import cairosvg
import urllib.parse

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
from answers import templates
from commands import commands

load_dotenv()

BOT_TOKEN = getenv("TG_BOT_TOKEN")
BOT_USERS = getenv("TG_BOT_USERS").split(",")
OWNER_ID = 791388236
OPENAI_KEY = getenv("OPENAI_API_KEY")
# OPENAI API prices per 1K tokens
FEE = 1.6
GPT_MEMORY_SEC = 7200
GPT_MEMORY_MSG = 20
GPT_MODEL = "gpt-4-turbo"
GPT4TURBO_INPUT_1K = 0.01
GPT4TURBO_OUTPUT_1K = 0.03
DALLE3_OUTPUT = 0.08
DALLE2_OUTPUT = 0.02
GPT4VISION_INPUT = 0.01

LATEX_MIN_LEN = 20

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


async def variate_image(path):
    img = Image.open(f"{path}.jpg")
    img.save(f"{path}.png")
    os.remove(f"{path}.jpg")
    response = await client.images.create_variation(
        image=open(f"{path}.png", "rb"),
        n=2,
        size="1024x1024",
        model="dall-e-2",
    )
    media = [
        InputMediaPhoto(type=InputMediaType.PHOTO, media=response.data[0].url),
        InputMediaPhoto(type=InputMediaType.PHOTO, media=response.data[1].url),
    ]
    return media


async def format(text, defects=True, latex=True, markdown=True):
    if defects:
        if text and text[0] == ",":
            text = text[1:]
        lines = text.split("\n")
        for i in range(len(lines)):
            if lines[i].strip() in ".,?!-:;":
                lines[i] = ""
        text = "\n".join([elem for elem in lines if elem])
    if latex:
        text = (
            text.replace("$$", "*")
            .replace("\[", "*")
            .replace("\]", "*")
            .replace("\(", "*")
            .replace("\)", "*")
        )
        if text.find("$") != text.rfind("$"):
            text = text.replace("$", "*")
    if markdown:
        text = (
            text.replace("**", "*")
            .replace("\\", "\\\\")
            .replace("_", "\\_")
            .replace("[", "\\[")
            .replace("]", "\\]")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("~", "\\~")
            .replace(">", "\\>")
            .replace("#", "\\#")
            .replace("+", "\\+")
            .replace("-", "\\-")
            .replace("=", "\\=")
            .replace("|", "\\|")
            .replace("{", "\\{")
            .replace("}", "\\}")
            .replace(".", "\\.")
            .replace("!", "\\!")
        )
    return text


async def send_latex(message, f):
    builder = InlineKeyboardBuilder()
    lang = await get_lang(message)
    builder.add(
        types.InlineKeyboardButton(
            text=templates[lang]["latex-original"], callback_data="latex-original"
        ),
    )
    url = "https://math.vercel.app?from=" + urllib.parse.quote(
        translited(f[2].lower()).replace("\\\\", ";\,").replace(" ", "\,\!")
    )
    path = f"photos/{message.from_user.username}.jpg"
    svg_to_jpg(url, path)
    photo = FSInputFile(path)
    sent_message = await bot.send_photo(
        message.chat.id, photo, reply_markup=builder.as_markup()
    )
    data = read_data(message.from_user.username)
    data["latex"][sent_message.message_id] = f[3][0] + f[2] + f[3][1]
    write_data(message.from_user.username, data)


async def send(message, text, reply_markup=None):
    text = await format(text, latex=False, markdown=False)
    if not text:
        return ""
    formulas = latex_math_found(text)
    if formulas:
        for f in formulas:
            await send(message, text[: f[0]])
            await send_latex(message, f)
        await send(message, text[formulas[-1][1] + len(formulas[-1][3][1]) :])
    else:
        text = await format(text)
        await bot.send_message(message.chat.id, text, reply_markup=reply_markup)


def latex_math_found(text):
    bad_delims = [
        ["\\begin{document}", "\end{document}"],
        ["usepackage", "usepackage"],
    ]
    delims = [
        ["$", "$"],
        ["$$", "$$"],
        ["\[", "\]"],
        ["\(", "\)"],
        ["\\begin{equation}", "\end{equation}"],
        ["\\begin{align}", "\end{align}"],
        ["\\begin{gather}", "\end{gather}"],
        ["\\begin{multiline}", "\end{multiline}"],
        ["\\begin{cases}", "\end{cases}"],
        ["\\begin{equation*}", "\end{equation*}"],
        ["\\begin{align*}", "\end{align*}"],
        ["\\begin{gather*}", "\end{gather*}"],
        ["\\begin{multiline*}", "\end{multiline*}"],
        ["\\begin{cases*}", "\end{cases*}"],
    ]
    from_idx = 0
    math_found = []
    for bad_delim in bad_delims:
        if text.find(bad_delim[0]) != text.find(bad_delim[1]):
            return []
    for delim in delims:
        from_idx = 0
        l = text.find(delim[0], from_idx)
        r = text.find(delim[1], l + len(delim[0]))
        while l != -1 and r != -1:
            if (
                r - l - len(delim[0]) >= LATEX_MIN_LEN
                or text[l + len(delim[0]) : r].count("\\") > 2
                or "begin" in delim[0]
            ):
                math_found.append([l, r, text[l + len(delim[0]) : r], delim])
            from_idx = r + len(delim[1])
            l = text.find(delim[0], from_idx)
            r = text.find(delim[1], l + len(delim[0]))
    return sorted(math_found, key=lambda x: x[0])


def translited(text):
    GOST = {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "j",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "cz",
        "ч": "ch",
        "ш": "sh",
        "щ": "shh",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
    for key, value in GOST.items():
        text = text.replace(key, value)
    return text


def islatex(text):
    latex_flags = [
        ["```latex", "```"],
        ["$$", "$$"],
        ["\[", "\]"],
        ["\(", "\)"],
        ["\\begin{", "\end{"],
    ]
    for flag in latex_flags:
        if (
            flag[0] in text
            and flag[1] in text
            and text.find(flag[0]) != text.rfind(flag[1])
        ):
            return True
    else:
        return False


def paragraph_type(par):
    if par.find("```") == -1 or par.find("```") != par.rfind("```"):
        return "text"
    elif islatex(par):
        return "latex"
    else:
        return "code"


async def process_delim(delim, par, message, response):
    await send(message, par[:delim])
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    response += par[:delim]
    par = par[delim:]
    return response, par


async def generate_completion(message):
    data = read_data(message.from_user.username)
    stream = await client.chat.completions.create(
        model=GPT_MODEL, messages=data["messages"], temperature=0.5, stream=True
    )
    response = ""
    par = ""
    par_type = "text"
    try:
        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                par += chunk.choices[0].delta.content
                match par_type, paragraph_type(par):
                    case "text", "text":
                        if "\n\n" in par:
                            delim = par.rfind("\n\n") + 2
                            response, par = await process_delim(
                                delim, par, message, response
                            )
                    case "text", t:
                        par_type = t
                        delim = par.rfind("```")
                        response, par = await process_delim(
                            delim, par, message, response
                        )
                    case _, "text":
                        par_type = "text"
                        delim = par.rfind("```") + 3
                        response, par = await process_delim(
                            delim, par, message, response
                        )
        await send(message, par, keyboards.forget_keyboard)
        response += par
    except (Exception, OpenAIError) as e:
        alert = await format(
            f"*ERROR:* {e}\n\n*USER:* {message.from_user.username}\n\n*LAST PROMPT:* {message.text}\n\n*COLLECTED RESPONSE:* {response}",
            latex=False,
        )
        builder = InlineKeyboardBuilder()
        lang = await get_lang(message)
        builder.add(
            types.InlineKeyboardButton(
                text=templates[lang]["what"], callback_data="error"
            ),
        )
        await bot.send_message(OWNER_ID, alert)
        await bot.send_message(message.chat.id, alert, reply_markup=builder.as_markup())
        await clear_handler(message)
    finally:
        await stream.close()
    return response


def read_data(username) -> None:
    with open(f"data/{username}.json", "r") as f:
        data = json.load(f)
    return data


def write_data(username, data) -> None:
    with open(f"data/{username}.json", "w") as f:
        json.dump(data, f)


async def updated_data(message) -> bool:
    username = message.from_user.username
    data = read_data(username)
    if data["balance"] < 0.001:
        await answer(message, "empty")
        alert = await format(
            f"*WARNING: @{username} has tried to use GPT with empty balance.*"
        )
        await bot.send_message(OWNER_ID, alert)
        return False
    now = time.time()
    data["timestamps"].append(now)
    encoding = tiktoken.encoding_for_model("gpt-4-turbo")
    if message.photo:
        image_path = f"photos/{username}.jpg"
        await bot.download(message.photo[-1], destination=image_path)
        data_url = local_image_to_data_url(image_path)
        text = message.caption if message.caption else "What do you think about it?"
        data["messages"].append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "high"},
                    },
                ],
            }
        )
        data["tokens"] += len(encoding.encode(text))
        data["balance"] -= FEE * GPT4VISION_INPUT
    else:
        data["messages"].append({"role": "user", "content": message.text})
        data["tokens"] += len(encoding.encode(message.text))
    data["balance"] -= data["tokens"] * FEE * GPT4TURBO_INPUT_1K / 1000
    # Remove outdated messages from the chat history
    for i in range(len(data["timestamps"])):
        if now - data["timestamps"][i] < GPT_MEMORY_SEC:
            data["timestamps"] = data["timestamps"][i:]
            data["messages"] = data["messages"][i:]
            break
    # Cut off last GPT_MEMORY_MSH messages
    if len(data["timestamps"]) > GPT_MEMORY_MSG:
        data["timestamps"] = data["timestamps"][-GPT_MEMORY_MSG:]
        data["messages"] = data["messages"][-GPT_MEMORY_MSG:]
    write_data(username, data)
    return True


async def get_lang(message):
    lang = message.from_user.language_code
    if lang != "ru":
        lang = "en"
    return lang


async def answer(message, template, *args, reply_markup=None):
    lang = await get_lang(message)
    text = templates[lang][template]
    if len(args) != 0:
        text = text.format(*args)
    await message.answer(
        re.sub(r"[_[\]()~>#\+\-=|{}.!]", lambda x: "\\" + x.group(), text),
        reply_markup=reply_markup,
    )


async def authorized(message):
    if message.from_user.username not in BOT_USERS:
        await answer(message, "auth", reply_markup=keyboards.help_keyboard)
        return False
    return True


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    lang = await get_lang(message)
    await bot.set_my_commands(
        [
            types.BotCommand(command=key, description=value)
            for key, value in commands[lang].items()
        ]
    )
    await answer(
        message,
        "start",
        message.from_user.first_name,
        reply_markup=keyboards.help_keyboard,
    )


@dp.message(Command("help"))
async def help_handler(message: Message) -> None:
    builder = InlineKeyboardBuilder()
    lang = await get_lang(message)
    builder.add(
        types.InlineKeyboardButton(
            text=templates[lang]["payment"], callback_data="payment"
        ),
    )
    await answer(message, "help", reply_markup=builder.as_markup())


@dp.message(Command("forget", "clear"))
async def clear_handler(message: Message) -> None:
    username = message.from_user.username
    if await authorized(message):
        data = read_data(username)
        await answer(message, "forget")
        data["messages"].clear()
        data["latex"].clear()
        data["timestamps"].clear()
        data["tokens"] = 0
        write_data(username, data)


@dp.message(Command("balance"))
async def billing_handler(message: Message) -> None:
    if await authorized(message):
        username = message.from_user.username
        data = read_data(username)
        await answer(
            message,
            "balance",
            round(data["balance"], 4),
            round(94 * data["balance"], 2),
        )


@dp.message(Command("add"))
async def add_handler(message: Message) -> None:
    if await authorized(message) and message.chat.id == OWNER_ID:
        if len(message.text.split()) == 3 and float(message.text.split()[2]) >= 0:
            _, username, balance = message.text.split()
            if username in BOT_USERS:
                data = read_data(username)
                data["balance"] += float(balance)
                write_data(username, data)
                return
            else:
                init = {
                    "messages": [],
                    "latex": {},
                    "timestamps": [],
                    "tokens": 0,
                    "balance": float(balance),
                }
                with open(f"data/{username}.json", "w") as f:
                    json.dump(init, f)
                BOT_USERS.append(username)
                os.system(f"dotenv set TG_BOT_USERS {','.join(BOT_USERS)}")
                return
    alert = await format(
        f"*WARNING: @{message.from_user.username} has made an attempt to add another user.*"
    )
    await bot.send_message(OWNER_ID, alert)


@dp.message(Command("rm", "remove", "delete"))
async def delete_handler(message: Message) -> None:
    if await authorized(message) and message.chat.id == OWNER_ID:
        if len(message.text.split()) == 2 and message.text.split()[1] in BOT_USERS:
            _, username = message.text.split()
            BOT_USERS.remove(username)
            os.system(f"dotenv set TG_BOT_USERS {','.join(BOT_USERS)}")
            os.remove(f"data/{username}.json")
            return
    alert = f"*WARNING: @{message.from_user.username} has made and attempt to delete another user.*"
    await bot.send_message(OWNER_ID, alert)


@dp.message(Command("draw"))
async def image_generation_handler(message: Message) -> None:
    if await authorized(message) and await updated_data(message):
        try:
            username = message.from_user.username
            prompt = message.text.split("draw")[1].strip()
            if len(prompt) == 0:
                await answer(message, "draw")
                return
            async with ChatActionSender.upload_photo(bot=bot, chat_id=message.chat.id):
                image_url = await generate_image(prompt)
            builder = InlineKeyboardBuilder()
            lang = await get_lang(message)
            builder.add(
                types.InlineKeyboardButton(
                    text=templates[lang]["redraw"], callback_data="redraw"
                ),
            )
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=image_url,
                reply_markup=builder.as_markup(),
            )
            data = read_data(username)
            data["balance"] -= FEE * DALLE3_OUTPUT
            write_data(username, data)
        except (Exception, OpenAIError) as e:
            alert = await format(
                f"*ERROR:* {e}\n\n*USER:* {message.from_user.username}\n\n*LAST PROMPT:* {message.text}",
                latex=False,
            )
            await bot.send_message(OWNER_ID, alert)
            await answer(message, "block")
            await clear_handler(message)


async def unknown_commands_handler(message: Message) -> None:
    await answer(message, "unknown", reply_markup=keyboards.help_keyboard)


@dp.message()
async def universal_handler(message: Message) -> None:
    if message.text and message.text[0] == "/":
        await unknown_commands_handler(message)
    elif await authorized(message) and await updated_data(message):
        username = message.from_user.username
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            response = await generate_completion(message)
        data = read_data(username)
        data["timestamps"].append(time.time())
        data["messages"].append({"role": "system", "content": response})
        encoding = tiktoken.encoding_for_model("gpt-4-turbo")
        data["tokens"] += len(encoding.encode(response))
        data["balance"] -= (
            len(encoding.encode(response)) * FEE * GPT4TURBO_OUTPUT_1K / 1000
        )
        write_data(username, data)


@dp.callback_query(F.data == "redraw")
async def redraw_handler(callback: types.CallbackQuery):
    username = callback.from_user.username
    message = callback.message
    file_name = f"photos/{username}"
    async with ChatActionSender.upload_photo(bot=bot, chat_id=message.chat.id):
        await bot.download(message.photo[-1], destination=file_name + ".jpg")
        media = await variate_image(file_name)
    await bot.send_media_group(message.chat.id, media)
    data = read_data(username)
    data["balance"] -= 2 * FEE * DALLE2_OUTPUT
    write_data(username, data)


@dp.callback_query(F.data == "error")
async def error_message_handler(callback: types.CallbackQuery):
    await answer(callback.message, "error")


@dp.callback_query(F.data == "payment")
async def payment_redirection_handler(callback: types.CallbackQuery):
    data = read_data(callback.from_user.username)
    lang = callback.from_user.language_code
    text = templates[lang]["balance"]
    text = text.format(round(data["balance"], 4), round(94 * data["balance"], 2))
    await callback.message.answer(
        re.sub(r"[_[\]()~>#\+\-=|{}.!]", lambda x: "\\" + x.group(), text)
    )


@dp.callback_query(F.data == "latex-original")
async def latex_handler(callback: types.CallbackQuery):
    message = callback.message
    builder = InlineKeyboardBuilder()
    lang = await get_lang(message)
    builder.add(
        types.InlineKeyboardButton(text=templates[lang]["hide"], callback_data="hide"),
    )
    data = read_data(callback.from_user.username)
    text = data["latex"].get(str(message.message_id), templates[lang]["forgotten"])
    text = await format(text, latex=False)
    await bot.send_message(
        message.chat.id,
        text,
        reply_to_message_id=message.message_id,
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data == "hide")
async def hide_handler(callback: types.CallbackQuery):
    message = callback.message
    deleted = await bot.delete_message(message.chat.id, message.message_id)
    if not deleted:
        lang = await get_lang(callback)
        text = await format(templates[lang]["old"])
        await bot.send_message(
            message.chat.id, text, reply_to_message_id=message.message_id
        )


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
