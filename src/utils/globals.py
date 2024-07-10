import re
from os import getenv
from dotenv import load_dotenv

from openai import AsyncOpenAI

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

load_dotenv()

BOT_TOKEN = getenv("TG_BOT_TOKEN")
OPENAI_KEY = getenv("OPENAI_API_KEY")

WEB_SERVER_HOST = "127.0.0.1"
WEB_SERVER_PORT = 8080
WEBHOOK_PATH = "/var/www/chxxxxbot"
BASE_WEBHOOK_URL = "https://trxxxxkov.net"
WEBHOOK_SECRET = getenv("WEBHOOK_SECRET")

OWNER_CHAT_ID = 791388236
DATABASE_NAME = "chxxxxbot"
DATABASE_USER = "chxxxxbot"
DATABASE_HOST = "localhost"
DATABASE_PORT = "5432"
DATABASE_PASSWORD = getenv("POSTGRESQL_DB_PASSWORD")
DSN = f"host={DATABASE_HOST} \
        port={DATABASE_PORT} \
        dbname={DATABASE_NAME} \
        user={DATABASE_USER} \
        password={DATABASE_PASSWORD}"

GPT_MEMORY_SEC = 7200
GPT4O_IN_USD = 0.005 / 1000
GPT4O_OUT_USD = 0.015 / 1000
VISION_USD = 0.004
DALLE3_USD = 0.08
DALLE2_USD = 0.02


OPENAI_REFILL_LOSS = 0.4
STORE_COMMISSION = 0.3
TELEGRAM_COMMISSSION = 0.05
ROYALTIES = 0.05
XTR2USD = 0.02
USD2TOKENS = 1 / GPT4O_OUT_USD
REFUND_PERIOD_DAYS = 28

PAR_MAX_LEN = 4090

CODE_PATTERN = re.compile(
    r"(?<!`|\w)(?<!\\)```\S*?\n(?:(?:.|\n)*?\S(?:.|\n)*?)(?:\s+)```(?!`|\w)"
)
PRE_PATTERN = re.compile(
    r"(?<!`|\w)(?<!\\)`(?:(?:[^`])|(?:[^`]*?\\`[^`]*?))*?(?<!\\)`(?!`|\w)"
)
CODE_AND_PRE_PATTERN = re.compile(
    rf"(?:{PRE_PATTERN.pattern})|(?:{CODE_PATTERN.pattern})"
)
ESCAPED_IN_C_DEFAULT = re.compile(r"(?<!\\)[\\`]")
ESCAPED_IN_O_DEFAULT = re.compile(r"(?<!\\)[\\[\]()`#+-={}.!]")
ESCAPED_IN_O_TIGHT = re.compile(r"(?<=\w)(?<!_)[*_~|](?!_)(?=\w)")
ESCAPED_IN_O_QUOTE = re.compile(r"(?<!\n)(?<!\A)(?<!\\)>")
ESCAPED_IN_O_SINGLE = re.compile(r"(?<!\|)(?<!\\)\|(?!\|)")
LATEX_PATTERN = re.compile(
    r"(?:\$\$|\\\[|\\\(|\\begin\{\w+\*?\})(?:.|\n)*?(?:\$\$|\\\]|\\\)|\\end\{\w+\*?\})"
)
LATEX_BODY_PATTERN = re.compile(
    r"(?:\$\$|\\\[|\\\(|\\begin\{\w+\*?\})((?:.|\n)*?)(?:\$\$|\\\]|\\\)|\\end\{\w+\*?\})"
)
INCOMPLETE_CODE_PATTERN = re.compile(
    rf"(?:(?:{CODE_PATTERN.pattern})|(?:[^`])|(?:``?)(?!`)|(?:````+)|(?<=\w|\\)```|```(?!\n)\s)*"
)


bot = Bot(
    token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2)
)
openai_client = AsyncOpenAI(
    api_key=OPENAI_KEY,
    base_url="https://api.openai.com/v1",
)
