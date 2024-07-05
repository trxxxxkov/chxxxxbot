import psycopg
from psycopg.rows import dict_row

from src.utils.globals import bot, DSN, GPT4O_INPUT_1K, GPT4O_OUTPUT_1K


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
                {"type": "image_url", "image_url": {"url": msg["image_url"]}}
            )
    return messages


async def db_save_user(user):
    await db_execute(
        "UPDATE users SET \
                first_name = %s, \
                last_name = %s, \
                balance = %s, \
                lock = %s \
                WHERE id = %s;",
        [
            user["first_name"],
            user["last_name"],
            user["balance"],
            user["lock"],
            user["id"],
        ],
    )


async def db_save_model(model):
    await db_execute(
        "UPDATE models SET \
                model_name = %s, \
                max_tokens = %s, \
                temperature = %s, \
                WHERE user_id = %s;",
        [
            model["model_name"],
            model["max_tokens"],
            model["temperature"],
            model["user_id"],
        ],
    )


async def db_save_message(message, role):
    await db_execute(
        "INSERT INTO messages (message_id, from_user_id, timestamp, role, text, image_url) VALUES (%s, %s, %s, %s, %s, %s);",
        [
            message.message_id,
            message.from_user.id,
            message.date,
            role,
            await get_message_text(message),
            await get_image_url(message),
        ],
    )


async def db_save_expenses(message, usage):
    await db_execute(
        "INSERT INTO transactions (user_id, prompt_tokens, completion_tokens, cost) VALUES (%s, %s, %s, %s);",
        [
            message.from_user.id,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.prompt_tokens * GPT4O_INPUT_1K / 1000
            + usage.completion_tokens * GPT4O_OUTPUT_1K / 1000,
        ],
    )


async def get_image_url(message):
    from src.utils.formatting import local_image_to_data_url

    if message.photo:
        image_path = f"src/utils/temp/images/{message.from_user.id}.jpg"
        await bot.download(message.photo[-1], destination=image_path)
        return local_image_to_data_url(image_path)
    else:
        return None


async def get_message_text(message):
    if message.photo:
        if message.caption:
            return message.caption
        else:
            return ""
    else:
        return message.text
