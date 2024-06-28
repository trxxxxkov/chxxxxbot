from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import types

from src.templates.keyboards.buttons import buttons


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
