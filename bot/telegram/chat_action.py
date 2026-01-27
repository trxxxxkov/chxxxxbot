"""Chat action utilities for Telegram typing indicators.

This module provides helpers for sending chat actions (typing, uploading, etc.)
to show users that the bot is working on something.

Available actions:
- typing: For text generation
- upload_photo: For sending photos
- upload_document: For sending files
- upload_video: For sending videos
- upload_voice: For sending voice messages
- record_voice: For recording voice
- record_video: For recording video
- choose_sticker: For sticker selection
- find_location: For location search

NO __init__.py - use direct import:
    from telegram.chat_action import send_action, ChatActionContext
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Literal, Optional, TYPE_CHECKING

from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot

logger = get_logger(__name__)

# Type alias for chat actions
ChatAction = Literal[
    "typing",
    "upload_photo",
    "upload_document",
    "upload_video",
    "upload_voice",
    "record_voice",
    "record_video",
    "record_video_note",
    "upload_video_note",
    "choose_sticker",
    "find_location",
]


async def send_action(
    bot: "Bot",
    chat_id: int,
    action: ChatAction = "typing",
    message_thread_id: Optional[int] = None,
) -> bool:
    """Send a chat action to indicate bot activity.

    Chat actions are automatically cleared after 5 seconds or when
    a message is sent, so they need to be refreshed for long operations.

    Args:
        bot: Telegram Bot instance.
        chat_id: Target chat ID.
        action: Type of action to show.
        message_thread_id: Forum topic ID (optional).

    Returns:
        True on success, False on failure.
    """
    try:
        await bot.send_chat_action(
            chat_id=chat_id,
            action=action,
            message_thread_id=message_thread_id,
        )
        logger.info(
            "chat_action.sent",
            chat_id=chat_id,
            action=action,
            thread_id=message_thread_id,
        )
        return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        # Don't fail the operation if chat action fails
        logger.warning(
            "chat_action.failed",
            chat_id=chat_id,
            action=action,
            error=str(e),
        )
        return False


@asynccontextmanager
async def continuous_action(
    bot: "Bot",
    chat_id: int,
    action: ChatAction = "typing",
    message_thread_id: Optional[int] = None,
    interval: float = 4.0,
):
    """Context manager that continuously sends chat action.

    Telegram clears chat actions after 5 seconds, so this sends
    the action periodically until the context exits.

    Usage:
        async with continuous_action(bot, chat_id, "typing"):
            await long_running_operation()

    Args:
        bot: Telegram Bot instance.
        chat_id: Target chat ID.
        action: Type of action to show.
        message_thread_id: Forum topic ID (optional).
        interval: Seconds between action refreshes (default: 4.0).
    """
    task: Optional[asyncio.Task] = None
    stop_event = asyncio.Event()

    async def action_loop():
        """Send chat action periodically until stopped."""
        while not stop_event.is_set():
            await send_action(bot, chat_id, action, message_thread_id)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
                break  # Event was set
            except asyncio.TimeoutError:
                pass  # Continue loop

    try:
        # Start the action loop
        task = asyncio.create_task(action_loop())
        yield
    finally:
        # Stop the action loop
        stop_event.set()
        if task:
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


class ChatActionContext:
    """Helper class for managing chat actions in tools.

    Provides a simple interface for tools to send appropriate
    chat actions without needing to import bot directly.

    Usage:
        ctx = ChatActionContext(bot, chat_id, topic_id)
        await ctx.typing()
        await ctx.uploading_photo()
    """

    def __init__(
        self,
        bot: "Bot",
        chat_id: int,
        message_thread_id: Optional[int] = None,
    ):
        """Initialize chat action context.

        Args:
            bot: Telegram Bot instance.
            chat_id: Target chat ID.
            message_thread_id: Forum topic ID (optional).
        """
        self.bot = bot
        self.chat_id = chat_id
        self.message_thread_id = message_thread_id

    async def send(self, action: ChatAction) -> bool:
        """Send a chat action.

        Args:
            action: Type of action to show.

        Returns:
            True on success.
        """
        return await send_action(
            self.bot,
            self.chat_id,
            action,
            self.message_thread_id,
        )

    async def typing(self) -> bool:
        """Show typing indicator."""
        return await self.send("typing")

    async def uploading_photo(self) -> bool:
        """Show uploading photo indicator."""
        return await self.send("upload_photo")

    async def uploading_document(self) -> bool:
        """Show uploading document indicator."""
        return await self.send("upload_document")

    async def uploading_video(self) -> bool:
        """Show uploading video indicator."""
        return await self.send("upload_video")

    async def uploading_voice(self) -> bool:
        """Show uploading voice indicator."""
        return await self.send("upload_voice")

    async def recording_voice(self) -> bool:
        """Show recording voice indicator."""
        return await self.send("record_voice")

    async def recording_video(self) -> bool:
        """Show recording video indicator."""
        return await self.send("record_video")

    async def choosing_sticker(self) -> bool:
        """Show choosing sticker indicator."""
        return await self.send("choose_sticker")

    async def finding_location(self) -> bool:
        """Show finding location indicator."""
        return await self.send("find_location")

    def continuous(
        self,
        action: ChatAction = "typing",
        interval: float = 4.0,
    ):
        """Get context manager for continuous action.

        Args:
            action: Type of action to show.
            interval: Seconds between refreshes.

        Returns:
            Async context manager.
        """
        return continuous_action(
            self.bot,
            self.chat_id,
            action,
            self.message_thread_id,
            interval,
        )
