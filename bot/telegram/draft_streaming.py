"""Draft-based streaming for Telegram Bot API 9.3.

This module provides DraftStreamer class for streaming responses using
sendMessageDraft method with proper rate limiting.

Supports both MarkdownV2 (default) and HTML parse modes.

NO __init__.py - use direct import: from telegram.draft_streaming import DraftStreamer
"""

import asyncio
from asyncio import Task
import random
import time
from typing import Literal, Optional

from aiogram import Bot
from aiogram import types
from aiogram.exceptions import TelegramBadRequest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessageDraft
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Type alias for parse mode
ParseMode = Literal["MarkdownV2", "HTML"]

# Default parse mode
DEFAULT_PARSE_MODE: ParseMode = "MarkdownV2"

# Minimum interval between draft updates (seconds)
# sendMessageDraft still has rate limits, just more relaxed than edit_message
MIN_UPDATE_INTERVAL = 0.6

# Default keepalive interval (seconds)
DEFAULT_KEEPALIVE_INTERVAL = 6.0

# Minimum time since last update before sending keepalive (seconds)
# If we recently sent an update, skip keepalive to avoid flood control
MIN_TIME_BEFORE_KEEPALIVE = 3.0


class DraftManager:
    """Manages multiple DraftStreamers with automatic cleanup.

    Handles the common pattern where streaming may create multiple drafts
    (e.g., when files are sent between text sections).

    Implements async context manager for automatic resource cleanup.

    Example:
        async with DraftManager(bot, chat_id, topic_id) as dm:
            await dm.current.update("Processing...")
            # Send a file - this finalizes current draft
            await dm.commit_and_create_new()
            await dm.current.update("Done!")
            return await dm.current.finalize()
    """

    def __init__(
            self,
            bot: Bot,
            chat_id: int,
            topic_id: Optional[int] = None,
            keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL) -> None:
        """Initialize draft manager.

        Args:
            bot: Telegram Bot instance.
            chat_id: Target chat ID.
            topic_id: Telegram forum topic ID (None for main chat).
            keepalive_interval: Seconds between keepalive updates.
        """
        self.bot = bot
        self.chat_id = chat_id
        self.topic_id = topic_id
        self.keepalive_interval = keepalive_interval
        self._current: Optional["DraftStreamer"] = None

    @property
    def current(self) -> "DraftStreamer":
        """Get current draft streamer (creates one if needed)."""
        if self._current is None:
            self._current = DraftStreamer(
                bot=self.bot,
                chat_id=self.chat_id,
                topic_id=self.topic_id,
            )
            self._current.start_keepalive(self.keepalive_interval)
        return self._current

    async def commit_and_create_new(
            self,
            final_text: Optional[str] = None,
            parse_mode: ParseMode = DEFAULT_PARSE_MODE) -> None:
        """Finalize current draft and prepare for new one.

        Use this when sending files - commits current content, then
        prepares for lazy creation of new draft after file is sent.

        The new draft is NOT created immediately - it will be created
        lazily on first access to `current`. This ensures the draft
        appears AFTER any files sent between commit and next text.

        Args:
            final_text: Optional final text for current draft.
            parse_mode: "MarkdownV2" (default) or "HTML".
        """
        if self._current is not None:
            if final_text:
                await self._current.finalize(final_text=final_text,
                                             parse_mode=parse_mode)
            else:
                await self._current.clear()

        # Clear current - new streamer will be created lazily on demand
        # This ensures new draft appears AFTER files, not before
        self._current = None

    async def cleanup(self) -> None:
        """Cleanup current draft streamer."""
        if self._current is not None:
            await self._current.clear()
            self._current = None

    async def __aenter__(self) -> "DraftManager":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit async context manager - ensure cleanup."""
        await self.cleanup()
        logger.debug("draft_manager.context_exit",
                     chat_id=self.chat_id,
                     had_exception=exc_type is not None)
        return False


class DraftStreamer:  # pylint: disable=too-many-instance-attributes
    """Manages draft-based message streaming with rate limiting.

    Uses sendMessageDraft for smooth animated updates.
    Bot API 9.3 feature - requires forum topic mode enabled.

    Includes built-in throttling to avoid flood control.
    Implements async context manager for automatic resource cleanup.

    Attributes:
        bot: Telegram Bot instance.
        chat_id: Target chat ID.
        topic_id: Telegram forum topic ID (message_thread_id).
        draft_id: Unique draft identifier for animated updates.
        last_text: Last sent text (to avoid duplicate updates).

    Example (recommended - using context manager):
        async with DraftStreamer(bot, chat_id=123, topic_id=456) as streamer:
            await streamer.update("Thinking...")
            await streamer.update("Done!")
            return await streamer.finalize()
        # Automatic cleanup on exit (even on exceptions)

    Example (manual management):
        streamer = DraftStreamer(bot, chat_id=123, topic_id=456)
        streamer.start_keepalive()
        try:
            await streamer.update("Thinking...")
            return await streamer.finalize()
        except Exception:
            await streamer.clear()
            raise
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
        self._keepalive_task: Optional[Task[None]] = None  # Managed keepalive
        self._keepalive_interval: float = 5.0  # Default keepalive interval
        self._last_parse_mode: Optional[str] = DEFAULT_PARSE_MODE  # Track mode
        self._keepalive_failure_logged = False  # Prevent repeated warnings

        logger.debug("draft_streamer.initialized",
                     chat_id=chat_id,
                     topic_id=topic_id,
                     draft_id=self.draft_id)

    async def __aenter__(self) -> "DraftStreamer":
        """Enter async context manager - start keepalive.

        Returns:
            Self for use in 'async with' statement.
        """
        self.start_keepalive(self._keepalive_interval)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit async context manager - ensure cleanup.

        Automatically stops keepalive task and clears draft on any exit,
        including exceptions. This prevents resource leaks.

        Args:
            exc_type: Exception type (if any).
            exc_val: Exception value (if any).
            exc_tb: Exception traceback (if any).

        Returns:
            False to propagate exceptions (never suppresses).
        """
        # Always cleanup - clear() is idempotent
        await self.clear()
        logger.debug("draft_streamer.context_exit",
                     chat_id=self.chat_id,
                     draft_id=self.draft_id,
                     had_exception=exc_type is not None)
        return False  # Don't suppress exceptions

    def set_keepalive_interval(self, interval: float) -> "DraftStreamer":
        """Set keepalive interval (for use before entering context).

        Args:
            interval: Seconds between keepalive updates.

        Returns:
            Self for method chaining.
        """
        self._keepalive_interval = interval
        return self

    def start_keepalive(self, interval: float = 5.0) -> None:
        """Start automatic keepalive task.

        Creates a background task that periodically sends keepalive updates
        to prevent the draft from disappearing during long operations.

        The task is automatically cancelled when finalize() or clear() is called.

        Args:
            interval: Seconds between keepalive updates (default: 5.0).
        """
        if self._keepalive_task is not None:
            return  # Already running

        async def keepalive_loop() -> None:
            """Send periodic keepalive updates."""
            while True:
                await asyncio.sleep(interval)
                await self.keepalive()

        self._keepalive_task = asyncio.create_task(keepalive_loop())
        logger.debug("draft_streamer.keepalive_started",
                     chat_id=self.chat_id,
                     draft_id=self.draft_id,
                     interval=interval)

    async def stop_keepalive(self) -> None:
        """Stop the automatic keepalive task.

        Called automatically by finalize() and clear().
        Safe to call multiple times or when no task is running.
        """
        if self._keepalive_task is None:
            return

        self._keepalive_task.cancel()
        try:
            await self._keepalive_task
        except asyncio.CancelledError:
            pass
        self._keepalive_task = None
        logger.debug("draft_streamer.keepalive_stopped",
                     chat_id=self.chat_id,
                     draft_id=self.draft_id)

    async def update(  # pylint: disable=too-many-return-statements
            self,
            text: str,
            parse_mode: Optional[str] = DEFAULT_PARSE_MODE,
            force: bool = False) -> bool:
        """Update draft with new text (with throttling).

        Skips update if text hasn't changed or if called too frequently.
        Handles TelegramRetryAfter by waiting and retrying.
        Falls back to plain text if MarkdownV2 parsing fails.

        Args:
            text: New text content (1-4096 chars).
            parse_mode: Parse mode for formatting (MarkdownV2, HTML, None).
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
            self._last_parse_mode = parse_mode  # Track successful parse_mode
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
                self._last_parse_mode = parse_mode  # Track successful parse_mode
                self._update_count += 1
                self._last_update_time = time.time()
                return True
            except Exception:  # pylint: disable=broad-exception-caught
                return False

        except TelegramBadRequest as e:
            # MarkdownV2 parse error - fallback to plain text
            if "can't parse entities" in str(e).lower() and parse_mode:
                logger.warning("draft_streamer.parse_error_fallback",
                               chat_id=self.chat_id,
                               draft_id=self.draft_id,
                               parse_mode=parse_mode,
                               error=str(e))
                return await self.update(text_to_send,
                                         parse_mode=None,
                                         force=force)
            logger.warning("draft_streamer.update_failed",
                           chat_id=self.chat_id,
                           draft_id=self.draft_id,
                           error=str(e))
            return False

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("draft_streamer.update_failed",
                           chat_id=self.chat_id,
                           draft_id=self.draft_id,
                           error=str(e))
            # Try without parse_mode as fallback
            if parse_mode:
                return await self.update(text_to_send,
                                         parse_mode=None,
                                         force=force)
            return False

    async def flush_pending(self,
                            parse_mode: Optional[str] = DEFAULT_PARSE_MODE
                           ) -> bool:
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

    async def keepalive(  # pylint: disable=too-many-return-statements
            self,
            parse_mode: Optional[str] = DEFAULT_PARSE_MODE) -> bool:
        """Send keep-alive update to prevent draft from disappearing.

        Unlike update(), this always sends even if text unchanged.
        Use during long operations like image generation.

        Skips if we recently sent an update (within MIN_TIME_BEFORE_KEEPALIVE)
        to avoid flood control.

        Uses the last successful parse_mode to avoid parse errors when
        previous update fell back to plain text.

        Args:
            parse_mode: Parse mode for formatting (overridden by tracked mode).

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

        # Skip if we recently sent an update (avoids redundant keepalive)
        time_since_update = time.time() - self._last_update_time
        if time_since_update < MIN_TIME_BEFORE_KEEPALIVE:
            logger.debug("draft_streamer.keepalive_skipped",
                         chat_id=self.chat_id,
                         draft_id=self.draft_id,
                         reason="recent_update",
                         seconds_ago=round(time_since_update, 1))
            return True

        return await self._send_keepalive(self._last_parse_mode)

    async def _send_keepalive(self,
                              effective_parse_mode: Optional[str]) -> bool:
        """Send keepalive with specified parse mode, with fallback.

        Args:
            effective_parse_mode: Parse mode to use for sending.

        Returns:
            True on success, False on failure.
        """
        try:
            await self.bot(
                SendMessageDraft(
                    chat_id=self.chat_id,
                    draft_id=self.draft_id,
                    text=self.last_text,
                    message_thread_id=self.topic_id,
                    parse_mode=effective_parse_mode,
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
        except TelegramBadRequest as e:
            # Parse error - try again with plain text and track it
            if "can't parse entities" in str(
                    e).lower() and effective_parse_mode:
                if not self._keepalive_failure_logged:
                    logger.warning("draft_streamer.keepalive_parse_error",
                                   chat_id=self.chat_id,
                                   error=str(e))
                self._last_parse_mode = None  # Track fallback
                return await self._send_keepalive(None)  # Retry without parse
            # Log only first failure to avoid log flooding
            if not self._keepalive_failure_logged:
                logger.warning("draft_streamer.keepalive_failed",
                               chat_id=self.chat_id,
                               error=str(e))
                self._keepalive_failure_logged = True
            return False
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Log only first failure to avoid log flooding
            if not self._keepalive_failure_logged:
                logger.warning("draft_streamer.keepalive_failed",
                               chat_id=self.chat_id,
                               error=str(e))
                self._keepalive_failure_logged = True
            return False

    async def finalize(
            self,
            final_text: Optional[str] = None,
            parse_mode: Optional[str] = DEFAULT_PARSE_MODE) -> types.Message:
        """Convert draft to permanent message.

        Flushes any pending text, then sends final message.
        Draft disappears automatically.

        If final_text is provided, updates draft to final_text first for smooth
        transition, then sends final_text directly (no edit needed).

        Falls back to plain text if MarkdownV2 parsing fails.

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

        # Stop keepalive task if running (prevents resource leak)
        await self.stop_keepalive()

        # Determine what text to send (after any updates)
        text_to_send = final_text if final_text else self.last_text

        logger.info("draft_streamer.finalizing",
                    chat_id=self.chat_id,
                    topic_id=self.topic_id,
                    total_updates=self._update_count,
                    final_length=len(text_to_send))

        # Send final message directly with correct text (no edit needed)
        # Falls back to plain text if MarkdownV2 parsing fails
        try:
            message = await self.bot.send_message(
                chat_id=self.chat_id,
                text=text_to_send,
                message_thread_id=self.topic_id,
                parse_mode=parse_mode,
            )
        except TelegramBadRequest as e:
            if "can't parse entities" in str(e).lower() and parse_mode:
                logger.warning("draft_streamer.finalize_parse_error_fallback",
                               chat_id=self.chat_id,
                               parse_mode=parse_mode,
                               error=str(e))
                message = await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text_to_send,
                    message_thread_id=self.topic_id,
                    parse_mode=None,  # Fallback to plain text
                )
            else:
                raise

        return message

    async def clear(self) -> bool:
        """Clear/hide draft without sending final message.

        Useful when streaming is interrupted or cancelled.

        Simply marks the draft as finalized and stops keepalive.
        The draft will disappear naturally after a few seconds without updates.

        Note: We don't try to send empty/invisible content because Telegram
        rejects it with "text must be non-empty". The natural timeout approach
        is cleaner and more reliable.

        Safe to call multiple times or after finalize().

        Returns:
            True on success.
        """
        # Skip if already finalized (idempotent - safe to call after finalize)
        if self._finalized:
            await self.stop_keepalive()  # Ensure keepalive is stopped
            return True

        # Mark as finalized to prevent further updates
        self._finalized = True
        await self.stop_keepalive()  # Stop keepalive task if running

        logger.debug("draft_streamer.cleared",
                     chat_id=self.chat_id,
                     draft_id=self.draft_id,
                     had_content=bool(self.last_text))
        return True
