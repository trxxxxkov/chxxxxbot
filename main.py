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
from dialogues import dialogues
from commands import commands
from gifs import gifs
from buttons import buttons

load_dotenv()

BOT_TOKEN = getenv("TG_BOT_TOKEN")
BOT_USERS = getenv("TG_BOT_USERS").split(",")
OWNER_CHAT_ID = 791388236
OPENAI_KEY = getenv("OPENAI_API_KEY")
# OPENAI API prices per 1K tokens
FEE = 1.6
GPT_MEMORY_SEC = 7200
GPT_MEMORY_MSG = 20
GPT_MODEL = "gpt-4o"
GPT4O_INPUT_1K = 0.005
GPT4O_OUTPUT_1K = 0.015
GPT4VISION_INPUT = 0.005
DALLE3_OUTPUT = 0.08
DALLE2_OUTPUT = 0.02

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


async def format_markdown(text, keep="_*"):
    if text:
        if (l_idx := text.find("###")) != -1:
            if (r_idx := text.find("\n", l_idx)) != -1:
                text = text.replace(
                    text[l_idx:r_idx], "*" + text[l_idx + 3 : r_idx] + "*"
                )
            else:
                text = text.replace(text[l_idx:], "*" + text[l_idx + 3 :] + "*")
        text = (
            text.replace("**", "*")
            .replace("\\", "\\\\")
            .replace("_", "\\_")
            .replace("*", "\\*")
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
        if keep:
            for char in keep:
                text = text.replace(f"\\{char}", char)
    return text


async def format_latex(text):
    if text:
        text = (
            text.replace("$$", "*")
            .replace("\[", "*")
            .replace("\]", "*")
            .replace("\(", "*")
            .replace("\)", "*")
        )
        if text.count("$") % 2 == 0:
            text = text.replace("$", "*")
    return text


async def format(text, latex=True, defects=True, markdown=True, keep="_*"):
    if latex and "`" not in text:
        text = await format_latex(text)
    if defects:
        if text and text[0] == ",":
            text = text[1:]
        lines = text.split("\n")
        for i in range(len(lines)):
            if lines[i].strip() in ".,?!-:;":
                lines[i] = ""
        text = "\n".join([elem for elem in lines if elem])
    if markdown:
        text = await format_markdown(text, keep)
    return text


async def send_latex_formula(message, formula):
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(
            text=buttons[language(message)]["latex-original"],
            callback_data="latex-original",
        ),
    )
    image_url = formula[2].replace("\n", "").replace("&", "").replace("\\\\", ";\,")
    image_url = " ".join([elem for elem in image_url.split(" ") if elem]).replace(
        " ", "\,\!"
    )
    image_url = "https://math.vercel.app?from=" + urllib.parse.quote(
        image_url.replace(" ", "\,\!")
    )
    path = f"photos/{message.from_user.username}.jpg"
    svg_to_jpg(image_url, path)
    photo = FSInputFile(path)
    sent_message = await bot.send_photo(
        message.chat.id, photo, reply_markup=builder.as_markup()
    )
    data = await read_data(message.from_user.username)
    data["latex"][sent_message.message_id] = formula[3][0] + formula[2] + formula[3][1]
    await write_data(message.from_user.username, data)


def latex_type(text):
    document_flags = ["documentclass", "usepackage", "\\begin{document}"]
    for flag in document_flags:
        if flag in text:
            return "document"
    else:
        if latex_math_found(text):
            return "formulas"
        else:
            return None


async def send(message, text, reply_markup=None, keep="_*"):
    text = await format(text, latex=False, markdown=False)
    if not text:
        return
    if (latex_t := latex_type(text)) == "document":
        text = await format_markdown(text, keep=None)
        await bot.send_message(message.chat.id, text, reply_markup=reply_markup)
    elif latex_t == "formulas":
        text = text.replace("```latex", "").replace("```", "")
        formulas = latex_math_found(text)
        for idx, f in enumerate(formulas):
            if idx:
                await send(
                    message,
                    text[formulas[idx - 1][1] + len(formulas[idx - 1][3][1]) : f[0]],
                )
            else:
                await send(message, text[: f[0]])
            await send_latex_formula(message, f)
        await send(message, text[formulas[-1][1] + len(formulas[-1][3][1]) :])
    else:
        text = await format(text, keep)
        await bot.send_message(message.chat.id, text, reply_markup=reply_markup)


def latex_math_found(text):
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
    for delim in delims:
        from_idx = 0
        start_idx = text.find(delim[0], from_idx)
        end_idx = text.find(delim[1], start_idx + len(delim[0]))
        while start_idx != -1 and end_idx != -1:
            if (
                end_idx - start_idx - len(delim[0]) >= LATEX_MIN_LEN
                or text[start_idx + len(delim[0]) : end_idx].count("\\") > 2
                or "begin" in delim[0]
            ):
                math_found.append(
                    [
                        start_idx,
                        end_idx,
                        text[start_idx + len(delim[0]) : end_idx],
                        delim,
                    ]
                )
            from_idx = end_idx + len(delim[1])
            start_idx = text.find(delim[0], from_idx)
            end_idx = text.find(delim[1], start_idx + len(delim[0]))
    return sorted(math_found, key=lambda x: x[0])


def paragraph_type(par):
    if par.find("```") == -1 or par.find("```") != par.rfind("```"):
        return "text"
    else:
        return "code"


async def process_delim(delim, par, message, response):
    await send(message, par[:delim])
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    response += par[:delim]
    par = par[delim:]
    return response, par


async def generate_completion(message):
    data = await read_data(message.from_user.username)
    stream = await client.chat.completions.create(
        model=GPT_MODEL, messages=data["messages"], temperature=0.5, stream=True
    )
    response = ""
    paragraph = ""
    curr_paragraph_type = "text"
    try:
        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                paragraph += chunk.choices[0].delta.content
                match curr_paragraph_type, paragraph_type(paragraph):
                    case "text", "text":
                        if "\n\n" in paragraph:
                            delim = paragraph.rfind("\n\n") + 2
                            response, paragraph = await process_delim(
                                delim, paragraph, message, response
                            )
                    case "text", "code":
                        curr_paragraph_type = "code"
                        delim = paragraph.rfind("```")
                        response, paragraph = await process_delim(
                            delim, paragraph, message, response
                        )
                    case "code", "text":
                        curr_paragraph_type = "text"
                        delim = paragraph.rfind("```") + 3
                        response, paragraph = await process_delim(
                            delim, paragraph, message, response
                        )
        await send(message, paragraph, keyboards.forget_keyboard)
        response += paragraph
    except (Exception, OpenAIError) as e:
        alert = await format_markdown(
            f"*ERROR:* {e}\n\n*USER:* {message.from_user.username}\n\n*LAST PROMPT:* {message.text}\n\n*COLLECTED RESPONSE:* {response}"
        )
        builder = InlineKeyboardBuilder()
        builder.add(
            types.InlineKeyboardButton(
                text=buttons[language(message)]["error"], callback_data="error"
            ),
        )
        await bot.send_message(OWNER_CHAT_ID, alert)
        await bot.send_message(message.chat.id, alert, reply_markup=builder.as_markup())
        await clear_handler(message)
    finally:
        await stream.close()
    return response


async def read_data(username) -> None:
    with open(f"data/{username}.json", "r") as f:
        data = json.load(f)
    return data


async def write_data(username, data) -> None:
    with open(f"data/{username}.json", "w") as f:
        json.dump(data, f)


async def lock(username):
    data = await read_data(username)
    data["lock"] = True
    await write_data(username, data)
    await asyncio.sleep(0.6)
    data = await read_data(username)
    data["lock"] = False
    await write_data(username, data)


async def update_user_data(message) -> bool:
    username = message.from_user.username
    data = await read_data(username)
    if data["balance"] < 0.001:
        await send_template_answer(message, "empty")
        alert = await format_markdown(
            f"*WARNING: @{username} has tried to use GPT with empty balance.*"
        )
        await bot.send_message(OWNER_CHAT_ID, alert)
        return False
    now = time.time()
    data["timestamps"].append(now)
    encoding = tiktoken.encoding_for_model("gpt-4o")
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
    data["balance"] -= data["tokens"] * FEE * GPT4O_INPUT_1K / 1000
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
    await write_data(username, data)
    if not data["lock"]:
        return True
    else:
        return False


def language(message):
    lang = message.from_user.language_code
    if lang is None or lang != "ru":
        lang = "en"
    return lang


async def send_template_answer(message, template, *args, reply_markup=None, keep="_*"):
    text = dialogues[language(message)][template]
    if len(args) != 0:
        text = text.format(*args)
    text = await format_markdown(text, keep=keep)
    await bot.send_message(message.chat.id, text, reply_markup=reply_markup)


async def authorized(message):
    if message.from_user.username not in BOT_USERS:
        await send_template_answer(
            message, "auth", reply_markup=keyboards.help_keyboard
        )
        return False
    return True


@dp.message(Command("start"))
async def start_handler(message: Message) -> None:
    await bot.set_my_commands(
        [
            types.BotCommand(command=key, description=value)
            for key, value in commands[language(message)].items()
        ]
    )
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
    text = await format_markdown(dialogues[language(message)]["help"][0])
    await bot.send_animation(
        message.chat.id,
        gifs["help"][0],
        caption=text,
        reply_markup=builder.as_markup(),
    )


@dp.message(Command("forget", "clear"))
async def clear_handler(message: Message) -> None:
    username = message.from_user.username
    if await authorized(message):
        data = await read_data(username)
        await send_template_answer(message, "forget", keep="_")
        data["messages"].clear()
        data["latex"].clear()
        data["timestamps"].clear()
        data["tokens"] = 0
        await write_data(username, data)


@dp.message(Command("balance"))
async def billing_handler(message: Message) -> None:
    if await authorized(message):
        builder = InlineKeyboardBuilder()
        builder.add(
            types.InlineKeyboardButton(
                text=buttons[language(message)]["back-to-help"],
                callback_data="help-0",
            ),
            types.InlineKeyboardButton(
                text=buttons[language(message)]["tokens"],
                callback_data="tokens",
            ),
        )
        username = message.from_user.username
        data = await read_data(username)
        text = await format_markdown(
            dialogues[language(message)]["balance"].format(
                round(data["balance"], 4),
                round(94 * data["balance"], 2),
                round(data["balance"] / GPT4O_OUTPUT_1K * 1000),
            )
        )
        await bot.send_animation(
            message.chat.id,
            gifs["balance"],
            caption=text,
            reply_markup=builder.as_markup(),
        )


@dp.message(Command("get_id"))
async def file_id_handler(message: Message) -> None:
    # file_id = message.animation.file_id
    file_id = message.video.file_id
    await send(message, file_id)


@dp.message(Command("add"))
async def add_handler(message: Message) -> None:
    if await authorized(message) and message.chat.id == OWNER_CHAT_ID:
        if len(message.text.split()) == 3 and float(message.text.split()[2]) >= 0:
            _, username, balance = message.text.split()
            if username in BOT_USERS:
                data = await read_data(username)
                data["balance"] += float(balance)
                await write_data(username, data)
                return
            else:
                init = {
                    "lock": False,
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


@dp.message(Command("rm", "remove", "delete"))
async def delete_handler(message: Message) -> None:
    if await authorized(message) and message.chat.id == OWNER_CHAT_ID:
        if len(message.text.split()) == 2 and message.text.split()[1] in BOT_USERS:
            _, username = message.text.split()
            BOT_USERS.remove(username)
            os.system(f"dotenv set TG_BOT_USERS {','.join(BOT_USERS)}")
            os.remove(f"data/{username}.json")
            return


@dp.message(Command("draw"))
async def image_generation_handler(message: Message) -> None:
    if await authorized(message) and await update_user_data(message):
        try:
            username = message.from_user.username
            prompt = message.text.split("draw")[1].strip()
            if len(prompt) == 0:
                await send_template_answer(message, "draw")
                return
            async with ChatActionSender.upload_photo(bot=bot, chat_id=message.chat.id):
                image_url = await generate_image(prompt)
            builder = InlineKeyboardBuilder()
            builder.add(
                types.InlineKeyboardButton(
                    text=buttons[language(message)]["redraw"], callback_data="redraw"
                ),
            )
            await bot.send_photo(
                chat_id=message.chat.id,
                photo=image_url,
                reply_markup=builder.as_markup(),
            )
            data = await read_data(username)
            data["balance"] -= FEE * DALLE3_OUTPUT
            await write_data(username, data)
        except (Exception, OpenAIError) as e:
            await send_template_answer(message, "block")
            await clear_handler(message)


@dp.message()
async def universal_handler(message: Message) -> None:
    if await authorized(message) and await update_user_data(message):
        await lock(message.from_user.username)
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            response = await generate_completion(message)
        data = await read_data(message.from_user.username)
        data["timestamps"].append(time.time())
        data["messages"].append({"role": "system", "content": response})
        encoding = tiktoken.encoding_for_model("gpt-4o")
        data["tokens"] += len(encoding.encode(response))
        data["balance"] -= len(encoding.encode(response)) * FEE * GPT4O_OUTPUT_1K / 1000
        await write_data(message.from_user.username, data)


@dp.callback_query(F.data == "redraw")
async def redraw_handler(callback: types.CallbackQuery):
    username = callback.from_user.username
    message = callback.message
    file_name = f"photos/{username}"
    async with ChatActionSender.upload_photo(bot=bot, chat_id=message.chat.id):
        await bot.download(message.photo[-1], destination=file_name + ".jpg")
        media = await variate_image(file_name)
    await bot.send_media_group(message.chat.id, media)
    data = await read_data(username)
    data["balance"] -= 2 * FEE * DALLE2_OUTPUT
    await write_data(username, data)


@dp.callback_query(F.data == "error")
async def error_message_handler(callback: types.CallbackQuery):
    text = format_markdown(dialogues[language(callback)]["error"])
    await bot.send_message(callback.message.chat.id, text)


@dp.callback_query(F.data == "balance")
async def payment_redirection_handler(callback: types.CallbackQuery):
    message = callback.message
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(
            text=buttons[language(callback)]["back-to-help"],
            callback_data="help-0",
        ),
        types.InlineKeyboardButton(
            text=buttons[language(callback)]["tokens"],
            callback_data="tokens",
        ),
    )
    data = await read_data(callback.from_user.username)
    text = await format_markdown(
        dialogues[language(callback)]["balance"].format(
            round(data["balance"], 4),
            round(94 * data["balance"], 2),
            round(data["balance"] / GPT4O_OUTPUT_1K * 1000),
        )
    )
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=gifs["balance"],
            caption=text,
        ),
        message.chat.id,
        message.message_id,
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data == "tokens")
async def tokens_description_handler(callback: types.CallbackQuery):
    message = callback.message
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(
            text="<- " + buttons[language(callback)]["back-to-balance"],
            callback_data="back-to-balance",
        ),
    )
    text = await format_markdown(dialogues[language(callback)]["tokens"])
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=gifs["tokens"],
            caption=text,
        ),
        message.chat.id,
        message.message_id,
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data == "back-to-balance")
async def back_to_payment_handler(callback: types.CallbackQuery):
    message = callback.message
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(
            text=buttons[language(callback)]["back-to-help"],
            callback_data="help-0",
        ),
        types.InlineKeyboardButton(
            text=buttons[language(callback)]["tokens"],
            callback_data="tokens",
        ),
    )
    data = await read_data(callback.from_user.username)
    text = await format_markdown(
        dialogues[language(callback)]["balance"].format(
            round(data["balance"], 4),
            round(94 * data["balance"], 2),
            round(data["balance"] / GPT4O_OUTPUT_1K * 1000),
        ),
    )
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=gifs["balance"],
            caption=text,
        ),
        message.chat.id,
        message.message_id,
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data.startswith("help-"))
async def help_handler(callback: types.CallbackQuery):
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
    text = await format_markdown(
        dialogues[language(callback)]["help"][h_idx],
    )
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION, media=gifs["help"][h_idx], caption=text
        ),
        message.chat.id,
        message.message_id,
        reply_markup=builder.as_markup(),
    )


@dp.callback_query(F.data == "latex-original")
async def latex_handler(callback: types.CallbackQuery):
    message = callback.message
    builder = InlineKeyboardBuilder()
    builder.add(
        types.InlineKeyboardButton(
            text=buttons[language(callback)]["hide"], callback_data="hide"
        ),
    )
    data = await read_data(callback.from_user.username)
    text = data["latex"].get(
        str(message.message_id), dialogues[language(callback)]["forgotten"]
    )
    text = await format_markdown(text)
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
        text = await format_markdown(dialogues[language(callback)]["old"])
        await bot.send_message(
            message.chat.id, text, reply_to_message_id=message.message_id
        )


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
