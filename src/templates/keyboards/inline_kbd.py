"""Telegram inline kyboards templates."""

from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.utils.formatting import find_latex, latex_significant
from src.templates.scripts import scripts


def inline_kbd(buttons: dict, lang: str | None = None) -> InlineKeyboardMarkup:
    """Return an inline keyboard based on provided buttons and callbacks.

    Args:
        buttons: a dictionary which keys are either used directly as buttons
            text or as a key in scripts structure depending on whether the lang is
            provided and values are always callback data for a corresponding button.
        lang: user's language code. If is not None, the buttons text is obtained
            from scripts structure that is used for localization of pre-defined dialogs.

    Returns:
        InlineKeyboardMarkup - ready to use inline keyboard.
    """
    keyboard = InlineKeyboardBuilder()
    if lang is not None:
        for button, callback in buttons.items():
            keyboard.add(
                InlineKeyboardButton(
                    text=scripts["bttn"][button][lang], callback_data=callback
                ),
            )
    else:
        for button, callback in buttons.items():
            keyboard.add(InlineKeyboardButton(text=button, callback_data=callback))
    # The number of keys in a row is restricted specifically for latex_inline_kbd
    # which can produce keyboards with more then 10 buttons with short ("#x:") text.
    keyboard.adjust(5)
    return keyboard.as_markup()


def latex_inline_kbd(text: str, f_idx: int = 0) -> InlineKeyboardMarkup:
    """Return a keyboard with a button for each latex formula found in the text.

    Buttons in the keyboard have text like this: #X, where X - is a formula's
    index in the current response.

    Args:
        text: the text where latex formulas are searched.
        f_idx: index to start counting formulas from. It is calculated based
            on the formuals found in the previous messages that are part of the
            current response."""
    if fnum := len([f for f in find_latex(text) if latex_significant(f)]):
        kbd = inline_kbd({f"#{f_idx+1+i}": f"latex-{i}" for i in range(fnum)})
    else:
        kbd = None
    return kbd


def empty_balance_kbd(message):
    """Return a keyboard with three payment buttons for 1,10,100 stars invoice."""
    from src.utils.validations import language

    npay = scripts["bttn"]["try payment"][language(message)][:-1]
    kbd = InlineKeyboardBuilder()
    kbd.add(
        InlineKeyboardButton(text=npay + "1", callback_data="try payment 1"),
        InlineKeyboardButton(text=npay + "10", callback_data="try payment 10"),
        InlineKeyboardButton(text=npay + "100", callback_data="try payment 100"),
    )
    return kbd.as_markup()
