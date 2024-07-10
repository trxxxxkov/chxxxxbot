from aiogram import types

help_keyboard = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="/help")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)
