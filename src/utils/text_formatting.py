"""Functions for text parsing, formatting and data convertions"""

import aiogram

from src.openai import openai_globals


def stream_increment(paragraph_len: int) -> int:
    """Get number of characters to be collected before a message should be updated."""
    return min(
        openai_globals.MAX_CHARS_TO_UPDATE,
        openai_globals.MIN_CHARS_TO_UPDATE + paragraph_len // 5,
    )


def extract_text(message: aiogram.types.Message) -> str:
    """Extract text from message, including text from replied message."""
    text = message.md_text
    if message.invoice:
        text = f"{message.invoice.title}\n{message.invoice.description}"
    if message.reply_to_message:
        text = f"{extract_text(message.reply_to_message)}\n\n{text}"
    if not text:
        text = "?"
    return text
