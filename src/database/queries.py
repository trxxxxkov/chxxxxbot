"""Wrapper functions over psycopg calls"""

import time
import psycopg
from psycopg.rows import dict_row

from aiogram.types import Message

from src.utils.globals import DSN, REFUND_PERIOD_DAYS
from src.utils.formatting import get_image_url, get_message_text


async def db_execute(queries: list[str] | str, args=None):
    """Execute multiple db queries in a single psycopg connection.
    
    Args:
        queries:
            list of string SQL queries. If only one query is provided, it may be
            passed just as a string.
        args:
            list of arguments to format queries with. Each agrument corresponds
            to the query with the same index in arguments list.
    
    Returns:
        list of SQL queries results or a result itself if only one element acquired. 
    """
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


async def db_update_user(user: dict) -> None:
    """Update 'users' table record for the user with provided id.
    
    Args:
        user: dictionary with non-empty table fields. Usually is obtained as a
            result of db_get_user() function.
    """

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


async def db_update_model(model: dict) -> None:
    """Update 'models' table record for the model with provided user_id.
    
    Args:
        model: dictionary with non-empty table fields. Usually is obtained as a
            result of db_get_model() function.
    """
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


async def db_save_message(message: Message, tokens: str | int, role: str, pending: bool = False) -> None:
    """Write Telegram message object data into 'messages' table.
    
    Args:
        message: Telegram Message object which data will be written to the database.
        tokens: Estimated message cost calculated in output tokens.
        role: Either "user" or "system". Specifies whether the message sent by
            user or the AI.
        pending: Indicator of whether the message is already being processed or
            is waiting until the AI will answer all previous messages.
    """
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


async def db_update_purchase(purchase: dict) -> None:
    """Update 'purchases' table record for the purchase with provided id.
    
    Args:
        purchase: dictionary with non-empty table fields. Usually is obtained as a
            result of db_get_purchase() function.
    """
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


async def db_get_user(user_id: int) -> dict:
    """Read data of the specified user from the 'users' database table."""
    user = await db_execute("SELECT * FROM users WHERE id = %s;", user_id)
    return user


async def db_get_model(user_id: int) -> dict:
    """Read data of the specified user's model from the 'models' database table."""
    model = await db_execute("SELECT * FROM models WHERE user_id = %s;", user_id)
    return model


async def db_get_messages(user_id: int) -> dict:
    """Read and format messages of the specified user from the 'messages' table.
    
    The user's messages are formatted in a way that is required by OpenAI for 
    chatbot context.
    """
    data = await db_execute(
        "SELECT text, role, image_url FROM messages WHERE from_user_id = %s ORDER BY timestamp;",
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


async def db_get_purchase(purchase_id: str) -> dict:
    """Read data of the specified user's purchases from the 'purchases' table."""
    now = time.time()
    # Purchases made more than REFUND_PERIOD_DAYS are discarded.
    purchase = await db_execute(
        "SELECT * FROM purchases WHERE \
            id = %s and timestamp > TO_TIMESTAMP(%s);",
        [purchase_id, now - 60 * 60 * 24 * REFUND_PERIOD_DAYS],
    )
    return purchase
