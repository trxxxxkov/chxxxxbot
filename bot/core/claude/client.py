"""Claude API client implementation.

This module implements the LLMProvider interface for Claude using the
official Anthropic SDK. Handles streaming, token counting, error handling,
and comprehensive logging.

NO __init__.py - use direct import: from core.claude.client import ClaudeProvider
"""

import time
from typing import AsyncIterator, Optional

import anthropic
from config import get_model
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
        # Phase 1.4 & 1.5: Add beta headers for advanced features
        # - interleaved-thinking: Extended Thinking feature
        # - context-management: Context editing (thinking block clearing)
        # - effort: Effort parameter for Opus 4.5
        # Phase 1.5: Files API and Web Tools
        # - files-api: Files API for multimodal content
        # - web-search: Server-side web search tool
        # - web-fetch: Server-side web page/PDF fetching tool
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            default_headers={
                "anthropic-beta": ("interleaved-thinking-2025-05-14,"
                                   "context-management-2025-06-27,"
                                   "effort-2025-11-24,"
                                   "files-api-2025-04-14,"
                                   "web-search-2025-03-05,"
                                   "web-fetch-2025-09-10")
            })
        self.last_usage: Optional[TokenUsage] = None
        self.last_message: Optional[
            anthropic.types.Message] = None  # Phase 1.5: for tool use
        self.last_thinking: Optional[
            str] = None  # Phase 1.4.3: Extended Thinking

        logger.info("claude_provider.initialized",
                    beta_features=[
                        "interleaved-thinking", "context-management", "effort",
                        "files-api", "web-search", "web-fetch"
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

        # Convert messages to Anthropic format
        api_messages = [{
            "role": msg.role,
            "content": msg.content
        } for msg in request.messages]

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
        if request.system_prompt:
            estimated_tokens = len(request.system_prompt) // 4
            use_caching = estimated_tokens >= 1024

            if use_caching:
                api_params["system"] = [{
                    "type": "text",
                    "text": request.system_prompt,
                    "cache_control": {
                        "type": "ephemeral"
                    }
                }]
            else:
                api_params["system"] = request.system_prompt

        # Effort parameter for Opus 4.5
        if model_config.has_capability("effort"):
            api_params["effort"] = "high"

        # Phase 1.4.3: Extended Thinking (for tool loop)
        # NOW ENABLED: thinking blocks are saved to DB and properly handled
        api_params["thinking"] = {"type": "enabled", "budget_tokens": 10000}

        try:
            # Non-streaming API call
            response = await self.client.messages.create(**api_params)

            # Phase 1.4.3: Extract thinking blocks from non-streaming response
            thinking_text = ""
            for block in response.content:
                if hasattr(block, 'type') and block.type == "thinking":
                    thinking_text += block.thinking
            self.last_thinking = thinking_text if thinking_text else None

            # Store usage and message
            thinking_tokens = getattr(response.usage, 'thinking_tokens', 0)
            server_tool_use = getattr(response.usage, 'server_tool_use', None)
            web_search_requests = 0
            if server_tool_use:
                web_search_requests = getattr(server_tool_use,
                                              'web_search_requests', 0) or 0
            self.last_usage = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_read_tokens=getattr(response.usage,
                                          'cache_read_input_tokens', 0),
                cache_creation_tokens=getattr(response.usage,
                                              'cache_creation_input_tokens', 0),
                thinking_tokens=thinking_tokens,
                web_search_requests=web_search_requests)
            self.last_message = response

            duration_ms = (time.time() - start_time) * 1000

            # Phase 1.5 Stage 6: Log cache metrics for monitoring
            cache_read = getattr(response.usage, 'cache_read_input_tokens', 0)
            cache_creation = getattr(response.usage,
                                     'cache_creation_input_tokens', 0)

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
            logger.error("claude.get_message.rate_limit",
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)
            raise RateLimitError("Rate limit exceeded. Please try again later.",
                                 retry_after=None) from e

        except anthropic.APIConnectionError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("claude.get_message.connection_error",
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)
            raise APIConnectionError("Failed to connect to Claude API.") from e

        except anthropic.APITimeoutError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("claude.get_message.timeout",
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)
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

        # Convert messages to Anthropic format
        api_messages = [{
            "role": msg.role,
            "content": msg.content
        } for msg in request.messages]

        # Prepare request parameters (use exact model_id for API)
        api_params = {
            "model":
                model_config.model_id,  # e.g., "claude-sonnet-4-5-20250929"
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
                logger.warning("claude.token_counting.failed",
                               model_full_id=request.model,
                               error=str(e))

        # Phase 1.4.3: Extended Thinking
        # NOW ENABLED: thinking blocks are saved to DB and properly handled
        api_params["thinking"] = {"type": "enabled", "budget_tokens": 10000}

        # Note: context_management not supported in current SDK version
        # Will be added in Phase 1.5 when SDK supports it
        # api_params["context_management"] = [{
        #     "type": "clear_thinking_20251015",
        #     "keep": "all"
        # }]

        # Phase 1.4.4: Effort parameter (Opus 4.5 only)
        # Always set to "high" for maximum quality when supported
        if model_config.has_capability("effort"):
            api_params["effort"] = "high"
            logger.info("claude.effort.enabled",
                        model_full_id=request.model,
                        effort="high")

        # Phase 1.4.2: System prompt with conditional caching
        # Minimum 1024 tokens required for caching (Sonnet 4.5 limitation)
        # Automatically enables when system prompt grows (e.g., with tool descriptions)
        if request.system_prompt:
            # Estimate tokens (~4 chars per token)
            estimated_tokens = len(request.system_prompt) // 4
            use_caching = estimated_tokens >= 1024

            if use_caching:
                # Phase 1.5 Stage 6: Use 1-hour cache TTL for better cost efficiency
                # 1-hour cache is 2x more expensive to write but lasts 12x longer
                # For shared bot cache (all users), this saves ~41% vs 5-minute TTL
                api_params["system"] = [{
                    "type": "text",
                    "text": request.system_prompt,
                    "cache_control": {
                        "type": "ephemeral",
                        "ttl": "1h"  # 1-hour cache instead of default 5 minutes
                    }
                }]
                logger.info("claude.prompt_caching.enabled",
                            estimated_tokens=estimated_tokens,
                            ttl="1h")
            else:
                # Plain string format (no caching for small prompts)
                api_params["system"] = request.system_prompt
                logger.info("claude.prompt_caching.disabled",
                            estimated_tokens=estimated_tokens,
                            required_tokens=1024)

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
            self.last_usage = TokenUsage(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=getattr(usage, 'cache_read_input_tokens', 0),
                cache_creation_tokens=getattr(usage,
                                              'cache_creation_input_tokens', 0),
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

            logger.error("claude.stream.rate_limit",
                         model_full_id=request.model,
                         model_api_id=model_config.model_id,
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
                         model_full_id=request.model,
                         model_api_id=model_config.model_id,
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)

            raise APIConnectionError(
                "Failed to connect to Claude API. Please check your internet "
                "connection.") from e

        except anthropic.APITimeoutError as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error("claude.stream.timeout",
                         model_full_id=request.model,
                         model_api_id=model_config.model_id,
                         error=str(e),
                         duration_ms=round(duration_ms, 2),
                         exc_info=True)

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
        """Get thinking text from last API response.

        Phase 1.4.3: Extended Thinking support.

        Returns:
            Thinking text string or None if no thinking was used.

        Examples:
            >>> thinking = provider.get_thinking()
            >>> if thinking:
            >>>     # Save to database
        """
        return self.last_thinking
