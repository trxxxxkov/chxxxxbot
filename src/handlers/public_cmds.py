"""Handlers for commands that are visible from Telegram's Bot Menu interface.

These are the commands that you want your users to use. The list is kept short
to avoid users get distracted from the bot's core functionality.
"""

from openai import OpenAIError

from aiogram import Router, types
from aiogram.types import Message, LabeledPrice
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.chat_action import ChatActionSender
from aiogram.exceptions import TelegramBadRequest

import src.templates.tutorial.videos
from src.templates.bot_menu import bot_menu
from src.templates.scripted_dialogues import dialogues
from src.templates.keyboards.inline_kbd import inline_kbd
from src.core.image_generation import generate_image
from src.core.chat_completion import generate_completion
from src.utils.formatting import (
    send_template_answer,
    format_tg_msg,
    xtr2usd,
    usd2tok,
    get_image_url,
)
from src.utils.validations import (
    language,
    tutorial_videos2ids,
    is_implemented,
    is_affordable,
    message_cost,
)
from src.database.queries import (
    db_execute,
    db_save_message,
    db_update_user,
    db_get_user,
    db_get_purchase,
)
from src.utils.globals import bot, GPT4O_OUT_USD, DALLE3_USD, GPT4O_IN_USD


rt = Router()
# Set of users whose requests are currently being processed by GPT-4o.
# All requests coming from these users will be marked as pending and will be
# answered later.
# TODO: This should become a Redis database very soon...
BUSY_USERS = set()


@rt.message(Command("draw"))
async def draw_handler(message: Message, command) -> None:
    """Generate an image by user's description with DALLE-3.

    The command have the following syntax:
    /draw YOUR_PROMPT,
    where YOUR_PROMPT - is a description that will be used to generate image.

    If a prompt violates OpenAI's content policy, the corresponding request will not
    be processed and the user will be notified about it.
    """
    if not command.args:
        # Show user the command's syntax.
        await send_template_answer(message, "doc", "draw")
    else:
        # Check that user's balance is sufficient to pay for the context.
        if await is_affordable(message):
            # OpenAI add ~7 tokens to every prompt cost so a compensation added.
            input_tokens = usd2tok(message_cost(message) + 2 * GPT4O_OUT_USD)
            # Draw requests are not pending because of great waiting time.
            await db_save_message(message, input_tokens, "user", False)
            try:
                async with ChatActionSender.upload_photo(message.chat.id, bot):
                    image_url = await generate_image(command.args)
                kbd = inline_kbd({"redraw": "redraw"}, language(message))
                msg = await bot.send_photo(message.chat.id, image_url, reply_markup=kbd)
                # 300 - is an approximate cost of the image recognition which
                # will be needed in the following requests.
                # This record receives "user" role because OpenAI doesn't permit
                # messages with "system" role that contain images.
                await db_execute(
                    "INSERT INTO messages (message_id, from_user_id, tokens, image_url, pending) \
                        VALUES (%s, %s, %s, %s, %s);",
                    [
                        msg.message_id,
                        message.from_user.id,
                        300,
                        await get_image_url(msg),
                        False,
                    ],
                )
                user = await db_get_user(message.from_user.id)
                user["balance"] -= DALLE3_USD
                await db_update_user(user)
            except (Exception, OpenAIError) as e:
                # OpenAI declined the request because of violation of their
                # content policy. The user is adviced to try again with another
                # choice of words.
                await send_template_answer(message, "err", "policy block")
                await forget_handler(message)


@rt.message(Command("forget", "clear"))
async def forget_handler(message: Message) -> None:
    """Delete user's messages from the database and notify him about it."""
    await db_execute(
        "DELETE FROM messages WHERE from_user_id = %s;", message.from_user.id
    )
    await send_template_answer(message, "info", "forget success")


@rt.message(Command("balance"))
async def balance_handler(message: Message) -> None:
    """Show user's balance, payment info and buttons to other tutorials.

    The message contain short video that shows prompt tokenization details and
    buttons to the default /help message, additional information about tokens and
    payment button with 1 Telegram Star invoice.
    """
    # If the tutorial videos weren't send yet, send them to bot owner and save
    # their file_ids into src.templates.tutorial.videos.videos.
    if src.templates.tutorial.videos.videos is None:
        await tutorial_videos2ids()
    builder = InlineKeyboardBuilder()
    mid_button = types.InlineKeyboardButton(
        text=dialogues["bttn"]["try payment"][language(message)],
        callback_data=f"try payment",
    )
    builder.row(mid_button)
    builder.row(
        types.InlineKeyboardButton(
            text=dialogues["bttn"]["back to help"][language(message)],
            callback_data="help-0",
        ),
        types.InlineKeyboardButton(
            text=dialogues["bttn"]["to tokens"][language(message)],
            callback_data="tokens",
        ),
    )
    user = await db_get_user(message.from_user.id)
    text = format_tg_msg(
        dialogues["doc"]["payment"][language(message)].format(
            usd2tok(user["balance"]), usd2tok(xtr2usd(1))
        )
    )
    await bot.send_animation(
        message.chat.id,
        src.templates.tutorial.videos.videos["tokens"],
        caption=text,
        reply_markup=builder.as_markup(),
    )


@rt.message(Command("pay"))
async def pay_handler(message: Message, command) -> None:
    """Send invoice for the specified amount of Telegram stars.

    The command have the following syntax:
    /pay STARS_AMOUNT,
    where STARS_AMOUNT - is an integer number of stars to send an invoice for.

    Though users see tokens as the main currency, calculations are always
    performed in USD. Tokens to USD convertion is very simple:

    $1 = (1 / GPT4O_OUT_USD) tokens,

    where GPT4O_OUT_USD - is a OpenAI's price of a single output token for GPT-4o.
    Thus, the main bot's currency is actually output tokens of GPT-4o.
    """
    if (
        command.args is None
        or not command.args.isdigit()
        or not 1 <= int(command.args) <= 2500
    ):
        await send_template_answer(message, "doc", "pay", usd2tok(xtr2usd(1)))
    else:
        amount = int(command.args)
        prices = [LabeledPrice(label="XTR", amount=amount)]
        kbd = (
            InlineKeyboardBuilder()
            .add(
                types.InlineKeyboardButton(
                    text=dialogues["bttn"]["pay"][language(message)].format(amount),
                    pay=True,
                ),
                types.InlineKeyboardButton(
                    text=dialogues["bttn"]["to tokens"][language(message)],
                    callback_data="sep tokens",
                ),
            )
            .as_markup()
        )
        await bot.send_invoice(
            chat_id=message.chat.id,
            title=dialogues["other"]["payment title"][language(message)],
            description=dialogues["doc"]["payment description"][
                language(message)
            ].format(usd2tok(xtr2usd(amount))),
            payload=f"{message.from_user.id} {amount}",
            currency="XTR",
            prices=prices,
            reply_markup=kbd,
        )


@rt.message(Command("refund"))
async def refund_handler(message: Message, command) -> None:
    """Refund a purchase after satisfying date and balance requirements.

    After each purchase users get purchase ID which is required to make a refund.
    Check if the purchase was made less than REFUND_PERIOD_DAYS ago and the user's
    balance is sufficient to withdraw the corresponding amount of tokens."""
    purchase_id = command.args
    if purchase_id is None:
        await send_template_answer(message, "doc", "refund")
    else:
        purchase = await db_get_purchase(purchase_id)
        user = await db_get_user(message.from_user.id)
        if purchase:
            if user["balance"] < xtr2usd(purchase["amount"]):
                await send_template_answer(message, "err", "invalid purchase id")
                return
            try:
                result = await bot.refund_star_payment(
                    user_id=message.from_user.id, telegram_payment_charge_id=purchase_id
                )
                if result:
                    await db_execute(
                        [
                            "UPDATE users SET balance = %s WHERE id = %s;",
                            "UPDATE purchases SET refunded = True WHERE id = %s;",
                        ],
                        [
                            [
                                user["balance"] - xtr2usd(purchase["amount"]),
                                user["id"],
                            ],
                            [purchase["id"]],
                        ],
                    )
            except TelegramBadRequest as e:
                if "CHARGE_ALREADY_REFUNDED" in e.message:
                    await send_template_answer(message, "err", "already refunded")
                else:
                    await send_template_answer(message, "err", "invalid purchase id")
        else:
            await send_template_answer(message, "err", "refund expired")


@rt.message(Command("help"))
async def help_handler(message: Message) -> None:
    """Show tutorial start page with information about making prompt.

    The message contain text and short video that provides example about how to
    make requests to GPT-4o and buttons to the default /balance message, and the
    next tutorial page devoted to image generation.

    The initial text of the message, sent by /help command is just a first page
    of several messages that use text and short video to provide information about
    bot usage.
     Each message consists of the following parts:
      - Short video about the topic;
      - Textual information about the topic;
      - Navigation buttons that let user move from one page to another.
    Thus, all tutorial messages are connected with each other through inline
    keyboard buttons:

                          (prompts)  (gener.)    (recogn.)  (LaTeX)
    tokens <-> balance <-> help-0 <-> help-1 <-> help-2 <-> help-3 ---> balance <-> tokens

    Where arrow means that the messages are connected via inline keyboard buttons.
    When the button is pressed, the message is edited with the required content.
    """
    if src.templates.tutorial.videos.videos is None:
        await tutorial_videos2ids()
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(
            text=dialogues["bttn"]["to balance"][language(message)],
            callback_data="balance",
        ),
        types.InlineKeyboardButton(
            text=dialogues["bttn"]["to help"][1][language(message)] + " »",
            callback_data="help-1",
        ),
    )
    text = format_tg_msg(dialogues["doc"]["help"][0][language(message)])
    await bot.send_animation(
        message.from_user.id,
        src.templates.tutorial.videos.videos["help"][0],
        caption=text,
        reply_markup=builder.as_markup(),
    )


@rt.message()
async def handler(message: Message, *, recursive=False) -> None:
    """Handler for all messages which are considered a prompt to GPT-4o.

    Recursively handle all non-command updates. After an update is detected, the
    bot waits for 0.1 seconds (plus the time for db checks) to collect all updates
    that could be parts of a one long message automatically splitted into peaces
    by Telegram. Then the user input is locked until the response will be sent -
    this is necessary to prevent user from having multiple requests being
    processed which could result in temporary bot block due to the Telegram
    updates frequency limitations.
    If anything happens during that period, it is added to the database with
    'pending' marker. After the bot finishes processing of previous messages,
    all 'pending' updates are collected (with the same 0.1 +... waiting time),
    marked as 'not pending' and sent to GPT-4o for processing.

    The described cycle repeats until no 'pending' updates are left in the database.
    """
    if is_implemented(message) and await is_affordable(message):
        # The handler is called 'recursive' when it's going to process some
        # pending updates came while user was locked. The message past as
        # an argument is already processed, so it is not added to database again.
        if not recursive:
            input_tokens = usd2tok(message_cost(message) + 2 * GPT4O_OUT_USD)
            await db_save_message(message, input_tokens, "user", True)
        # If user input is locked, no other actions performed
        if message.from_user.id in BUSY_USERS:
            return
        BUSY_USERS.add(message.from_user.id)
        try:
            response, usage, last_message = await generate_completion(message)
            await db_execute(
                "INSERT INTO messages \
                    (message_id, from_user_id, tokens, role, text) \
                    VALUES (%s, %s, %s, %s, %s);",
                [
                    last_message.message_id,
                    message.from_user.id,
                    usage.completion_tokens,
                    "system",
                    response,
                ],
            )
            user = await db_get_user(message.from_user.id)
            user["balance"] -= (
                GPT4O_IN_USD * usage.prompt_tokens
                + GPT4O_OUT_USD * usage.completion_tokens
            )
            # The user's data is updated after each request.
            user["first_name"] = message.from_user.first_name
            user["last_name"] = message.from_user.last_name
            user["username"] = message.from_user.username
            user["language"] = language(message)
            await db_update_user(user)
            BUSY_USERS.discard(message.from_user.id)
            pending = await db_execute(
                "SELECT message_id FROM messages WHERE pending = TRUE and from_user_id = %s;",
                message.from_user.id,
            )
            # If there are new updates that showed up while processing previous
            # updates, the process must be restarted with all user's information
            # in 'message'. But its content has already been processed so reqursive
            # call is performed. Which means that the message will not be added
            # to the database again.
            if pending:
                await handler(message, recursive=True)
            else:
                await bot.set_my_commands(
                    [
                        types.BotCommand(
                            command=key, description=value[language(message)]
                        )
                        for key, value in bot_menu.items()
                    ]
                )
        # If user is locked, the handler will not react to him anymore, so
        # manual unlock of user input is required.
        except Exception:
            BUSY_USERS.discard(message.from_user.id)
