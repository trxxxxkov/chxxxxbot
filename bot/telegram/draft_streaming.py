"""Draft-based streaming for Telegram Bot API 9.3.

This module provides DraftStreamer class for streaming responses using
sendMessageDraft method with proper rate limiting.

NO __init__.py - use direct import: from telegram.draft_streaming import DraftStreamer
"""

import asyncio
import random
import time
from typing import Optional

from aiogram import Bot
from aiogram import types
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessageDraft
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Minimum interval between draft updates (seconds)
# sendMessageDraft still has rate limits, just more relaxed than edit_message
MIN_UPDATE_INTERVAL = 0.3


class DraftStreamer:  # pylint: disable=too-many-instance-attributes
    """Manages draft-based message streaming with rate limiting.

    Uses sendMessageDraft for smooth animated updates.
    Bot API 9.3 feature - requires forum topic mode enabled.

    Includes built-in throttling to avoid flood control.

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
        self._last_update_time = 0.0
        self._pending_text: Optional[str] = None  # Text waiting to be sent
        self._finalized = False  # Prevents keepalive on finalized drafts

        logger.debug("draft_streamer.initialized",
                     chat_id=chat_id,
                     topic_id=topic_id,
                     draft_id=self.draft_id)

    async def update(  # pylint: disable=too-many-return-statements
            self,
            text: str,
            parse_mode: Optional[str] = "HTML",
            force: bool = False) -> bool:
        """Update draft with new text (with throttling).

        Skips update if text hasn't changed or if called too frequently.
        Handles TelegramRetryAfter by waiting and retrying.

        Args:
            text: New text content (1-4096 chars).
            parse_mode: Parse mode for formatting (HTML, Markdown, etc).
            force: If True, ignore throttling (for final updates).

        Returns:
            True on success, False on failure.
        """
        if not text:
            return True

        # Skip if already finalized
        if self._finalized:
            return True

        # Skip if text unchanged
        if text == self.last_text:
            return True

        # Throttle updates (unless forced)
        current_time = time.time()
        time_since_last = current_time - self._last_update_time

        if not force and time_since_last < MIN_UPDATE_INTERVAL:
            # Store pending text, will be sent on next allowed update
            self._pending_text = text
            return True

        # When forced, always use the passed text (e.g., final stripped message)
        # Otherwise use pending text if we have it (ensures we send latest)
        if force:
            text_to_send = text
            self._pending_text = None  # Clear pending since we're sending now
        else:
            text_to_send = self._pending_text or text
            self._pending_text = None

        # Truncate if too long (Telegram limit)
        if len(text_to_send) > 4096:
            text_to_send = text_to_send[:4093] + "..."

        try:
            await self.bot(
                SendMessageDraft(
                    chat_id=self.chat_id,
                    draft_id=self.draft_id,
                    text=text_to_send,
                    message_thread_id=self.topic_id,
                    parse_mode=parse_mode,
                ))

            self.last_text = text_to_send
            self._update_count += 1
            self._last_update_time = time.time()

            if self._update_count % 50 == 0:  # Log every 50 updates
                logger.debug("draft_streamer.update_milestone",
                             chat_id=self.chat_id,
                             update_count=self._update_count,
                             text_length=len(text_to_send))

            return True

        except TelegramRetryAfter as e:
            # Flood control - wait and retry once
            logger.warning("draft_streamer.flood_control",
                           chat_id=self.chat_id,
                           retry_after=e.retry_after)
            await asyncio.sleep(e.retry_after)
            try:
                await self.bot(
                    SendMessageDraft(
                        chat_id=self.chat_id,
                        draft_id=self.draft_id,
                        text=text_to_send,
                        message_thread_id=self.topic_id,
                        parse_mode=parse_mode,
                    ))
                self.last_text = text_to_send
                self._update_count += 1
                self._last_update_time = time.time()
                return True
            except Exception:  # pylint: disable=broad-exception-caught
                return False

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("draft_streamer.update_failed",
                           chat_id=self.chat_id,
                           draft_id=self.draft_id,
                           error=str(e))
            # Try without parse_mode as fallback
            if parse_mode:
                return await self.update(text_to_send, parse_mode=None)
            return False

    async def flush_pending(self, parse_mode: Optional[str] = "HTML") -> bool:
        """Send any pending text that was throttled.

        Call this before finalize() to ensure all text is sent.

        Args:
            parse_mode: Parse mode for formatting.

        Returns:
            True on success.
        """
        if self._pending_text and self._pending_text != self.last_text:
            return await self.update(self._pending_text, parse_mode, force=True)
        return True

    async def keepalive(self, parse_mode: Optional[str] = "HTML") -> bool:
        """Send keep-alive update to prevent draft from disappearing.

        Unlike update(), this always sends even if text unchanged.
        Use during long operations like image generation.

        Args:
            parse_mode: Parse mode for formatting.

        Returns:
            True on success, False on failure.
        """
        # Skip if already finalized (prevents race condition with
        # commit_draft_before_file creating new DraftStreamer)
        if self._finalized:
            logger.debug("draft_streamer.keepalive_skipped",
                         chat_id=self.chat_id,
                         draft_id=self.draft_id,
                         reason="finalized")
            return True

        if not self.last_text:
            logger.debug("draft_streamer.keepalive_skipped",
                         chat_id=self.chat_id,
                         draft_id=self.draft_id,
                         reason="no_last_text")
            return True

        try:
            await self.bot(
                SendMessageDraft(
                    chat_id=self.chat_id,
                    draft_id=self.draft_id,
                    text=self.last_text,
                    message_thread_id=self.topic_id,
                    parse_mode=parse_mode,
                ))
            self._last_update_time = time.time()
            logger.debug("draft_streamer.keepalive",
                         chat_id=self.chat_id,
                         draft_id=self.draft_id)
            return True
        except TelegramRetryAfter as e:
            logger.warning("draft_streamer.keepalive_flood",
                           chat_id=self.chat_id,
                           retry_after=e.retry_after)
            await asyncio.sleep(e.retry_after)
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("draft_streamer.keepalive_failed",
                           chat_id=self.chat_id,
                           error=str(e))
            return False

    async def finalize(self,
                       final_text: Optional[str] = None,
                       parse_mode: Optional[str] = "HTML") -> types.Message:
        """Convert draft to permanent message.

        Flushes any pending text, then sends final message.
        Draft disappears automatically.

        If final_text is provided, updates draft to final_text first for smooth
        transition, then sends final_text directly (no edit needed).

        Args:
            final_text: Optional final text to show. If provided, this text
                will be sent directly (draft updated first for smooth visual).
            parse_mode: Parse mode for final message.

        Returns:
            Final sent Message object.

        Raises:
            Exception: If send_message fails.
        """
        # If final_text is provided and differs, update draft first for smooth
        # visual transition. Otherwise, flush any pending text.
        if final_text and final_text.strip() != self.last_text.strip():
            await self.update(final_text, parse_mode, force=True)
        else:
            # No final_text or same text - just flush pending
            await self.flush_pending(parse_mode)

        # Mark as finalized BEFORE send_message to prevent keepalive race condition
        # (keepalive might read draft_streamer after finalize starts but before
        # commit_draft_before_file creates new DraftStreamer)
        self._finalized = True

        # Determine what text to send (after any updates)
        text_to_send = final_text if final_text else self.last_text

        logger.info("draft_streamer.finalizing",
                    chat_id=self.chat_id,
                    topic_id=self.topic_id,
                    total_updates=self._update_count,
                    final_length=len(text_to_send))

        # Send final message directly with correct text (no edit needed)
        message = await self.bot.send_message(
            chat_id=self.chat_id,
            text=text_to_send,
            message_thread_id=self.topic_id,
            parse_mode=parse_mode,
        )

        return message

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
