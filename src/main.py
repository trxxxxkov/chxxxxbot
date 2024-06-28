import logging
import sys
from aiohttp import web

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from src.handlers import public_cmds, hidden_cmds, privileged_cmds, callbacks
from utils.globals import (
    bot,
    BASE_WEBHOOK_URL,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
    WEB_SERVER_HOST,
    WEB_SERVER_PORT,
)

router = Router()


@router.message(Command("start"))
async def command_start_handler(message: Message) -> None:
    await message.answer(f"Hello\,\!")


async def on_startup(bot: Bot) -> None:
    await bot.set_webhook(
        f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}", secret_token=WEBHOOK_SECRET
    )


def main() -> None:
    dp = Dispatcher()
    dp.include_router(router)
    dp.include_router(public_cmds.rt)
    dp.include_router(hidden_cmds.rt)
    dp.include_router(privileged_cmds.rt)
    dp.include_router(callbacks.rt)
    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    main()
