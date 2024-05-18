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
from aiogram.exceptions import TelegramBadRequest

import keyboards
from dialogues import dialogues
from commands import commands
from gifs import gifs
from buttons import buttons

load_dotenv()

OWNER_CHAT_ID = 791388236
BOT_TOKEN = getenv("TG_BOT_TOKEN")
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
PAR_MIN_LEN = 150

INITIAL_USER_DATA = {
    "lock": False,
    "messages": [],
    "latex": {},
    "timestamps": [],
    "tokens": 0,
    "balance": 0,
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


def format_markdown(text, code_entity=False, strict=False):
    if strict:
        strict_escape = "\\_*[]()`~>#+-=|}{.!"
        for char in strict_escape:
            text = text.replace(char, f"\\{char}")
    elif code_entity:
        code_entity_escape = "\\`"
        for char in code_entity_escape:
            text = text.replace(char, f"\\{char}")
    else:
        code_l = text.find("```")
        code_r = text.rfind("```")
        if code_l != code_r:
            formatted_l = format_markdown(text[:code_l])
            formatted_r = format_markdown(text[code_r + 3 :])
            formatted_code = format_markdown(
                text[code_l + 3 : code_r], code_entity=True
            )
            text = formatted_l + "```" + formatted_code + "```" + formatted_r
        else:
            pre_l = text.find("`")
            pre_r = text.find("`", pre_l + 1)
            if pre_l != pre_r and text.count("`") % 2 == 0:
                formatted_l = format_markdown(text[:pre_l])
                formatted_r = format_markdown(text[pre_r + 1 :])
                formatted_pre = format_markdown(
                    text[pre_l + 1 : pre_r], code_entity=True
                )
                text = formatted_l + "`" + formatted_pre + "`" + formatted_r
            else:
                must_escape = "\\[]()`>#+-=|}{.!"
                may_escape = "_*~"
                for char in must_escape:
                    text = text.replace(char, f"\\{char}")
                for char in may_escape:
                    if (text.count(char) - text.count(f"\r{char}")) % 2 != 0:
                        text = text.replace(f"\r{char}", char).replace(
                            char, f"\\{char}"
                        )
                    else:
                        text = text.replace(f"\r{char}", f"\\{char}")
    return text


def inline_latex_found(text):
    delims = [
        ["$$", "$$"],
        ["\\[", "\\]"],
        ["\\(", "\\)"],
    ]
    delims_idx = []
    for delim in delims:
        l = text.find(delim[0])
        r = text.find(delim[1], l)
        while l != -1 and r != -1:
            delims_idx.append([l, r])
            l = text.find(delim[0], r + 2)
            r = text.find(delim[1], l)
    return delims_idx


def format_latex(text):
    delim_idx = inline_latex_found(text)
    text = list(text)
    for char in "_*":
        char_idx = [i for i in range(len(text)) if text[i] == char]
        for ci in char_idx:
            for di in delim_idx:
                if ci in range(*di):
                    text[ci] = f"\r{char}"
                    break
    text = "".join(text)
    for delim in ["$$", "\\[", "\\]", "\\(", "\\)"]:
        text = text.replace(delim, "*")
    return text


def format_gpt(text):
    if text[0] == ",":
        text = text[1:]
    lines = text.replace("**", "*").split("\n")
    for i in range(len(lines)):
        if lines[i].strip() in ".,?!-:;":
            lines[i] = ""
    text = "\n".join([elem for elem in lines])
    if text.replace("\n", ""):
        return text
    else:
        return ""


def format(text, *, latex=True, gpt=True, markdown=True, strict=False):
    if text and latex and not strict and "`" not in text:
        text = format_latex(text)
    if text and gpt and not strict:
        text = format_gpt(text)
    if text and markdown:
        text = format_markdown(text, strict=strict)
    return text


def get_latex_image_url(formula):
    image_url = formula[2].replace("\n", "").replace("&", ",").replace("\\\\", ";\,")
    image_url = (
        " ".join([elem for elem in image_url.split(" ") if elem])
        .replace(" ", "\,\!")
        .replace(" ", "\,\!")
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


async def send(message, text, reply_markup=None):
    if (latex_t := latex_type(text)) == "document":
        text = format(text, latex=False, gpt=False)
        if text:
            await bot.send_message(
                message.chat.id,
                text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
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
        text = format(text)
        if text:
            await bot.send_message(
                message.chat.id,
                text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )


def latex_math_found(text):
    delims = [
        # ["$", "$"],
        ["$$", "$$"],
        ["\\[", "\\]"],
        ["\\(", "\\)"],
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
    par = par.replace(" ", "")
    if (
        par.startswith("```")
        and par.count("\n```") == 0
        or not par.startswith("```")
        and par.count("\n```") == 1
    ):
        return "code"
    else:
        return "text"


async def process_delim(delim, par, message, response):
    await send(message, par[:delim])
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    response += par[:delim]
    par = par[delim:]
    return response, par


async def generate_completion(message):
    data = await read_user_data(message.from_user.id)
    stream = await client.chat.completions.create(
        model=GPT_MODEL, messages=data["messages"], temperature=0.5, stream=True
    )
    response = ""
    par = ""
    cur_par_type = "text"
    try:
        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                par += chunk.choices[0].delta.content
                match cur_par_type, paragraph_type(par):
                    case "text", "text":
                        if (
                            "\n\n" in par
                            and len(par[: par.rfind("\n\n")]) > PAR_MIN_LEN
                            and par[par.rfind("\n\n") - 1] != "`"
                        ):
                            delim = par.rfind("\n\n") + 2
                            response, par = await process_delim(
                                delim, par, message, response
                            )
                    case "text", "code":
                        cur_par_type = "code"
                        delim = par.rfind("```")
                        response, par = await process_delim(
                            delim, par, message, response
                        )
                    case "code", "text":
                        cur_par_type = "text"
                        delim = par.rfind("```") + 3
                        response, par = await process_delim(
                            delim, par, message, response
                        )
        await send(message, par, keyboards.forget_keyboard)
        response += par
    except (Exception, OpenAIError) as e:
        alert = format(
            f"*ERROR:* {e}\n\n*USER:* {message.from_user.username}\n\n*LAST PROMPT:* {message.text}\n\n*COLLECTED RESPONSE:* {response}"
        )
        await bot.send_message(OWNER_CHAT_ID, alert)
        inline = inline_keyboard({"error": "error"}, language(message))
        await bot.send_message(message.chat.id, alert, reply_markup=inline)
        await clear_handler(message)
    finally:
        await stream.close()
    return response


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


async def cost(message):
    price = 0
    encoding = tiktoken.encoding_for_model("gpt-4o")
    data = await read_user_data(message.from_user.id)
    if message.photo:
        pre_prompt = dialogues[language(message)]["vision-pre-prompt"]
        text = message.caption if message.caption else pre_prompt
        price += FEE * GPT4VISION_INPUT
    else:
        text = message.text
    tokens = data["tokens"] + len(encoding.encode(text))
    price += tokens * FEE * GPT4O_INPUT_1K / 1000
    return price, tokens, text


async def update_user_data(message) -> bool:
    message_cost, tokens, text = await cost(message)
    data = await read_user_data(message.from_user.id)
    if data["balance"] - message_cost < 0:
        await send_template_answer(message, "empty")
        return False
    now = time.time()
    data["timestamps"].append(now)
    if message.photo:
        image_path = f"photos/{message.from_user.id}.jpg"
        await bot.download(message.photo[-1], destination=image_path)
        data_url = local_image_to_data_url(image_path)
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
    else:
        data["messages"].append({"role": "user", "content": message.text})
    data["tokens"] = tokens
    data["balance"] -= message_cost
    # Remove outdated messages from the chat history
    for i in range(len(data["timestamps"])):
        if now - data["timestamps"][i] < GPT_MEMORY_SEC:
            data["timestamps"] = data["timestamps"][i:]
            data["messages"] = data["messages"][i:]
            break
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
async def top_up_handler(message: Message) -> None:
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
            if funds.startswith(("+", "-")) and funds[1:].isnumeric():
                user_data["balance"] += float(funds)
                await write_user_data(user, user_data)
                await send(message, "_Done._")
            elif funds.isnumeric():
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
            await top_up_handler(message)


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
        gifs["help"][0],
        caption=text,
        reply_markup=builder.as_markup(),
    )


@dp.message(Command("forget", "clear"))
async def clear_handler(message: Message) -> None:
    data = await read_user_data(message.from_user.id)
    await send_template_answer(message, "forget")
    data["messages"].clear()
    data["latex"].clear()
    data["timestamps"].clear()
    data["tokens"] = 0
    await write_user_data(message.from_user.id, data)


@dp.message(Command("balance"))
async def billing_handler(message: Message) -> None:
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
        gifs["balance"],
        caption=text,
        reply_markup=markup,  # builder.as_markup(),
    )


@dp.message(Command("draw"))
async def image_generation_handler(message: Message) -> None:
    if await update_user_data(message):
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
            data["balance"] -= FEE * DALLE3_OUTPUT
            await write_user_data(message.from_user.id, data)
        except (Exception, OpenAIError) as e:
            await send_template_answer(message, "block")
            await clear_handler(message)


@dp.message()
async def universal_handler(message: Message) -> None:
    if await update_user_data(message):
        await lock(message.from_user.id)
        async with ChatActionSender.typing(message.chat.id, bot):
            response = await generate_completion(message)
        data = await read_user_data(message.from_user.id)
        data["timestamps"].append(time.time())
        data["messages"].append({"role": "system", "content": response})
        encoding = tiktoken.encoding_for_model("gpt-4o")
        data["tokens"] += len(encoding.encode(response))
        data["balance"] -= len(encoding.encode(response)) * FEE * GPT4O_OUTPUT_1K / 1000
        await write_user_data(message.from_user.id, data)


@dp.callback_query(F.data == "redraw")
async def redraw_handler(callback: types.CallbackQuery):
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
async def error_message_handler(callback: types.CallbackQuery):
    text = dialogues[language(callback)]["error"]
    await send(callback.message, text)


@dp.callback_query(F.data == "balance")
async def payment_redirection_handler(callback: types.CallbackQuery):
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
            media=gifs["balance"],
            caption=text,
        ),
        message.chat.id,
        message.message_id,
        reply_markup=inline,
    )


@dp.callback_query(F.data == "tokens")
async def tokens_description_handler(callback: types.CallbackQuery):
    message = callback.message
    text = format(dialogues[language(callback)]["tokens"])
    inline = inline_keyboard({"balance": "balance"}, language(message))
    await bot.edit_message_media(
        types.InputMediaAnimation(
            type=InputMediaType.ANIMATION,
            media=gifs["tokens"],
            caption=text,
        ),
        message.chat.id,
        message.message_id,
        reply_markup=inline,
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
    text = format(dialogues[language(callback)]["help"][h_idx])
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
    data = await read_user_data(callback.from_user.id)
    text = data["latex"].get(
        str(message.message_id), dialogues[language(callback)]["forgotten"]
    )
    text = format(text, latex=False)
    inline = inline_keyboard({"hide": "hide"}, language(callback))
    await bot.send_message(
        message.chat.id,
        text,
        reply_to_message_id=message.message_id,
        reply_markup=inline,
    )


@dp.callback_query(F.data == "hide")
async def hide_handler(callback: types.CallbackQuery):
    message = callback.message
    deleted = await bot.delete_message(message.chat.id, message.message_id)
    if not deleted:
        text = format(dialogues[language(callback)]["old"])
        await bot.send_message(
            message.chat.id, text, reply_to_message_id=message.message_id
        )


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
