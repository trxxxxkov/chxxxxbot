import re
import urllib.parse
import cairosvg
import base64
from mimetypes import guess_type

from src.templates.scripts import scripts
from src.utils.analytics.logging import logged
from src.templates.keyboards.inline_kbd import inline_kbd
from src.utils.globals import (
    bot,
    PAR_MAX_LEN,
    PAR_MIN_LEN,
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


def format(text, f_idx=0):
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
    await send(message, text, reply_markup=reply_markup)


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
