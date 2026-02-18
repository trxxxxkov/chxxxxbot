"""Claude API client implementation.

This module implements the LLMProvider interface for Claude using the
official Anthropic SDK. Handles streaming, token counting, error handling,
and comprehensive logging.

NO __init__.py - use direct import: from core.claude.client import ClaudeProvider
"""

import asyncio
import json
import time
from typing import AsyncIterator, Optional

import anthropic
from config import get_model
from core.base import LLMProvider
from core.exceptions import APIConnectionError
from core.exceptions import APITimeoutError
from core.exceptions import InvalidModelError
from core.exceptions import OverloadedError
from core.exceptions import RateLimitError
from core.models import LLMRequest
from core.models import StreamEvent
from core.models import TokenUsage
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def _get_error_type(e: anthropic.APIStatusError) -> Optional[str]:
    """Extract error type from APIStatusError body.

    Mid-stream SSE errors arrive with HTTP 200 (stream already established),
    so status_code is not reliable. The error type is in the JSON body.
    """
    body = getattr(e, 'body', None)
    if isinstance(body, dict):
        error_info = body.get('error')
        if isinstance(error_info, dict):
            return error_info.get('type')
    return None


def _is_retriable_server_error(e: anthropic.APIStatusError) -> bool:
    """Check if an APIStatusError is a retriable server-side error.

    Retriable errors:
    - HTTP 529 or body type 'overloaded_error' (API overloaded)
    - HTTP 500 or body type 'api_error' (internal server error)
    """
    if e.status_code in (500, 529):
        return True
    error_type = _get_error_type(e)
    return error_type in ('overloaded_error', 'api_error')


def _filter_empty_messages(messages: list) -> list:
    """Filter out messages with empty content.

    Claude API requires all messages to have non-empty content
    (except for optional final assistant message).

    Args:
        messages: List of Message objects.

    Returns:
        List of dicts with role/content, empty messages filtered out.
    """
    result = []
    for msg in messages:
        content = msg.content
        # Skip messages with empty content
        if content is None:
            continue
        if isinstance(content, str) and not content.strip():
            continue
        if isinstance(content, list) and not content:
            continue
        result.append({"role": msg.role, "content": content})
    return result


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
        # Beta headers for advanced features
        # - interleaved-thinking: Extended Thinking feature
        # - context-management: Context editing (thinking block clearing)
        # - compact: Server-side compaction (Opus 4.6)
        # - files-api: Files API for multimodal content
        # - code-execution-web-tools: Dynamic filtering for web search/fetch
        # Note: effort, web-search, extended-cache-ttl are now GA
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            default_headers={
                "anthropic-beta": ("interleaved-thinking-2025-05-14,"
                                   "context-management-2025-06-27,"
                                   "compact-2026-01-12,"
                                   "files-api-2025-04-14,"
                                   "code-execution-web-tools-2026-02-09")
            })
        self.last_usage: Optional[TokenUsage] = None
        self.last_message: Optional[
            anthropic.types.Message] = None  # Phase 1.5: for tool use
        self.last_thinking: Optional[
            str] = None  # Phase 1.4.3: Extended Thinking
        self.last_compaction: Optional[str] = None  # Opus 4.6: compaction

        logger.debug("claude_provider.initialized",
                     beta_features=[
                         "interleaved-thinking", "context-management",
                         "compact", "files-api", "code-execution-web-tools"
                     ])

    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    async def get_message(self, request: LLMRequest) -> anthropic.types.Message:
        """Get complete message from Claude API (non-streaming).

        Used for tool use where we need the complete response before
        proceeding. Does not stream - waits for full response.

        Args:
            request: LLM request with messages and configuration.

        Returns:
            Complete Message object with content, usage, stop_reason.

        Raises:
            RateLimitError: Rate limit exceeded (429).
            APIConnectionError: Connection to API failed.
            APITimeoutError: API request timed out.
            InvalidModelError: Model not supported or wrong provider.

        Examples:
            >>> request = LLMRequest(messages=[...], tools=[...])
            >>> response = await provider.get_message(request)
            >>> if response.stop_reason == "tool_use":
            ...     # Extract and execute tools
        """
        start_time = time.time()

        # Get model configuration
        try:
            model_config = get_model(request.model)
        except KeyError as e:
            raise InvalidModelError(
                f"Model '{request.model}' not found in registry. {e}") from e

        if model_config.provider != "claude":
            raise InvalidModelError(
                f"ClaudeProvider can only handle 'claude' models, "
                f"got provider '{model_config.provider}' for model "
                f"'{request.model}'")

        logger.info("claude.get_message.start",
                    model_full_id=request.model,
                    model_api_id=model_config.model_id,
                    message_count=len(request.messages),
                    has_tools=request.tools is not None,
                    tool_count=len(request.tools) if request.tools else 0)

        # Convert messages to Anthropic format, filtering empty messages
        api_messages = _filter_empty_messages(request.messages)

        # Prepare API parameters
        api_params = {
            "model": model_config.model_id,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": api_messages,
        }

        # Add tools if provided
        if request.tools:
            api_params["tools"] = request.tools
            logger.info("claude.get_message.tools_enabled",
                        tool_count=len(request.tools))

        # System prompt with conditional caching
        # Supports both string (legacy) and list of blocks (multi-block caching)
        if request.system_prompt:
            if isinstance(request.system_prompt, list):
                # Multi-block format - already has cache_control per block
                api_params["system"] = request.system_prompt
            else:
                # Legacy string format - apply single-block caching
                estimated_tokens = len(request.system_prompt) // 4
                use_caching = estimated_tokens >= 1024

                if use_caching:
                    api_params["system"] = [{
                        "type": "text",
                        "text": request.system_prompt,
                        "cache_control": {
                            "type": "ephemeral",
                            "ttl": "1h"
                        }
                    }]
                else:
                    api_params["system"] = request.system_prompt

        # Effort parameter (GA via output_config)
        if model_config.has_capability("effort"):
            api_params["output_config"] = {"effort": "high"}
            logger.debug("claude.effort.enabled", effort="high")

        # Adaptive thinking (Opus 4.6) or manual extended thinking
        if model_config.has_capability("adaptive_thinking"):
            api_params["thinking"] = {"type": "adaptive"}
            logger.debug("claude.thinking.adaptive")
        elif request.thinking_budget:
            api_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": request.thinking_budget
            }

        # Server-side compaction (Opus 4.6, beta)
        self._apply_compaction_config(api_params, model_config)

        try:
            # Non-streaming API call
            response = await self.client.messages.create(**api_params)

            # Extract thinking and compaction blocks from non-streaming response
            thinking_text = ""
            compaction_text = ""
            for block in response.content:
                if hasattr(block, 'type') and block.type == "thinking":
                    thinking_text += block.thinking
                elif hasattr(block, 'type') and block.type == "compaction":
                    compaction_text += getattr(block, 'content', '')
            self.last_thinking = thinking_text if thinking_text else None
            self.last_compaction = compaction_text if compaction_text else None

            # Store usage and message
            thinking_tokens = getattr(response.usage, 'thinking_tokens', 0)
            server_tool_use = getattr(response.usage, 'server_tool_use', None)
            web_search_requests = 0
            if server_tool_use:
                web_search_requests = getattr(server_tool_use,
                                              'web_search_requests', 0) or 0
            # Parse cache creation breakdown (1h explicit vs 5m auto-cached)
            cache_creation_total = getattr(response.usage,
                                           'cache_creation_input_tokens', 0)
            cache_breakdown = getattr(response.usage, 'cache_creation', None)
            cache_1h = 0
            cache_5m = 0
            if cache_breakdown is not None:
                cache_1h = getattr(cache_breakdown, 'ephemeral_1h_input_tokens',
                                   0) or 0
                cache_5m = getattr(cache_breakdown, 'ephemeral_5m_input_tokens',
                                   0) or 0
                # Ensure int (guard against mock objects in tests)
                if not isinstance(cache_1h, int):
                    cache_1h = 0
                if not isinstance(cache_5m, int):
                    cache_5m = 0

            self.last_usage = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_read_tokens=getattr(response.usage,
                                          'cache_read_input_tokens', 0),
                cache_creation_tokens=cache_creation_total,
                cache_creation_1h_tokens=cache_1h,
                cache_creation_5m_tokens=cache_5m,
                thinking_tokens=thinking_tokens,
                web_search_requests=web_search_requests)
            self.last_message = response

            duration_ms = (time.time() - start_time) * 1000

            # Phase 1.5 Stage 6: Log cache metrics for monitoring
            cache_read = getattr(response.usage, 'cache_read_input_tokens', 0)
            cache_creation = cache_creation_total

            # Phase 1.5 Stage 4: Log server-side tool usage (web_search, web_fetch)
            log_params = {
                "model_full_id": request.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "thinking_tokens": thinking_tokens,
                "cache_read_tokens": cache_read,
                "cache_creation_tokens": cache_creation,
                "stop_reason": response.stop_reason,
                "content_blocks": len(response.content),
                "duration_ms": round(duration_ms, 2)
            }
            if server_tool_use:
                log_params["server_tool_use"] = server_tool_use

            logger.info("claude.get_message.complete", **log_params)

            return response

        except anthropic.RateLimitError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.info("claude.get_message.rate_limit",
                        error=str(e),
                        duration_ms=round(duration_ms, 2))
            raise RateLimitError("Rate limit exceeded. Please try again later.",
                                 retry_after=None) from e

        except anthropic.APIConnectionError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.info("claude.get_message.connection_error",
                        error=str(e),
                        duration_ms=round(duration_ms, 2))
            raise APIConnectionError("Failed to connect to Claude API.") from e

        except anthropic.APITimeoutError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.info("claude.get_message.timeout",
                        error=str(e),
                        duration_ms=round(duration_ms, 2))
            raise APITimeoutError("Request to Claude API timed out.") from e

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("claude.get_message.unexpected_error",
                         error=str(e),
                         error_type=type(e).__name__,
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)
            raise

    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    async def stream_message(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream response from Claude API.

        Yields text chunks as they arrive without buffering. Tracks token
        usage after stream completes for billing.

        Args:
            request: LLM request with messages and configuration.
                     request.model should be full_id (e.g., "claude:sonnet").

        Yields:
            Text chunks as they arrive from API.

        Raises:
            RateLimitError: Rate limit exceeded (429).
            APIConnectionError: Connection to API failed.
            APITimeoutError: API request timed out.
            InvalidModelError: Model not supported or wrong provider.
        """
        start_time = time.time()

        # Get model configuration from registry
        try:
            model_config = get_model(request.model)
        except KeyError as e:
            raise InvalidModelError(
                f"Model '{request.model}' not found in registry. {e}") from e

        # Validate provider (ClaudeProvider only handles Claude models)
        if model_config.provider != "claude":
            raise InvalidModelError(
                f"ClaudeProvider can only handle 'claude' models, "
                f"got provider '{model_config.provider}' for model "
                f"'{request.model}'")

        logger.info("claude.stream.start",
                    model_full_id=request.model,
                    model_display_name=model_config.display_name,
                    model_api_id=model_config.model_id,
                    provider=model_config.provider,
                    message_count=len(request.messages),
                    system_prompt_length=len(request.system_prompt or ""),
                    max_tokens=request.max_tokens,
                    temperature=request.temperature)

        # Convert messages to Anthropic format, filtering empty messages
        api_messages = _filter_empty_messages(request.messages)

        # Prepare request parameters (use exact model_id for API)
        api_params = {
            "model":
                model_config.model_id,  # e.g., "claude-sonnet-4-6"
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": api_messages,
        }

        # Phase 1.5: Add tools if provided
        if request.tools:
            api_params["tools"] = request.tools
            logger.info("claude.tools.enabled",
                        model_full_id=request.model,
                        tool_count=len(request.tools))

        # Phase 1.4.4: Token Counting API for large requests
        # Estimate tokens first (rough calculation: ~4 chars per token)
        total_text = (request.system_prompt or "") + "".join(
            msg.content for msg in request.messages)
        estimated_tokens = len(total_text) // 4

        # If estimated >150K, use Token Counting API for accurate count
        if estimated_tokens > 150_000:
            logger.info("claude.token_counting.checking",
                        model_full_id=request.model,
                        estimated_tokens=estimated_tokens,
                        threshold=150_000)
            try:
                # Count tokens using official API
                count_response = await self.client.messages.count_tokens(
                    model=model_config.model_id,
                    system=request.system_prompt,
                    messages=api_messages,
                )
                actual_input_tokens = count_response.input_tokens

                logger.info("claude.token_counting.result",
                            model_full_id=request.model,
                            estimated_tokens=estimated_tokens,
                            actual_tokens=actual_input_tokens,
                            context_window=model_config.context_window)

                # Check if within limits (with buffer)
                max_allowed = model_config.context_window - request.max_tokens
                if actual_input_tokens > max_allowed:
                    logger.error("claude.token_counting.overflow",
                                 model_full_id=request.model,
                                 actual_tokens=actual_input_tokens,
                                 max_allowed=max_allowed)
                    # Let it proceed - API will return proper error
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Token counting failed - log but continue (not critical)
                logger.info("claude.token_counting.failed",
                            model_full_id=request.model,
                            error=str(e))

        # Adaptive thinking (Opus 4.6) or manual extended thinking
        if model_config.has_capability("adaptive_thinking"):
            api_params["thinking"] = {"type": "adaptive"}
            logger.debug("claude.thinking.adaptive")
        elif request.thinking_budget:
            api_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": request.thinking_budget
            }
            logger.debug("claude.thinking.enabled",
                         budget_tokens=request.thinking_budget)

        # Effort parameter (GA via output_config)
        if model_config.has_capability("effort"):
            api_params["output_config"] = {"effort": "high"}
            logger.debug("claude.effort.enabled", effort="high")

        # Server-side compaction (Opus 4.6, beta)
        self._apply_compaction_config(api_params, model_config)

        # Phase 1.4.2: System prompt with conditional caching
        # Supports both string (legacy) and list of blocks (multi-block caching)
        if request.system_prompt:
            if isinstance(request.system_prompt, list):
                # Multi-block format - already has cache_control per block
                api_params["system"] = request.system_prompt
                logger.info("claude.prompt_caching.multi_block",
                            block_count=len(request.system_prompt))
            else:
                # Legacy string format - apply single-block caching
                estimated_tokens = len(request.system_prompt) // 4
                use_caching = estimated_tokens >= 1024

                if use_caching:
                    # Use 1-hour cache TTL for better cost efficiency
                    api_params["system"] = [{
                        "type": "text",
                        "text": request.system_prompt,
                        "cache_control": {
                            "type": "ephemeral",
                            "ttl": "1h"
                        }
                    }]
                    logger.info("claude.prompt_caching.enabled",
                                estimated_tokens=estimated_tokens,
                                ttl="1h")
                else:
                    api_params["system"] = request.system_prompt
                    logger.info("claude.prompt_caching.disabled",
                                estimated_tokens=estimated_tokens,
                                required_tokens=1024)

        # Reset state before new request to prevent stale data on errors
        self.last_message = None
        self.last_usage = None
        self.last_thinking = None

        try:
            # Stream response (Phase 1.4.3: handle thinking_delta events)
            total_chunks = 0
            total_thinking_chunks = 0
            response_text = ""
            thinking_text = ""

            async with self.client.messages.stream(**api_params) as stream:
                # Iterate over raw events to handle thinking_delta
                async for event in stream:
                    # Handle text content
                    if (event.type == "content_block_delta" and
                            hasattr(event.delta, "text")):
                        text_chunk = event.delta.text
                        total_chunks += 1
                        response_text += text_chunk

                        logger.debug("claude.stream.text_chunk",
                                     chunk_number=total_chunks,
                                     chunk_length=len(text_chunk))

                        yield text_chunk

                    # Phase 1.4.3: Handle thinking content
                    elif (event.type == "content_block_delta" and
                          hasattr(event.delta, "thinking")):
                        thinking_chunk = event.delta.thinking
                        total_thinking_chunks += 1
                        thinking_text += thinking_chunk

                        logger.debug("claude.stream.thinking_chunk",
                                     chunk_number=total_thinking_chunks,
                                     chunk_length=len(thinking_chunk))

                # Get final message with usage stats
                final_message = await stream.get_final_message()

            # Log thinking summary if present
            if thinking_text:
                logger.info(
                    "claude.stream.thinking_complete",
                    total_thinking_chunks=total_thinking_chunks,
                    thinking_length=len(thinking_text),
                    thinking_preview=thinking_text[:200] +
                    "..." if len(thinking_text) > 200 else thinking_text)

            # Phase 1.5: Save final_message for tool use (contains thinking blocks)
            # When tools call back, we'll need to include thinking block with tool_result
            self.last_message = final_message

            # Phase 1.4.3: Save thinking text for database storage
            self.last_thinking = thinking_text if thinking_text else None

            # Track usage (Phase 1.4.2: cache, Phase 1.4.3: thinking)
            usage = final_message.usage
            server_tool_use = getattr(usage, 'server_tool_use', None)
            web_search_requests = 0
            if server_tool_use:
                web_search_requests = getattr(server_tool_use,
                                              'web_search_requests', 0) or 0
            # Parse cache creation breakdown (1h explicit vs 5m auto-cached)
            cache_creation_total = getattr(usage, 'cache_creation_input_tokens',
                                           0)
            cache_breakdown = getattr(usage, 'cache_creation', None)
            cache_1h = (cache_breakdown.ephemeral_1h_input_tokens
                        if cache_breakdown else 0)
            cache_5m = (cache_breakdown.ephemeral_5m_input_tokens
                        if cache_breakdown else 0)
            self.last_usage = TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, 'cache_read_input_tokens', 0),
                cache_creation_tokens=cache_creation_total,
                cache_creation_1h_tokens=cache_1h,
                cache_creation_5m_tokens=cache_5m,
                thinking_tokens=getattr(usage, 'thinking_tokens', 0),
                web_search_requests=web_search_requests)

            # Phase 1.4.4: Calculate cache hit rate
            total_input = (self.last_usage.input_tokens +
                           self.last_usage.cache_read_tokens +
                           self.last_usage.cache_creation_tokens)
            cache_hit_rate = (self.last_usage.cache_read_tokens /
                              total_input if total_input > 0 else 0.0)

            # Phase 1.5 Stage 4: Extract server-side tool usage (already extracted above)

            usage_log_params = {
                "input_tokens": self.last_usage.input_tokens,
                "output_tokens": self.last_usage.output_tokens,
                "thinking_tokens": self.last_usage.thinking_tokens,
                "cache_read": self.last_usage.cache_read_tokens,
                "cache_creation": self.last_usage.cache_creation_tokens,
                "cache_hit_rate": round(cache_hit_rate * 100, 1)
            }
            if server_tool_use:
                usage_log_params["server_tool_use"] = server_tool_use

            logger.info("claude.stream.usage", **usage_log_params)

            duration_ms = (time.time() - start_time) * 1000

            complete_log_params = {
                "model_full_id": request.model,
                "model_api_id": model_config.model_id,
                "input_tokens": self.last_usage.input_tokens,
                "output_tokens": self.last_usage.output_tokens,
                "total_chunks": total_chunks,
                "response_length": len(response_text),
                "duration_ms": round(duration_ms, 2),
                "stop_reason": final_message.stop_reason
            }
            if server_tool_use:
                complete_log_params["server_tool_use"] = server_tool_use

            logger.info("claude.stream.complete", **complete_log_params)

        except anthropic.RateLimitError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.info("claude.stream.rate_limit",
                        model_full_id=request.model,
                        model_api_id=model_config.model_id,
                        error=str(e),
                        duration_ms=round(duration_ms, 2))

            raise RateLimitError(
                "Rate limit exceeded. Please try again later.",
                retry_after=None  # Parse from headers if available
            ) from e

        except anthropic.APIConnectionError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.info("claude.stream.connection_error",
                        model_full_id=request.model,
                        model_api_id=model_config.model_id,
                        error=str(e),
                        duration_ms=round(duration_ms, 2))

            raise APIConnectionError(
                "Failed to connect to Claude API. Please check your internet "
                "connection.") from e

        except anthropic.APITimeoutError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.info("claude.stream.timeout",
                        model_full_id=request.model,
                        model_api_id=model_config.model_id,
                        error=str(e),
                        duration_ms=round(duration_ms, 2))

            raise APITimeoutError(
                "Request to Claude API timed out. Please try again.") from e

        except anthropic.NotFoundError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error("claude.stream.invalid_model",
                         model_full_id=request.model,
                         model_api_id=model_config.model_id,
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)

            raise InvalidModelError(
                f"Model '{model_config.display_name}' ({model_config.model_id}) "
                f"not found or not accessible.") from e

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error("claude.stream.unexpected_error",
                         model_full_id=request.model,
                         model_api_id=model_config.model_id,
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

    def get_last_message(self) -> Optional[anthropic.types.Message]:
        """Get last API response message (for tool use in Phase 1.5).

        Contains complete message with thinking blocks and tool calls.
        Required for preserving thinking blocks when posting tool_result.

        Returns:
            Last Message object or None if no message sent yet.

        Examples:
            >>> last_msg = provider.get_last_message()
            >>> if last_msg and last_msg.stop_reason == "tool_use":
            >>>     # Extract thinking blocks for tool_result
            >>>     thinking_blocks = [b for b in last_msg.content
            >>>                       if b.type == "thinking"]
        """
        return self.last_message

    def get_stop_reason(self) -> Optional[str]:
        """Get stop_reason from last API response.

        Phase 1.4.4: Stop reason handling for better error messages.

        Returns:
            Stop reason string or None if no message sent yet.

        Examples:
            >>> stop_reason = provider.get_stop_reason()
            >>> if stop_reason == "model_context_window_exceeded":
            >>>     # Handle context overflow
        """
        if self.last_message is None:
            return None
        return self.last_message.stop_reason

    def get_thinking(self) -> Optional[str]:
        """Get thinking text from last API response (for display/logging).

        Phase 1.4.3: Extended Thinking support.

        Returns:
            Thinking text string or None if no thinking was used.

        Examples:
            >>> thinking = provider.get_thinking()
            >>> if thinking:
            >>>     # Display to user or log
        """
        return self.last_thinking

    @staticmethod
    def _apply_compaction_config(api_params: dict, model_config) -> None:
        """Add server-side compaction for models that support it.

        Compaction is a beta feature not yet in the SDK's method signature,
        so it must be passed via extra_body. The beta header is already set
        at the client level in default_headers.

        Args:
            api_params: Mutable dict of API parameters to augment.
            model_config: Model configuration from registry.
        """
        if not model_config.has_capability("compaction"):
            return

        extra_body = api_params.setdefault("extra_body", {})
        extra_body["context_management"] = {
            "edits": [{
                "type": "compact_20260112",
                "trigger": {
                    "type": "input_tokens",
                    "value": 100_000
                }
            }]
        }
        logger.debug("claude.compaction.enabled", trigger_tokens=100_000)

    @staticmethod
    def _sanitize_block_for_api(block_dict: dict) -> dict:
        """Remove fields that API returns but doesn't accept on input.

        Delegates to shared serialize_content_block utility (DRY).

        Args:
            block_dict: Serialized content block.

        Returns:
            Sanitized block dict safe to send to API.
        """
        from utils.serialization import serialize_content_block
        return serialize_content_block(block_dict)

    def get_thinking_blocks_json(self) -> Optional[str]:
        """Get full assistant content blocks as JSON for context preservation.

        When Extended Thinking is enabled, subsequent requests must include
        ALL content blocks from previous turns EXACTLY as received. This method
        serializes the complete content array from the last response.

        IMPORTANT: The content must be preserved without modification to avoid
        'thinking blocks cannot be modified' errors from the API.

        Note: Server-side tool results have 'citations' and 'text' fields
        stripped as API doesn't accept them on input.

        Returns:
            JSON string of ALL content blocks or None if no message available.
            Format: [{"type": "thinking", ...}, {"type": "text", ...}, ...]

        Examples:
            >>> blocks_json = provider.get_thinking_blocks_json()
            >>> if blocks_json:
            >>>     # Save to database for exact context reconstruction
        """
        if self.last_message is None:
            return None

        content_blocks = []
        has_thinking = False

        for block in self.last_message.content:
            # Check if there are any thinking-related blocks
            if hasattr(block, 'type') and block.type in ("thinking",
                                                         "redacted_thinking"):
                has_thinking = True

            # Serialize each block preserving all fields
            if hasattr(block, 'model_dump'):
                # Pydantic model - use model_dump for complete serialization
                block_dict = block.model_dump(exclude_none=True)
                # Sanitize for API (remove citations from server tool results)
                block_dict = self._sanitize_block_for_api(block_dict)
                content_blocks.append(block_dict)
            elif isinstance(block, dict):
                block_dict = self._sanitize_block_for_api(block)
                content_blocks.append(block_dict)
            else:
                # Fallback: try to convert to dict
                try:
                    content_blocks.append(dict(block))
                except (TypeError, ValueError):
                    logger.warning("claude.thinking_blocks.serialize_failed",
                                   block_type=type(block).__name__)

        # Only return if there were thinking blocks (otherwise not needed)
        if not has_thinking:
            return None

        return json.dumps(content_blocks)

    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    async def stream_events(self,
                            request: LLMRequest) -> AsyncIterator[StreamEvent]:
        """Stream response events from Claude API.

        Unified streaming method that yields structured events for thinking,
        text, and tool use. Replaces separate stream_message/get_message.

        Event flow:
        1. thinking_delta events (if thinking enabled)
        2. text_delta events (response text)
        3. tool_use event (if tool called)
        4. block_end after each content block
        5. message_end with stop_reason

        Args:
            request: LLM request with messages and configuration.

        Yields:
            StreamEvent objects for each streaming event.

        Raises:
            RateLimitError: Rate limit exceeded (429).
            APIConnectionError: Connection to API failed.
            APITimeoutError: API request timed out.
            InvalidModelError: Model not supported or wrong provider.
        """
        import json
        start_time = time.time()

        # Get model configuration from registry
        try:
            model_config = get_model(request.model)
        except KeyError as e:
            raise InvalidModelError(
                f"Model '{request.model}' not found in registry. {e}") from e

        if model_config.provider != "claude":
            raise InvalidModelError(
                f"ClaudeProvider can only handle 'claude' models, "
                f"got provider '{model_config.provider}' for model "
                f"'{request.model}'")

        logger.info("claude.stream_events.start",
                    model_full_id=request.model,
                    model_api_id=model_config.model_id,
                    message_count=len(request.messages),
                    has_tools=request.tools is not None,
                    tool_count=len(request.tools) if request.tools else 0)

        # Convert messages to Anthropic format, filtering empty messages
        api_messages = _filter_empty_messages(request.messages)

        # Prepare API parameters
        api_params = {
            "model": model_config.model_id,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": api_messages,
        }

        # Add tools if provided
        if request.tools:
            api_params["tools"] = request.tools

        # System prompt with conditional caching
        # Supports both string (legacy) and list of blocks (multi-block caching)
        if request.system_prompt:
            if isinstance(request.system_prompt, list):
                # Multi-block format - already has cache_control per block
                api_params["system"] = request.system_prompt
            else:
                # Legacy string format - apply single-block caching
                estimated_tokens = len(request.system_prompt) // 4
                use_caching = estimated_tokens >= 1024

                if use_caching:
                    api_params["system"] = [{
                        "type": "text",
                        "text": request.system_prompt,
                        "cache_control": {
                            "type": "ephemeral",
                            "ttl": "1h"
                        }
                    }]
                else:
                    api_params["system"] = request.system_prompt

        # Effort parameter (GA via output_config)
        if model_config.has_capability("effort"):
            api_params["output_config"] = {"effort": "high"}
            logger.debug("claude.effort.enabled", effort="high")

        # Adaptive thinking (Opus 4.6) or manual extended thinking
        if model_config.has_capability("adaptive_thinking"):
            api_params["thinking"] = {"type": "adaptive"}
            logger.debug("claude.thinking.adaptive")
        elif request.thinking_budget:
            api_params["thinking"] = {
                "type": "enabled",
                "budget_tokens": request.thinking_budget
            }

        # Server-side compaction (Opus 4.6, beta)
        self._apply_compaction_config(api_params, model_config)

        # Track current block type and accumulated data
        current_block_type: Optional[str] = None
        current_tool_name = ""
        current_tool_id = ""
        accumulated_json = ""
        thinking_text = ""
        response_text = ""
        compaction_content = ""

        # Reset state before new request to prevent stale data on errors
        # This prevents tool_use_id mismatch if previous request failed
        self.last_message = None
        self.last_usage = None
        self.last_thinking = None
        self.last_compaction = None

        max_retries = 3
        retry_delays = [2, 5, 10]  # seconds
        has_yielded = False  # Track if events were yielded to caller

        for attempt in range(max_retries + 1):
            try:
                async with self.client.messages.stream(**api_params) as stream:
                    async for event in stream:
                        has_yielded = True
                        # Content block start - detect block type
                        if event.type == "content_block_start":
                            block = event.content_block
                            current_block_type = block.type

                            # Regular tool_use (client-side tools)
                            if block.type == "tool_use":
                                current_tool_name = block.name
                                current_tool_id = block.id
                                accumulated_json = ""
                                yield StreamEvent(type="tool_use",
                                                  tool_name=block.name,
                                                  tool_id=block.id)

                            # Server-side tools (web_search, web_fetch)
                            # These are executed by API automatically
                            elif block.type == "server_tool_use":
                                current_tool_name = block.name
                                current_tool_id = block.id
                                accumulated_json = ""
                                yield StreamEvent(type="tool_use",
                                                  tool_name=block.name,
                                                  tool_id=block.id,
                                                  is_server_tool=True)

                            # Server-side compaction (Opus 4.6)
                            elif block.type == "compaction":
                                current_block_type = "compaction"

                        # Content block delta - yield appropriate event
                        elif event.type == "content_block_delta":
                            delta = event.delta

                            if hasattr(delta, "thinking") and delta.thinking:
                                thinking_text += delta.thinking
                                yield StreamEvent(type="thinking_delta",
                                                  content=delta.thinking)

                            elif hasattr(delta, "text") and delta.text:
                                response_text += delta.text
                                yield StreamEvent(type="text_delta",
                                                  content=delta.text)

                            elif (hasattr(delta, "partial_json") and
                                  delta.partial_json):
                                accumulated_json += delta.partial_json
                                yield StreamEvent(type="input_json_delta",
                                                  content=delta.partial_json)

                            elif (hasattr(delta, "type") and
                                  delta.type == "compaction_delta"):
                                compaction_content += getattr(
                                    delta, "content", "")

                        # Content block stop
                        elif event.type == "content_block_stop":
                            if (current_block_type == "tool_use" and
                                    accumulated_json):
                                try:
                                    tool_input = json.loads(accumulated_json)
                                except json.JSONDecodeError:
                                    tool_input = {"raw": accumulated_json}

                                yield StreamEvent(type="block_end",
                                                  tool_name=current_tool_name,
                                                  tool_id=current_tool_id,
                                                  tool_input=tool_input)
                            elif current_block_type == "server_tool_use":
                                yield StreamEvent(type="block_end",
                                                  tool_name=current_tool_name,
                                                  tool_id=current_tool_id,
                                                  is_server_tool=True)
                            else:
                                yield StreamEvent(type="block_end")

                            current_block_type = None

                        # Message delta - contains stop_reason
                        elif event.type == "message_delta":
                            stop_reason = event.delta.stop_reason or ""
                            yield StreamEvent(type="message_end",
                                              stop_reason=stop_reason)

                    # Get final message for usage stats
                    final_message = await stream.get_final_message()

                # Store usage and message
                usage = final_message.usage
                server_tool_use = getattr(usage, 'server_tool_use', None)
                web_search_requests = 0
                if server_tool_use:
                    web_search_requests = getattr(server_tool_use,
                                                  'web_search_requests', 0) or 0
                # Parse cache creation breakdown (1h vs 5m)
                cache_creation_total = getattr(usage,
                                               'cache_creation_input_tokens', 0)
                cache_breakdown = getattr(usage, 'cache_creation', None)
                cache_1h = 0
                cache_5m = 0
                if cache_breakdown is not None:
                    cache_1h = getattr(cache_breakdown,
                                       'ephemeral_1h_input_tokens', 0) or 0
                    cache_5m = getattr(cache_breakdown,
                                       'ephemeral_5m_input_tokens', 0) or 0
                    if not isinstance(cache_1h, int):
                        cache_1h = 0
                    if not isinstance(cache_5m, int):
                        cache_5m = 0

                self.last_usage = TokenUsage(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=getattr(usage, 'cache_read_input_tokens',
                                              0),
                    cache_creation_tokens=cache_creation_total,
                    cache_creation_1h_tokens=cache_1h,
                    cache_creation_5m_tokens=cache_5m,
                    thinking_tokens=getattr(usage, 'thinking_tokens', 0),
                    web_search_requests=web_search_requests)

                self.last_message = final_message
                self.last_thinking = thinking_text if thinking_text else None
                self.last_compaction = (compaction_content
                                        if compaction_content else None)

                if compaction_content:
                    logger.info("claude.compaction.triggered",
                                summary_length=len(compaction_content))

                # Yield stream_complete event with all data
                yield StreamEvent(
                    type="stream_complete",
                    final_message=final_message,
                    usage=self.last_usage,
                    thinking=self.last_thinking,
                )

                duration_ms = (time.time() - start_time) * 1000
                logger.info("claude.stream_events.complete",
                            model_full_id=request.model,
                            input_tokens=self.last_usage.input_tokens,
                            output_tokens=self.last_usage.output_tokens,
                            thinking_tokens=self.last_usage.thinking_tokens,
                            cache_read=self.last_usage.cache_read_tokens,
                            stop_reason=final_message.stop_reason,
                            duration_ms=round(duration_ms, 2))

                # Success — exit retry loop
                return

            except anthropic.APIStatusError as e:
                # Detect retriable server errors:
                # - HTTP 529 / overloaded_error (API overloaded)
                # - HTTP 500 / api_error (internal server error)
                if _is_retriable_server_error(e):
                    error_type = _get_error_type(e) or f"http_{e.status_code}"
                    if has_yielded:
                        # Mid-stream error after yielding events to caller —
                        # cannot retry because partial data was already sent
                        logger.warning(
                            "claude.stream_events.server_error_midstream",
                            attempt=attempt + 1,
                            error_type=error_type,
                            error=str(e))
                        raise OverloadedError(
                            "Claude API server error mid-stream") from e
                    # Pre-stream error — safe to retry
                    if attempt < max_retries:
                        delay = retry_delays[attempt]
                        logger.warning(
                            "claude.stream_events.server_error_retry",
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_seconds=delay,
                            error_type=error_type,
                            status_code=e.status_code)
                        await asyncio.sleep(delay)
                        # Reset state for retry
                        self.last_message = None
                        self.last_usage = None
                        self.last_thinking = None
                        self.last_compaction = None
                        continue
                    # All retries exhausted
                    logger.error(
                        "claude.stream_events.server_error_exhausted",
                        attempts=max_retries + 1,
                        error_type=error_type,
                        error=str(e))
                    raise OverloadedError(
                        "Claude API server error after "
                        f"{max_retries + 1} attempts") from e
                # Non-retriable APIStatusError — re-raise as-is
                raise

            except anthropic.RateLimitError as e:
                logger.info("claude.stream_events.rate_limit", error=str(e))
                raise RateLimitError(
                    "Rate limit exceeded. Please try again later.",
                    retry_after=None) from e

            except anthropic.APIConnectionError as e:
                logger.info("claude.stream_events.connection_error",
                            error=str(e))
                raise APIConnectionError(
                    "Failed to connect to Claude API.") from e

            except anthropic.APITimeoutError as e:
                logger.info("claude.stream_events.timeout", error=str(e))
                raise APITimeoutError("Request to Claude API timed out.") from e

            except Exception as e:
                logger.error("claude.stream_events.unexpected_error",
                             error=str(e),
                             error_type=type(e).__name__,
                             exc_info=True)
                raise
