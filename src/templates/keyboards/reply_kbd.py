"""Pre-built Telegram reply keyboards."""

from aiogram import types

# Suggest /help command
help_kbd = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="/help")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)
