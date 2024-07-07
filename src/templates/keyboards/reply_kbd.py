from aiogram import types

help_keyboard = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="/help")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

last_msg_keyboard = types.ReplyKeyboardMarkup(
    keyboard=[
        [types.KeyboardButton(text="/forget"), types.KeyboardButton(text="/as_file")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)
