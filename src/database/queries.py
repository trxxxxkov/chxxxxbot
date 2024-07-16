import time
import psycopg
import os
from psycopg.rows import dict_row

from src.utils.globals import bot, DSN, REFUND_PERIOD_DAYS


async def db_execute(queries, args=None):
    response = []
    if not isinstance(queries, list):
        queries = [queries]
        args = [args]
    async with await psycopg.AsyncConnection.connect(
        DSN, row_factory=dict_row
    ) as aconn:
        async with aconn.cursor() as cur:
            for i in range(min(len(queries), len(args))):
                if not isinstance(args[i], list) and args[i] is not None:
                    args[i] = [args[i]]
                try:
                    await cur.execute(queries[i], args[i])
                    response.extend(await cur.fetchall())
                except Exception as e:
                    if "the last operation didn't produce a result" in str(e):
                        pass
                    else:
                        raise e
    if len(response) == 1:
        return response[0]
    else:
        return response


async def db_update_user(user):
    await db_execute(
        "UPDATE users SET \
                first_name = %s, \
                last_name = %s, \
                username = %s, \
                balance = %s, \
                language = %s \
                WHERE id = %s;",
        [
            user["first_name"],
            user["last_name"],
            user["username"],
            user["balance"],
            user["language"],
            user["id"],
        ],
    )


async def db_update_model(model):
    await db_execute(
        "UPDATE models SET \
                model_name = %s, \
                max_tokens = %s, \
                temperature = %s \
                WHERE user_id = %s;",
        [
            model["model_name"],
            model["max_tokens"],
            model["temperature"],
            model["user_id"],
        ],
    )


async def db_save_message(message, tokens, role, pending=False):
    await db_execute(
        "INSERT INTO messages (message_id, from_user_id, timestamp, tokens, role, text, image_url, pending) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
        [
            message.message_id,
            message.from_user.id,
            message.date,
            tokens,
            role,
            get_message_text(message),
            await get_image_url(message),
            pending,
        ],
    )


async def db_update_purchase(purchase):
    await db_execute(
        "UPDATE purchases SET \
                user_id = %s, \
                amount = %s, \
                timestamp = %s, \
                currency = %s, \
                refunded = %s \
                WHERE id = %s;",
        [
            purchase["user_id"],
            purchase["amount"],
            purchase["timestamp"],
            purchase["currency"],
            purchase["refunded"],
            purchase["id"],
        ],
    )


async def get_image_url(message):
    from src.utils.formatting import encode_image

    if message.photo:
        image_path = f"src/utils/temp/images/{message.from_user.id}-{message.message_id}.jpg"
        await bot.download(message.photo[-1], destination=image_path)
        url = encode_image(image_path)
        os.remove(image_path)
        return url
    else:
        return None


def get_message_text(message):
    if message.photo:
        if message.caption:
            return message.caption
        else:
            return ""
    else:
        return message.text


async def db_get_user(user_id):
    user = await db_execute("SELECT * FROM users WHERE id = %s;", user_id)
    return user


async def db_get_model(user_id):
    model = await db_execute("SELECT * FROM models WHERE user_id = %s;", user_id)
    return model


async def db_get_messages(user_id):
    data = await db_execute(
        "SELECT * FROM messages WHERE from_user_id = %s ORDER BY timestamp;",
        user_id,
    )
    if not isinstance(data, list):
        data = [data]
    messages = []
    for msg in data:
        messages.append(
            {
                "role": msg["role"],
                "content": [
                    {"type": "text", "text": msg["text"]},
                ],
            }
        )
        if msg["image_url"] is not None:
            messages[-1]["content"].append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{msg["image_url"]}", "detail": "high"},
                }
            )
    return messages


async def db_get_purchase(purchase_id):
    now = time.time()
    purchase = await db_execute(
        "SELECT * FROM purchases WHERE \
            id = %s and timestamp > TO_TIMESTAMP(%s);",
        [purchase_id, now - 60 * 60 * 24 * REFUND_PERIOD_DAYS],
    )
    return purchase
