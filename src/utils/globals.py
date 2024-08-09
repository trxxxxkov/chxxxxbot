"""Storage for bot object, openai client and global constants"""

import re
from os import getenv

from openai import AsyncOpenAI

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Telegram Bot token obtained from @BotFather
with open("/run/secrets/bot_token") as f:
    BOT_TOKEN = f.read().strip()

# OpenAI API token
with open("/run/secrets/openai_token") as f:
    OPENAI_TOKEN = f.read().strip()

# Secret used in incoming https requests authentication
with open("/run/secrets/webhook_secret") as f:
    WEBHOOK_SECRET = f.read().strip()

# Postgresql database password
with open("/run/secrets/db_password") as f:
    DATABASE_PASSWORD = f.read().strip()


WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = 8080
WEBHOOK_PATH = "/app/webhooks/"
BASE_WEBHOOK_URL = f"https://{getenv('NGINX_HOST')}"

# Telegram's user ID of the bot's owner
OWNER_TG_ID = getenv("OWNER_TG_ID")
# List of users with access to admin commands
PRIVILEGED_USERS = [OWNER_TG_ID]
DATABASE_NAME = getenv("POSTGRES_DB")
DATABASE_USER = getenv("POSTGRES_USER")
# Name of the webserver service in docker compose
DATABASE_HOST = "pgdb"
DATABASE_PORT = "5432"

# psycopg connection string
DSN = f"host={DATABASE_HOST} \
        port={DATABASE_PORT} \
        dbname={DATABASE_NAME} \
        user={DATABASE_USER} \
        password={DATABASE_PASSWORD}"

# Time in seconds which user's dialogs with GPT-4 are stored.
GPT_MEMORY_SEC = 7200
# Price in USD for an input token for GPT-4o
GPT4O_IN_USD = 0.0025 / 1000
# Price in USD for an output token for GPT-4o
GPT4O_OUT_USD = 0.01 / 1000
# Price in USD for an image recognition for GPT
VISION_USD = 0.004
# Price in USD for an image generation for DALLE-3
DALLE3_USD = 0.04
# Price in USD for an image generation for DALLE-2
DALLE2_USD = 0.02

# Loss of funds due to taxes and account top-up service fees
OPENAI_REFILL_LOSS = 0.38
# Apple Store and Google Play's commission for Telegram Stars
STORE_COMMISSION = 0.0  # 0.3
# Telegram commission for Telegram Stars
TELEGRAM_COMMISSSION = 0.0
# Bow owner's profit for Telegram Stars
ROYALTIES = 0.0
# Cost of a Telegram Star
XTR2USD = 0.02
# Cost of a USD in GPT-4o output tokens
USD2TOKENS = 1 / GPT4O_OUT_USD
# Period during which a refund can be performed
REFUND_PERIOD_DAYS = 28

# Maximum length of a text that is going to be sent via Telegram.
# 4096 - is a Telegram's restriction, but additional "\" characters will be added
# during markdown formatting
PAR_MAX_LEN = 3900

# Minimum length of text piece the message is updated with during chat completion.
MIN_INCREMENT = 30
# Maximum length of text piece the message is updated with during chat completion.
MAX_INCREMENT = 100

# Re pattern for code pieces surrounded by "```" in markdown text
CODE_PATTERN = re.compile(
    r"(?<!`|\w)(?<!\\)```\S*?\n(?:(?:.|\n)*?\S(?:.|\n)*?)(?:\s+)```(?!`|\w)"
)
# Re pattern for inline code pieces surrounded by "`" in markdown text
PRE_PATTERN = re.compile(
    r"(?<!`|\w)(?<!\\)`(?:(?:[^`])|(?:[^`]*?\\`[^`]*?))*?(?<!\\)`(?!`|\w)"
)
# Re pattern for all code pieces surrounded either by "`" or "```" in markdown text
CODE_AND_PRE_PATTERN = re.compile(
    rf"(?:{PRE_PATTERN.pattern})|(?:{CODE_PATTERN.pattern})"
)
# Re pattern for characters that should be escaped inside of code blocks in markdown
ESCAPED_IN_C_DEFAULT = re.compile(r"(?<!\\)[\\`]")
# Re pattern for characters that should be escaped outside of code blocks in markdown
ESCAPED_IN_O_DEFAULT = re.compile(r"(?<!\\)[\\[\]()`#+-={}.!]")
# Re pattern for "*", "_", "~", "|" surrounded with digits or letters
ESCAPED_IN_O_TIGHT = re.compile(r"(?<=\w)(?<!_)[*_~|](?!_)(?=\w)")
# Re pattern for markdown quote that is not at the start of the line
ESCAPED_IN_O_QUOTE = re.compile(r"(?<!\n)(?<!\A)(?<!\\)>")
# Re pattern for single "|" in markdown text (only paired "||" is valid for spoilers)
ESCAPED_IN_O_SINGLE = re.compile(r"(?<!\|)(?<!\\)\|(?!\|)")
# Re pattern for latex formulas
LATEX_PATTERN = re.compile(
    r"(?:\$\$|\\\[|\\\(|\\begin\{\w+\*?\})(?:.|\n)*?(?:\$\$|\\\]|\\\)|\\end\{\w+\*?\})"
)
# Re pattern for a body of a latex formula with delimiters discarded
LATEX_BODY_PATTERN = re.compile(
    r"(?:\$\$|\\\[|\\\(|\\begin\{\w+\*?\})((?:.|\n)*?)(?:\$\$|\\\]|\\\)|\\end\{\w+\*?\})"
)
# Re pattern for non-paired "```" or "`" which should be considered opening for
# a code block in markdown text
INCOMPLETE_CODE_PATTERN = re.compile(
    rf"(?:(?:{CODE_PATTERN.pattern})|(?:[^`])|(?:``?)(?!`)|(?:````+)|(?<=\w|\\)```|```(?!\n)\s)*"
)


# Aiogram's bot object that is used to send and recieve Telegram API requests
# and updates.
bot = Bot(
    token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2)
)
# OpenAI's asynchronous client object that is used to send and recieve API
# requests for chat completion and image generation.
openai_client = AsyncOpenAI(
    api_key=OPENAI_TOKEN,
    base_url="https://api.openai.com/v1",
)
