"""Global objects and constants related to OpenAI API usage."""

import os

import dotenv
import openai


dotenv.load_dotenv()

client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

default_assistants = [
    {
        "name": "Default gpt-4o",
        "model": "gpt-4o",
        "instructions": "You are a personal assistant. Strive to answer questions briefly, in a sentence or two.",
        "temperature": 0.4,
        "tools": [{"type": "file_search"}, {"type": "code_interpreter"}],
    },
    {
        "name": "Default gpt-4o-mini",
        "model": "gpt-4o-mini",
        "instructions": "You are a personal assistant. Strive to answer questions briefly, in a sentence or two.",
        "temperature": 0.4,
        "tools": [{"type": "file_search"}],
    },
]
