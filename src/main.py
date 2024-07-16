import logging
import sys
from os import getenv

from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from src.handlers import (
    public_cmds,
    hidden_cmds,
    privileged_cmds,
    callbacks,
    other_upds,
)
from utils.globals import (
    bot,
    BASE_WEBHOOK_URL,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
    WEB_SERVER_HOST,
    WEB_SERVER_PORT,
)


async def on_startup(bot: Bot) -> None:
    await bot.set_webhook(
        f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=[
            "message",
            "inline_query",
            "callback_query",
            "pre_checkout_query",
        ],
    )


def main() -> None:
    if getenv("BOT_DEBUG") != "0":
        import debugpy

        debugpy.listen(("0.0.0.0", 5678))
    dp = Dispatcher()
    dp.include_routers(
        other_upds.rt, callbacks.rt, privileged_cmds.rt, hidden_cmds.rt, public_cmds.rt
    )
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
