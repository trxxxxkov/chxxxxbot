"""Functions for text parsing, formatting and data convertions"""

import re
import os
import urllib.parse
import cairosvg
import base64
from io import BytesIO
from PIL import Image

from aiogram.types import Message, InlineKeyboardMarkup

from src.templates.scripted_dialogues import dialogues
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


def encode_image(image_path: str, max_image: int = 2048) -> str:
    """Convert local image into url using base64 encoding"""
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


def svg2jpg(svg_file_path: str, output_file_path: str) -> None:
    """Convert local svg image to local jpg image.

    The function is needed to send latex formulas converted to svg by
    https://github.com/uetchy/math-api because Telegram does not support svg images.
    """
    cairosvg.svg2png(
        url=svg_file_path,
        write_to=output_file_path,
        output_width=512,
        output_height=128,
    )


def latex2url(formula: str) -> str:
    """Format latex formula for usage in https://github.com/uetchy/math-api service.

    Args:
        formula: string that contains latex formula with correspoding delimiters.

    Returns:
        image_url - url string for svg image with the formula.
    """
    body = LATEX_BODY_PATTERN.search(formula)[1]
    # The math-api service does not support certain characters, so substitute them
    image_url = body.replace("\n", "").replace("&", ",").replace("\\\\", ";\,")
    # Get rid of extra spaces
    image_url = " ".join([elem for elem in image_url.split(" ") if elem])
    # Substitute " " with latex-determined spaces
    image_url = image_url.replace(" ", "\,\!")
    return "https://math.vercel.app?from=" + urllib.parse.quote(image_url)


def escaped(text: str, pattern: str | re.Pattern = ".") -> str:
    """Add "\\" to any character in the text that matches the pattern.

    Args:
        text: a text to escape characters in.
        pattern: re pattern which matches characters that must be escaped.

    Returns: text with escaped characters.
    """
    if isinstance(pattern, re.Pattern):
        return pattern.sub(lambda m: "".join(["\\" + i for i in m[0]]), text)
    else:
        return re.sub(
            pattern,
            lambda m: "".join(["\\" + i for i in m[0]]),
            text,
            flags=re.DOTALL,
        )


def escaped_last(pattern: str | re.Pattern, text: str) -> str:
    """Add "\\" to the last characters that matches pattern.

    Args:
        pattern: re pattern which matches characters that must be escaped.
        text: a text to escape characters in.

    Returns: text with "\\" added to the last match of the provided pattern.
    """
    if isinstance(pattern, re.Pattern):
        for m in pattern.finditer(text):
            pass
        else:
            return text[: m.start()] + escaped(text[m.start() :], pattern=pattern)
    for m in re.finditer(pattern, text):
        pass
    else:
        return text[: m.start()] + escaped(text[m.start() :], pattern=pattern)


def format_markdown(text: str) -> str:
    """Escape if neccessary special characters of Telegam's markdownV2 syntax.

    Escape minimal amount of special characters (all special characters are listed
    here: https://core.telegram.org/bots/api#markdownv2-style). Not all modes of
    formatting are supported. All characters in the unsupported formatting modes
    are escaped.

    List of unsupported formatting modes:
     - inline URL;
     - mention of a user;
     - expandable block of quotation;
    """
    # Split text into code blocks and non-code blocks and format code blocks.
    t_split = CODE_PATTERN.split(text)
    c_entities = CODE_PATTERN.findall(text)
    text = t_split[0]
    for idx, c in enumerate(c_entities):
        # Add code block dilimiter for a code block entity
        c = f"```{escaped(c[3:-3], pattern=ESCAPED_IN_C_DEFAULT)}```"
        c_entities[idx] = c
        # Join formatted code blocks back with the untouched text blocks.
        text += c_entities[idx] + t_split[idx + 1]

    # Split text into inline code blocks and non-code blocks and format inline
    # code blocks.
    t_split = PRE_PATTERN.split(text)
    p_entities = PRE_PATTERN.findall(text)
    text = t_split[0]
    for idx, p in enumerate(p_entities):
        p = f"`{escaped(p[1:-1], pattern=ESCAPED_IN_C_DEFAULT)}`"
        p_entities[idx] = p
        text += p_entities[idx] + t_split[idx + 1]

    # Split text into code blocks (aither inline or not) and non-code blocks and
    # format non-code (other entities) blocks.
    t_split = CODE_AND_PRE_PATTERN.findall(text) + [""]
    o_entities = CODE_AND_PRE_PATTERN.split(text)
    text = ""
    for idx, o in enumerate(o_entities):
        # GPT-4 sometime uses "**" instead of "*" to mark bold text
        o = o.replace("**", "*")
        o = escaped(o, pattern=ESCAPED_IN_O_DEFAULT)
        o = escaped(o, pattern=ESCAPED_IN_O_TIGHT)
        o = escaped(o, pattern=ESCAPED_IN_O_QUOTE)
        o = escaped(o, pattern=ESCAPED_IN_O_SINGLE)
        paired = ["*", "_", "__", "~", "||"]
        for char in paired:
            # Only the last unpaired pattern match is escaped, if any.
            if (o.count(char) - o.count(escaped(char))) % 2 != 0:
                o = escaped_last(rf"(?<!\\){re.escape(char)}", o)
        o_entities[idx] = o
        text += o_entities[idx] + t_split[idx]
    return re.sub(r"\\\\+", lambda m: "\\\\\\", text)


def find_latex(text: str) -> list[str]:
    """Find latex formulas outside of any pre-formatted code blocks."""
    other = CODE_AND_PRE_PATTERN.split(text)
    result = []
    for o in other:
        result += LATEX_PATTERN.findall(o)
    return result


def latex_significant(latex: str) -> bool:
    """Mark latex formula as "significant if it's long or difficult enough.

    Mark latex formulas that will be later suggested to user for convertion into
    image.

    Args:
        latex: latex formula to consider.
    """
    multiline = "begin" in latex and "end" in latex
    tricky = len(re.findall(r"\\\w+", latex)) >= 2
    return multiline or tricky


def format_latex(text: str, f_idx: int = 0) -> str:
    """Add "#4"-like indexes to the formulas that are long or difficult enough.

    Args:
        text: text to format formulas in.
        f_idx: number of latex formulas in previous parts of the response. If
            the provided text piece is not the first one in the prompt, f_idx != 0.
    """
    latex = find_latex(text)
    start_from = 0
    for formula in latex:
        start_from = text.find(formula, start_from)
        if latex_significant(formula):
            new_f = f"*#{f_idx + 1}:*\n`{formula}`"
            f_idx += 1
        else:
            new_f = f"`{formula}`"
        text = text[:start_from] + text[start_from:].replace(formula, new_f, 1)
        start_from += len(formula)
    return text


def format_tg_msg(text: str, f_idx: int = 0) -> str:
    """Format text before send it to user.

    Args:
        text: a text to format.
        f_idx: number of latex formulas in previous parts of the response. If
            the provided text piece is not the first one in the prompt, f_idx != 0.
    """
    if not text:
        return text
    else:
        return format_markdown(format_latex(text, f_idx))


@logged
async def send_template_answer(
    message: Message,
    cls: str,
    name: str,
    *args,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    """Send message with pre-defined text obtained from dialogues structure.

    The structure is a dictionary of texts divided into classes, each have texts
    written in multiple languages.

    Args:
        message: a user's prompt that requires an answer.
        cls: scripted message class. Must be one of "doc", "info", "err", "bttn"
            and "other".
        name: name of the scripted message inside given class.
        *args: arguments for texts that are formatting strings.
        reply_markup: inline keyboard that should be attached to the message.
    """
    from src.utils.validations import language

    text = dialogues[cls][name][language(message)]
    if len(args) != 0:
        text = text.format(*args)
    await bot.send_message(
        message.from_user.id, format_tg_msg(text), reply_markup=reply_markup
    )


def is_incomplete(text: str) -> bool:
    """Check if the provided text ends with an incomplete code block.

    If text has opening "```" or "`" for which the corresponding ending "```"
    or "`" is absent, it is considered incomplete. Only those "```" and "`"
    which are surrounded with specific context are considered opening.
    """
    return INCOMPLETE_CODE_PATTERN.search(text).end() != len(text)


def cut_tg_msg(text: str) -> tuple[str, str | None]:
    """Cut the first PAR_MAX_LEN characters from the text.

    The text is split by one of the delimiters (in descending order of priority:
    "\n\n", "\n", " ", text[PAR_MAX_LEN]; If a code block is split, it will be
    repaired with "```" in both 'head' and 'tail' which are the result of the cut.
    """
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
        # If a code block is split, "```" will be appended to the 'head' and
        # "```<programming lang name>" will be prepended to the 'tail' so they
        # will contain correct code blocks.
        if text.startswith("```"):
            # cblock_begin is "```<programming lang name>"
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


def nformulas_before(head: str, text: str) -> int:
    """Return amount of long latex formulas found in text before the 'head' piece.

    Args:
        head: a part of the text before which formulas are searched for in text.
        text: a text that contains 'head' where formulas are searched for in.
    """
    return len([f for f in find_latex(text[: text.find(head)]) if latex_significant(f)])


def xtr2usd(xtr: int | str | float) -> float:
    """Convertion from Telegram Stars to USD with all commissions included."""
    return (
        float(xtr)
        * XTR2USD
        * (1 - STORE_COMMISSION - TELEGRAM_COMMISSSION)
        * (1 - OPENAI_REFILL_LOSS - ROYALTIES)
    )


def usd2tok(usd: int | str | float) -> str:
    """Convertion from USD on users balance to tokens with pretty formating.

    The result is a string with numbers splitted by thousands: "4,444,444,444".
    """
    return f"{round(float(usd) * USD2TOKENS):,}"


async def get_image_url(message: Message) -> str | None:
    """Extract image from message and convert it to url with base64 encoding."""
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


def get_message_text(message: Message) -> str:
    """Extract text from message, including text from replied message."""
    text = message.md_text
    if message.invoice:
        text = f"{message.invoice.title}\n{message.invoice.description}"
    if message.reply_to_message:
        text = f"{get_message_text(message.reply_to_message)}\n\n{text}"
    return text
