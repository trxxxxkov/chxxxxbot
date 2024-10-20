"""Tools for user's accounts and data management."""

from src.utils import bot_globals
from src.openai import openai_globals, assistants


async def user_initialization(new_user_id: int, new_user_lang: str) -> None:
    """Activate new user's account and grant him a welcome gift."""
    empty_thread = await openai_globals.client.beta.threads.create()
    default_assistant = await assistants.get_assistant(name="Default gpt-4o-mini")
    bot_globals.bot_users[new_user_id] = {
        "assistant_id": default_assistant.id,
        "thread_id": empty_thread.id,
        "language": new_user_lang,
        "balance_usd": 0.05,
    }
