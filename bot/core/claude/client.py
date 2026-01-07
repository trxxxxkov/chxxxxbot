"""Claude API client implementation.

This module implements the LLMProvider interface for Claude using the
official Anthropic SDK. Handles streaming, token counting, error handling,
and comprehensive logging.

NO __init__.py - use direct import: from core.claude.client import ClaudeProvider
"""

import time
from typing import AsyncIterator, Optional

import anthropic
from core.base import LLMProvider
from core.exceptions import APIConnectionError
from core.exceptions import APITimeoutError
from core.exceptions import InvalidModelError
from core.exceptions import RateLimitError
from core.models import LLMRequest
from core.models import TokenUsage
from utils.structured_logging import get_logger

logger = get_logger(__name__)


class ClaudeProvider(LLMProvider):
    """Claude API client implementing LLMProvider interface.

    Uses official Anthropic SDK for API communication. Supports streaming
    responses without buffering, comprehensive error handling, and detailed
    logging for observability.

    Attributes:
        client: Anthropic async client.
        last_usage: Token usage from last API call.
    """

    def __init__(self, api_key: str):
        """Initialize Claude provider.

        Args:
            api_key: Anthropic API key.
        """
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.last_usage: Optional[TokenUsage] = None

        logger.info("claude_provider.initialized")

    async def stream_message(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream response from Claude API.

        Yields text chunks as they arrive without buffering. Tracks token
        usage after stream completes for billing.

        Args:
            request: LLM request with messages and configuration.

        Yields:
            Text chunks as they arrive from API.

        Raises:
            RateLimitError: Rate limit exceeded (429).
            APIConnectionError: Connection to API failed.
            APITimeoutError: API request timed out.
            InvalidModelError: Model not supported.
        """
        start_time = time.time()

        logger.info("claude.stream.start",
                    model=request.model,
                    message_count=len(request.messages),
                    system_prompt_length=len(request.system_prompt or ""),
                    max_tokens=request.max_tokens,
                    temperature=request.temperature)

        # Convert messages to Anthropic format
        api_messages = [{
            "role": msg.role,
            "content": msg.content
        } for msg in request.messages]

        # Prepare request parameters
        api_params = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": api_messages,
        }

        if request.system_prompt:
            api_params["system"] = request.system_prompt

        try:
            # Stream response
            total_chunks = 0
            response_text = ""

            async with self.client.messages.stream(**api_params) as stream:
                async for text in stream.text_stream:
                    total_chunks += 1
                    response_text += text

                    logger.debug("claude.stream.chunk",
                                 chunk_number=total_chunks,
                                 chunk_length=len(text))

                    yield text

                # Get final message with usage stats
                final_message = await stream.get_final_message()

            # Track usage
            self.last_usage = TokenUsage(
                input_tokens=final_message.usage.input_tokens,
                output_tokens=final_message.usage.output_tokens,
                cache_read_tokens=0,  # Phase 1.4
                cache_creation_tokens=0  # Phase 1.4
            )

            duration_ms = (time.time() - start_time) * 1000

            logger.info("claude.stream.complete",
                        model=request.model,
                        input_tokens=self.last_usage.input_tokens,
                        output_tokens=self.last_usage.output_tokens,
                        total_chunks=total_chunks,
                        response_length=len(response_text),
                        duration_ms=round(duration_ms, 2),
                        stop_reason=final_message.stop_reason)

        except anthropic.RateLimitError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error("claude.stream.rate_limit",
                         model=request.model,
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)

            raise RateLimitError(
                "Rate limit exceeded. Please try again later.",
                retry_after=None  # Parse from headers if available
            ) from e

        except anthropic.APIConnectionError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error("claude.stream.connection_error",
                         model=request.model,
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)

            raise APIConnectionError(
                "Failed to connect to Claude API. Please check your internet "
                "connection.") from e

        except anthropic.APITimeoutError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error("claude.stream.timeout",
                         model=request.model,
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)

            raise APITimeoutError(
                "Request to Claude API timed out. Please try again.") from e

        except anthropic.NotFoundError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error("claude.stream.invalid_model",
                         model=request.model,
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)

            raise InvalidModelError(
                f"Model '{request.model}' not found or not accessible.") from e

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error("claude.stream.unexpected_error",
                         model=request.model,
                         error=str(e),
                         error_type=type(e).__name__,
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)
            raise

    async def get_token_count(self, text: str) -> int:
        """Count tokens in text using Claude tokenizer.

        Uses Anthropic SDK's token counting (if available) or fallback
        estimation based on character count.

        Args:
            text: Text to count tokens for.

        Returns:
            Approximate number of tokens.
        """
        # Simple estimation: ~4 chars per token (conservative)
        # TODO: Use official Anthropic tokenizer  # pylint: disable=fixme
        estimated_tokens = len(text) // 4

        logger.debug("claude.token_count",
                     text_length=len(text),
                     estimated_tokens=estimated_tokens)

        return estimated_tokens

    async def get_usage(self) -> TokenUsage:
        """Get token usage for last API call.

        Returns:
            Token usage statistics.

        Raises:
            ValueError: If called before any API call completed.
        """
        if self.last_usage is None:
            raise ValueError(
                "No usage data available. Call stream_message() first.")

        return self.last_usage
