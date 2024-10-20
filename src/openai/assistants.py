"""Tools for assistants list management"""

from src.openai import openai_globals


async def initialize_assistants() -> None:
    """Add default assistants to the openai client if there weren't added before."""
    existing_assistants = await openai_globals.client.beta.assistants.list()
    default_assistants = openai_globals.default_assistants
    existing_names = {elem.name for elem in existing_assistants.data}
    for default_assistant in default_assistants:
        if default_assistant["name"] not in existing_names:
            await openai_globals.client.beta.assistants.create(**default_assistant)


async def get_assistant(
    *, name: str | None = None, identifier: str | None = None
) -> object | None:
    """Get assistant with corresponding name or id from the list of all assistants."""
    available_assistants = await openai_globals.client.beta.assistants.list()
    for assistant in available_assistants.data:
        if assistant.name == name or assistant.id == identifier:
            return assistant
    return None
