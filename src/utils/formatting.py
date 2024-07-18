import re
import os
import urllib.parse
import cairosvg
import base64
from io import BytesIO
from PIL import Image

from src.templates.scripts import scripts
from src.utils.analytics.logging import logged
from src.utils.globals import (
    bot,
    PAR_MAX_LEN,
    INCOMPLETE_CODE_PATTERN,
    LATEX_BODY_PATTERN,
    CODE_PATTERN,
    ESCAPED_IN_C_DEFAULT,
    PRE_PATTERN,
    CODE_AND_PRE_PATTERN,
    ESCAPED_IN_O_DEFAULT,
    ESCAPED_IN_O_QUOTE,
    ESCAPED_IN_O_SINGLE,
    ESCAPED_IN_O_TIGHT,
    LATEX_PATTERN,
    XTR2USD,
    USD2TOKENS,
    STORE_COMMISSION,
    TELEGRAM_COMMISSSION,
    OPENAI_REFILL_LOSS,
    ROYALTIES,
)


def encode_image(image_path, max_image=2048):
    with Image.open(image_path) as img:
        width, height = img.size
        max_dim = max(width, height)
        if max_dim > max_image:
            scale_factor = max_image / max_dim
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            img = img.resize((new_width, new_height))

        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        return img_str


def svg2jpg(svg_file_path, output_file_path):
    cairosvg.svg2png(
        url=svg_file_path,
        write_to=output_file_path,
        output_width=512,
        output_height=128,
    )


def latex2url(formula):
    body = LATEX_BODY_PATTERN.search(formula)[1]
    image_url = body.replace("\n", "").replace("&", ",").replace("\\\\", ";\,")
    image_url = " ".join([elem for elem in image_url.split(" ") if elem])
    image_url = image_url.replace(" ", "\,\!")
    return "https://math.vercel.app?from=" + urllib.parse.quote(image_url)


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


def format_tg_msg(text, f_idx=0):
    if not text:
        return text
    else:
        return format_markdown(format_latex(text, f_idx))


@logged
async def send_template_answer(message, cls, name, *args, reply_markup=None):
    from src.utils.validations import language

    text = scripts[cls][name][language(message)]
    if len(args) != 0:
        text = text.format(*args)
    await message.answer(format_tg_msg(text), reply_markup=reply_markup)


def is_incomplete(par):
    return INCOMPLETE_CODE_PATTERN.search(par).end() != len(par)


def cut_tg_msg(text):
    if len(text) < PAR_MAX_LEN:
        head = text
        tail = None
        return head, tail
    if "\n\n" in text[:PAR_MAX_LEN]:
        delim = text[:PAR_MAX_LEN].rfind("\n\n")
        dlen = len("\n\n")
    elif "\n" in text[:PAR_MAX_LEN]:
        delim = text[:PAR_MAX_LEN].rfind("\n")
        dlen = len("\n")
    elif " " in text[:PAR_MAX_LEN]:
        delim = text[:PAR_MAX_LEN].rfind(" ")
        dlen = len(" ")
    else:
        delim = PAR_MAX_LEN
        dlen = len("")
    if is_incomplete(text[:delim]):
        if text.startswith("```"):
            cblock_begin = text[: text.find("\n") + 1]
        else:
            tmp = text[:delim].rfind("\n```")
            cblock_begin = text[tmp + 1 : text.find("\n", tmp + 1) + 1]
        cblock_end = "\n```"
        head = text[:delim] + cblock_end
        tail = cblock_begin + text[delim + dlen :]
    else:
        head = text[:delim]
        tail = text[delim + dlen :]
    return head, tail


def nformulas_before(head, text):
    return len([f for f in find_latex(text[: text.find(head)]) if latex_significant(f)])


def xtr2usd(xtr: int | str | float) -> float:
    return (
        float(xtr)
        * XTR2USD
        * (1 - STORE_COMMISSION - TELEGRAM_COMMISSSION)
        * (1 - OPENAI_REFILL_LOSS - ROYALTIES)
    )


def usd2tok(usd: int | str | float) -> str:
    return f"{round(float(usd) * USD2TOKENS):,}"


async def get_image_url(message):
    from src.utils.formatting import encode_image

    if message.photo:
        image_path = (
            f"src/utils/temp/images/{message.from_user.id}-{message.message_id}.jpg"
        )
        await bot.download(message.photo[-1], destination=image_path)
        url = encode_image(image_path)
        os.remove(image_path)
        return url
    else:
        return None


def get_message_text(message):
    text = message.md_text
    if message.invoice:
        text = f"{message.invoice.title}\n{message.invoice.description}"
    if message.reply_to_message:
        text = f"{get_message_text(message.reply_to_message)}\n\n{text}"
    return text
