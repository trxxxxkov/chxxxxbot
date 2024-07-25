"""Bot entrypoint"""

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
    # If you have a self-signed SSL certificate, then you will need to send a public
    # certificate to Telegram
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
    # Connect debugger depending on a variable in .env
    if getenv("BOT_DEBUG") != "0":
        import debugpy

        debugpy.listen(("0.0.0.0", 5678))
    # Dispatcher is a root router
    dp = Dispatcher()
    # All handlers should be attached to the Router (or Dispatcher).
    # The order of the routers matters
    dp.include_routers(
        other_upds.rt, callbacks.rt, privileged_cmds.rt, hidden_cmds.rt, public_cmds.rt
    )
    # Register startup hook to initialize webhook
    dp.startup.register(on_startup)
    # Create aiohttp.web.Application instance
    app = web.Application()
    # Create an instance of request handler,
    # aiogram has few implementations for different cases of usage
    # In this example we use SimpleRequestHandler which is designed to handle simple cases
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    # Register webhook handler on application
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    # Mount dispatcher startup and shutdown hooks to aiohttp application
    setup_application(app, dp, bot=bot)
    # And finally start webserver
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    main()
