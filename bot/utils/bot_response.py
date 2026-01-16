"""Utility for logging bot responses.

This module provides a helper function to log bot responses (system messages)
with the bot's username, making them visible in Grafana logs.
"""

from typing import Optional

import config
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def log_bot_response(
    event: str,
    chat_id: int,
    user_id: Optional[int] = None,
    message_length: Optional[int] = None,
    **extra_fields,
) -> None:
    """Log a bot response with bot's username for Grafana visibility.

    Args:
        event: Event name (e.g., "bot.start_response", "bot.help_response").
        chat_id: Chat ID where the response was sent.
        user_id: User ID who triggered the response (optional).
        message_length: Length of the response message (optional).
        **extra_fields: Additional fields to include in the log.
    """
    log_data = {
        "chat_id": chat_id,
        "bot_id": config.BOT_ID,
        "username": config.BOT_USERNAME,
    }

    if user_id is not None:
        log_data["target_user_id"] = user_id

    if message_length is not None:
        log_data["message_length"] = message_length

    log_data.update(extra_fields)

    logger.info(event, **log_data)
