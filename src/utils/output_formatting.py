"""Functions for text parsing, formatting and data convertions"""

from src.openai import openai_globals


def stream_increment(paragraph_len: int) -> int:
    """Get number of characters to be collected before a message should be updated."""
    return min(
        openai_globals.MAX_CHARS_TO_UPDATE,
        openai_globals.MIN_CHARS_TO_UPDATE + paragraph_len // 5,
    )
