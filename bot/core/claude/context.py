"""Context management for conversation threads.

This module handles building conversation context that fits within model's
token limits. Uses token counting to include maximum possible history.

NO __init__.py - use direct import: from core.claude.context import ContextManager
"""

from typing import List

from core.base import LLMProvider
from core.exceptions import ContextWindowExceededError
from core.models import Message
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class ContextManager:
    """Manages conversation context with token limits.

    Builds conversation context from message history, ensuring it fits
    within the model's context window. Uses provider's token counter for
    accurate token counting.

    Algorithm:
    1. Reserve tokens for system prompt and output
    2. Count tokens for messages from newest to oldest
    3. Include messages until hitting token limit
    4. Return messages in chronological order (oldest first)
    """

    def __init__(self, provider: LLMProvider):
        """Initialize ContextManager.

        Args:
            provider: LLM provider for token counting.
        """
        self.provider = provider

    async def build_context(
        self,
        messages: List[Message],
        model_context_window: int,
        system_prompt: str | int,
        max_output_tokens: int,
        buffer_percent: float = 0.10,
    ) -> List[Message]:
        """Build context that fits in model's window.

        Includes as many messages as possible from history while staying
        within token limits. Prioritizes recent messages (newest first).

        Args:
            messages: All messages from thread (oldest first).
            model_context_window: Max tokens for model.
            system_prompt: System prompt text OR pre-computed character length
                (for multi-block prompts, pass total length as int).
            max_output_tokens: Tokens reserved for response.
            buffer_percent: Safety buffer (0.0-1.0).

        Returns:
            Messages that fit in context window (oldest first).

        Raises:
            ContextWindowExceededError: If even single message exceeds limit.
        """
        logger.info("context_manager.build_context.start",
                    total_messages=len(messages),
                    context_window=model_context_window,
                    max_output=max_output_tokens)

        # Calculate available tokens for history
        # Accept either string (legacy) or int (pre-computed length for multi-block)
        if isinstance(system_prompt, int):
            system_tokens = system_prompt // 4  # Estimate from char count
        else:
            system_tokens = await self.provider.get_token_count(system_prompt)
        buffer_tokens = int(model_context_window * buffer_percent)
        available_tokens = (model_context_window - system_tokens -
                            max_output_tokens - buffer_tokens)

        logger.debug("context_manager.tokens_reserved",
                     system_tokens=system_tokens,
                     max_output_tokens=max_output_tokens,
                     buffer_tokens=buffer_tokens,
                     available_for_history=available_tokens)

        if available_tokens <= 0:
            raise ContextWindowExceededError(
                "No tokens available for history after reserving for "
                "system prompt and output",
                tokens_used=system_tokens + max_output_tokens + buffer_tokens,
                tokens_limit=model_context_window)

        # Count tokens backwards (newest to oldest)
        included_messages = []
        tokens_used = 0

        for message in reversed(messages):
            message_tokens = await self.provider.get_token_count(message.content
                                                                )

            if tokens_used + message_tokens > available_tokens:
                # This message would exceed limit
                logger.debug("context_manager.message_skipped",
                             role=message.role,
                             tokens=message_tokens,
                             reason="would_exceed_limit")
                break

            tokens_used += message_tokens
            included_messages.append(message)

        # Reverse to get chronological order (oldest first)
        included_messages.reverse()

        # Check if we included any messages
        if not included_messages and messages:
            # First message itself is too large
            first_msg_tokens = await self.provider.get_token_count(
                messages[-1].content)
            raise ContextWindowExceededError(
                f"Single message exceeds available context "
                f"({first_msg_tokens} > {available_tokens})",
                tokens_used=first_msg_tokens,
                tokens_limit=available_tokens)

        logger.info("context_manager.build_context.complete",
                    included_messages=len(included_messages),
                    skipped_messages=len(messages) - len(included_messages),
                    tokens_used=tokens_used,
                    tokens_available=available_tokens,
                    utilization_percent=round(
                        (tokens_used / available_tokens) * 100, 2))

        return included_messages
