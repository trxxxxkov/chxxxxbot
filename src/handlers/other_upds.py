from aiogram import Router, F
from aiogram.types import Message, PreCheckoutQuery

from src.templates.dialogs import dialogs
from src.utils.formatting import send
from src.utils.validations import language
from src.utils.globals import XTR2USD_COEF
from src.database.queries import db_execute, db_get_user

rt = Router()


@rt.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@rt.message(F.successful_payment)
async def successful_payment_handler(message: Message):
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
            [user["balance"] + int(amount) * XTR2USD_COEF, user["id"]],
        ],
    )
    await send(
        message, dialogs[language(message)]["payment-successful"].format(purchase_id)
    )


@rt.message(F.refunded_payment)
async def refunded_payment_handler(message: Message):
    await send(message, dialogs[language(message)]["refund-successful"])
