"""Abstract base interface for LLM providers.

This module defines the abstract LLMProvider class that all LLM providers
(Claude, OpenAI, Google) must implement. Ensures consistent interface across
providers for streaming, token counting, and usage tracking.

NO __init__.py - use direct import: from core.base import LLMProvider
"""

from abc import ABC
from abc import abstractmethod
from typing import AsyncIterator

from core.models import LLMRequest
from core.models import TokenUsage


class LLMProvider(ABC):
    """Abstract interface for LLM providers.

    All LLM providers must implement this interface to ensure consistent
    behavior across different models and vendors.

    Principles:
    - Streaming-first: All providers must support streaming
    - No buffering: Chunks yielded immediately as received
    - Token tracking: Must track input/output tokens for billing
    """

    @abstractmethod
    async def stream_message(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream response tokens from LLM.

        Yields text chunks as they arrive from the API without buffering.
        Each chunk should be yielded immediately for real-time user experience.

        Args:
            request: LLM request with messages, system prompt, model config.

        Yields:
            Text chunks as they arrive from API.

        Raises:
            RateLimitError: Rate limit exceeded (429).
            APIConnectionError: Failed to connect to API.
            APITimeoutError: API request timed out.
            ContextWindowExceededError: Context exceeds model's window.
        """
        pass  # pylint: disable=unnecessary-pass

    @abstractmethod
    async def get_token_count(self, text: str) -> int:
        """Count tokens in text using provider's tokenizer.

        Used for context management to ensure messages fit in model's
        context window.

        Args:
            text: Text to count tokens for.

        Returns:
            Number of tokens in text.
        """
        pass  # pylint: disable=unnecessary-pass

    @abstractmethod
    async def get_usage(self) -> TokenUsage:
        """Get token usage for last API call.

        Must be called after stream_message() completes to get accurate
        token counts for billing.

        Returns:
            Token usage stats (input, output, cache tokens).

        Raises:
            ValueError: If called before any API call completed.
        """
        pass  # pylint: disable=unnecessary-pass

    def get_stop_reason(self) -> str | None:
        """Get stop reason from last API call.

        Phase 1.4.4: Stop reason handling for better error messages.
        Common stop reasons across providers:
        - "end_turn": Normal completion
        - "max_tokens": Output length limit reached
        - "model_context_window_exceeded": Input too large (Claude 4.5+)
        - "refusal": Model refused to answer (Claude 4.5+)
        - "stop_sequence": Stop sequence encountered
        - "tool_use": Tool call requested (Phase 1.5)

        Returns:
            Stop reason string or None if not available or no call made yet.
        """
        return None  # Default implementation returns None
