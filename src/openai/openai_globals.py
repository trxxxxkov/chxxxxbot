"""Global objects and constants related to OpenAI API usage."""

import os

import dotenv
import openai


dotenv.load_dotenv()

client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
assistants = {}
thread_ids = set()
