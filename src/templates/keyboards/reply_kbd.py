from aiogram import types

help_keyboard = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="/help")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

forget_keyboard = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="/as_file")],
        [types.KeyboardButton(text="/forget")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    one_time_keyboard=True,
)
