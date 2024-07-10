from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import types

from src.utils.formatting import find_latex, latex_significant
from src.templates.scripts import scripts


def inline_kbd(keys, lang=None):
    keyboard = InlineKeyboardBuilder()
    if lang is not None:
        for button, callback in keys.items():
            keyboard.add(
                types.InlineKeyboardButton(
                    text=scripts["bttn"][button][lang], callback_data=callback
                ),
            )
    else:
        for button, callback in keys.items():
            keyboard.add(
                types.InlineKeyboardButton(text=button, callback_data=callback),
            )
    return keyboard.as_markup()


def latex_inline_kbd(text, f_idx=0):
    if fnum := len([f for f in find_latex(text) if latex_significant(f)]):
        kbd = inline_kbd({f"#{f_idx+1+i}": f"latex-{i}" for i in range(fnum)})
    else:
        kbd = None
    return kbd
