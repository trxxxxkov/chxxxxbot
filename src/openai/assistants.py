"""Tools for assistants list management"""

from src.openai import openai_globals


async def initialize_assistants():
    """Retrieve a list of assistants if there are any. Otherwise, return default."""
    available_assistants = await openai_globals.client.beta.assistants.list()
    missed_assistants = {
        "gpt-4o": "You are a personal assistant. Strive to answer questions briefly, in a sentence or two.;0.4",
        "gpt-4o-mini": "You are a personal assistant. Strive to answer questions briefly, in a sentence or two.;0.4",
    }
    for assistant in available_assistants.data:
        if assistant.name in missed_assistants:
            missed_assistants.pop(assistant.name)
    for name, params in missed_assistants.items():
        instruction, temperature_str = params.split(";")
        created_assistant = await openai_globals.client.beta.assistants.create(
            name=name,
            model=name,
            instructions=instruction,
            temperature=float(temperature_str),
            tools=[
                {"type": "code_interpreter"},
                {"type": "file_search"},
            ],
        )
        openai_globals.assistants[created_assistant.id] = created_assistant
