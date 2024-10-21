"""Global objects and constants related to OpenAI API usage."""

import os

import dotenv
import openai


dotenv.load_dotenv()

# Main OpenAI's API object.
client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# List of assistants that are guaranteed to be present after bot launch.
default_assistants = [
    {
        "name": "Default gpt-4o",
        "model": "gpt-4o",
        "instructions": "You are a personal assistant with an access to files provided by the user. Retrieve information from files and always answer in a sentence or two if possible.",
        "temperature": 0.4,
        "tools": [
            {"type": "file_search", "file_search": {"max_num_results": 50}},
            {"type": "code_interpreter"},
        ],
    },
    {
        "name": "Default gpt-4o-mini",
        "model": "gpt-4o-mini",
        "instructions": "You are a personal assistant with an access to files provided by the user. Retrieve information from files and always answer in a sentence or two if possible.",
        "temperature": 0.4,
        "tools": [{"type": "file_search", "file_search": {"max_num_results": 50}}],
    },
]

# Minimal number of characters needed to update message when streaming chat completion.
MIN_CHARS_TO_UPDATE = 15
# Maximum number of characters needed to update message when streaming chat completion.
MAX_CHARS_TO_UPDATE = 150
