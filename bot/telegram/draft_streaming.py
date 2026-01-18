"""Draft-based streaming for Telegram Bot API 9.3.

This module provides DraftStreamer class for streaming responses using
sendMessageDraft method, which doesn't trigger flood control limits.

NO __init__.py - use direct import: from telegram.draft_streaming import DraftStreamer
"""

import random
from typing import Optional

from aiogram import Bot
from aiogram import types
from aiogram.methods import SendMessageDraft
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class DraftStreamer:
    """Manages draft-based message streaming.

    Uses sendMessageDraft for smooth animated updates without flood control.
    Bot API 9.3 feature - requires forum topic mode enabled.

    Attributes:
        bot: Telegram Bot instance.
        chat_id: Target chat ID.
        topic_id: Telegram forum topic ID (message_thread_id).
        draft_id: Unique draft identifier for animated updates.
        last_text: Last sent text (to avoid duplicate updates).

    Example:
        streamer = DraftStreamer(bot, chat_id=123, topic_id=456)
        await streamer.update("Thinking...")
        await streamer.update("Thinking... done!")
        final_msg = await streamer.finalize()
    """

    def __init__(self,
                 bot: Bot,
                 chat_id: int,
                 topic_id: Optional[int] = None) -> None:
        """Initialize draft streamer.

        Args:
            bot: Telegram Bot instance.
            chat_id: Target chat ID.
            topic_id: Telegram forum topic ID (None for main chat).
        """
        self.bot = bot
        self.chat_id = chat_id
        self.topic_id = topic_id
        # Non-zero draft_id required, same ID = animated updates
        self.draft_id = random.randint(1, 2**31 - 1)
        self.last_text = ""
        self._update_count = 0

        logger.debug("draft_streamer.initialized",
                     chat_id=chat_id,
                     topic_id=topic_id,
                     draft_id=self.draft_id)

    async def update(self,
                     text: str,
                     parse_mode: Optional[str] = "HTML") -> bool:
        """Update draft with new text (animated).

        Skips update if text hasn't changed.
        No flood control - can call frequently.

        Args:
            text: New text content (1-4096 chars).
            parse_mode: Parse mode for formatting (HTML, Markdown, etc).

        Returns:
            True on success, False on failure.
        """
        if not text:
            return True

        # Skip if text unchanged
        if text == self.last_text:
            return True

        # Truncate if too long (Telegram limit)
        if len(text) > 4096:
            text = text[:4093] + "..."

        try:
            result = await self.bot(
                SendMessageDraft(
                    chat_id=self.chat_id,
                    draft_id=self.draft_id,
                    text=text,
                    message_thread_id=self.topic_id,
                    parse_mode=parse_mode,
                ))

            self.last_text = text
            self._update_count += 1

            if self._update_count % 50 == 0:  # Log every 50 updates
                logger.debug("draft_streamer.update_milestone",
                             chat_id=self.chat_id,
                             update_count=self._update_count,
                             text_length=len(text))

            return result

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("draft_streamer.update_failed",
                           chat_id=self.chat_id,
                           draft_id=self.draft_id,
                           error=str(e))
            # Try without parse_mode as fallback
            if parse_mode:
                return await self.update(text, parse_mode=None)
            return False

    async def finalize(self,
                       parse_mode: Optional[str] = "HTML") -> types.Message:
        """Convert draft to permanent message.

        Draft disappears automatically, sends final message via send_message.

        Args:
            parse_mode: Parse mode for final message.

        Returns:
            Final sent Message object.

        Raises:
            Exception: If send_message fails.
        """
        logger.info("draft_streamer.finalizing",
                    chat_id=self.chat_id,
                    topic_id=self.topic_id,
                    total_updates=self._update_count,
                    final_length=len(self.last_text))

        # Send final message (draft disappears)
        return await self.bot.send_message(
            chat_id=self.chat_id,
            text=self.last_text,
            message_thread_id=self.topic_id,
            parse_mode=parse_mode,
        )

    async def clear(self) -> bool:
        """Clear/hide draft without sending final message.

        Useful when streaming is interrupted or cancelled.

        Returns:
            True on success.
        """
        try:
            # Send empty draft to clear
            await self.bot(
                SendMessageDraft(
                    chat_id=self.chat_id,
                    draft_id=self.draft_id,
                    text=" ",  # Minimal content
                    message_thread_id=self.topic_id,
                ))

            logger.debug("draft_streamer.cleared",
                         chat_id=self.chat_id,
                         draft_id=self.draft_id)
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("draft_streamer.clear_failed",
                           chat_id=self.chat_id,
                           error=str(e))
            return False
