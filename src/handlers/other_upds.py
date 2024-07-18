"""Handlers for payment updates and for other updates that could be added later."""

from aiogram import Router, F
from aiogram.types import Message, PreCheckoutQuery

from src.utils.formatting import send_template_answer, xtr2usd, usd2tok
from src.database.queries import db_execute, db_get_user

rt = Router()


@rt.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    """Accept the pre_checkout_query.

    This must be done within 20 seconds after receiving it.
    """
    await pre_checkout_query.answer(ok=True)


@rt.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    """Add funds to the user's balance after successful payment."""
    purchase_id = message.successful_payment.telegram_payment_charge_id
    user_id, amount = message.successful_payment.invoice_payload.split()
    user = await db_get_user(user_id)
    await db_execute(
        [
            "INSERT INTO purchases (id, user_id, amount) \
                VALUES (%s, %s, %s);",
            "UPDATE users SET balance = %s WHERE id = %s;",
        ],
        [
            [purchase_id, user["id"], int(amount)],
            [user["balance"] + xtr2usd(amount), user["id"]],
        ],
    )
    await send_template_answer(
        message,
        "info",
        "payment success",
        usd2tok(xtr2usd(amount)),
        purchase_id,
    )


# @rt.message(F.refunded_payment)
# async def refunded_payment_handler(message: Message):
#     """Seems to be handled by Telegram itself"""
#     _, amount = message.refunded_payment.invoice_payload.split()
#     await send_template_answer(message, "info", "refund success", amount)
