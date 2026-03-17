"""Google Gemini API client implementation.

Implements the LLMProvider interface for Google Gemini using the
official google-genai SDK. Handles streaming, tool use, thinking,
thought signatures, and Google Search grounding.

Thought signatures: Gemini 3 returns encrypted reasoning state with
function calls. These must be preserved and sent back in subsequent
turns, otherwise function calling returns 400 errors. We capture
signatures from response parts and include them in serialized
assistant content for the tool loop.

NO __init__.py - use direct import:
    from core.google.client import GeminiProvider
"""

import asyncio
import base64
import hashlib
import time
import uuid
from typing import AsyncIterator, Optional

from config import get_model
from core.base import LLMProvider
from core.clients import get_google_client
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

# Sentinel for async stream iteration (cannot use None — could be a valid value)
_STREAM_DONE = object()


def _convert_tools_for_google(tools: list[dict]) -> list[dict]:
    """Convert tool definitions from Anthropic format to Google format.

    Anthropic: {"name": "foo", "description": "...", "input_schema": {...}}
    Google: FunctionDeclaration(name="foo", description="...", parameters={...})

    Args:
        tools: List of tool definitions in Anthropic format.

    Returns:
        List of function declaration dicts for Google API.
    """
    declarations = []
    for tool in tools:
        # Skip server-side tools (they have "type" field instead of "input_schema")
        if "type" in tool and tool["type"] != "function":
            continue
        if "input_schema" not in tool:
            continue

        decl = {
            "name": tool["name"],
            "description": tool.get("description", ""),
        }

        # Convert input_schema to parameters
        schema = tool["input_schema"]
        if schema:
            decl["parameters"] = _clean_schema_for_google(schema)

        declarations.append(decl)

    return declarations


def _clean_schema_for_google(schema: dict) -> dict:
    """Clean JSON Schema for Google API compatibility.

    Google's API is stricter about JSON Schema:
    - No 'additionalProperties' at top level
    - 'type' values must be uppercase

    Args:
        schema: JSON Schema dict.

    Returns:
        Cleaned schema dict.
    """
    cleaned = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue  # Google doesn't support this
        if key == "type" and isinstance(value, str):
            cleaned[key] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            cleaned[key] = {
                k: _clean_schema_for_google(v) if isinstance(v, dict) else v
                for k, v in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            cleaned[key] = _clean_schema_for_google(value)
        else:
            cleaned[key] = value
    return cleaned


def _convert_messages_for_google(
    messages: list[dict],
) -> list[dict]:
    """Convert messages from LLM format to Google Content format.

    LLM format: [{"role": "user"/"assistant", "content": str|list}]
    Google format: [{"role": "user"/"model", "parts": [...]}]

    Args:
        messages: Messages in LLM format.

    Returns:
        Messages in Google Content format.
    """
    contents = []

    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        content = msg["content"]

        parts = []
        if isinstance(content, str):
            if content.strip():
                parts.append({"text": content})
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    if block.strip():
                        parts.append({"text": block})
                elif isinstance(block, dict):
                    block_type = block.get("type", "")

                    if block_type == "text":
                        text = block.get("text", "")
                        if text.strip():
                            text_part = {"text": text}
                            if block.get("thought_signature"):
                                text_part["thought_signature"] = block[
                                    "thought_signature"]
                            parts.append(text_part)

                    elif block_type == "tool_use":
                        fc_part = {
                            "function_call": {
                                "name": block.get("name", ""),
                                "args": block.get("input", {}),
                            }
                        }
                        # Preserve thought signature (Gemini 3)
                        if block.get("thought_signature"):
                            fc_part["thought_signature"] = block[
                                "thought_signature"]
                        parts.append(fc_part)

                    elif block_type == "tool_result":
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            # Extract text from content blocks
                            text_parts = []
                            for item in result_content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    text_parts.append(item.get("text", ""))
                                elif isinstance(item, str):
                                    text_parts.append(item)
                            result_content = "\n".join(text_parts)

                        parts.append({
                            "function_response": {
                                "name": block.get("name", block.get("tool_use_id", "tool")),
                                "response": {"result": str(result_content)},
                            }
                        })

                    elif block_type == "function_response":
                        parts.append({
                            "function_response": {
                                "name": block.get("name", ""),
                                "response": block.get("response", {}),
                            }
                        })

                    elif block_type == "inline_data":
                        parts.append({
                            "inline_data": {
                                "mime_type": block.get("mime_type",
                                                       "image/jpeg"),
                                "data": block.get("data", ""),
                            }
                        })

                    elif "function_call" in block:
                        # Google-native format from
                        # get_serialized_assistant_content()
                        fc_part = {
                            "function_call": block["function_call"],
                        }
                        if block.get("thought_signature"):
                            fc_part["thought_signature"] = block[
                                "thought_signature"]
                        parts.append(fc_part)

                    elif "function_response" in block:
                        # Google-native format from tool results
                        parts.append({
                            "function_response": block["function_response"],
                        })

                    elif not block_type and "text" in block:
                        # Google-native format: {"text": "..."}
                        text = block["text"]
                        if text.strip():
                            text_part = {"text": text}
                            if block.get("thought_signature"):
                                text_part["thought_signature"] = block[
                                    "thought_signature"]
                            parts.append(text_part)

        if parts:
            contents.append({"role": role, "parts": parts})

    return contents


class GeminiProvider(LLMProvider):
    """Google Gemini provider implementing LLMProvider interface."""

    def __init__(self):
        """Initialize GeminiProvider."""
        self._last_usage: Optional[TokenUsage] = None
        self._last_stop_reason: Optional[str] = None
        self._last_thinking: Optional[str] = None
        self._last_assistant_content: Optional[list[dict]] = None
        self.last_compaction: Optional[str] = None
        # Explicit cache: maps content_hash -> (cache_name, expire_timestamp)
        self._content_caches: dict[str, tuple[str, float]] = {}
        # Negative cache: hashes that failed creation -> retry_after timestamp
        self._cache_creation_failures: dict[str, float] = {}
        # Cache creation tokens from last _get_or_create_cache() call
        self._last_cache_creation_tokens: int = 0
        logger.info("gemini_provider.initialized")

    async def _get_or_create_cache(
        self,
        model_id: str,
        system_instruction: Optional[str],
        google_tools: list,
        google_contents: Optional[list[dict]] = None,
    ) -> tuple[Optional[str], Optional[list[dict]]]:
        """Get or create explicit cache for system + tools + conversation.

        Caches system instruction, tools, and conversation history (all but
        last user message). Google requires minimum 1024 tokens for caching.
        Returns cache name and the remaining contents to send.

        Args:
            model_id: Google model ID.
            system_instruction: System prompt string.
            google_tools: List of genai_types.Tool objects.
            google_contents: Converted conversation messages.

        Returns:
            Tuple of (cache_name or None, remaining_contents or None).
            If cache is used, remaining_contents has only the uncached tail.
        """
        if not system_instruction and not google_tools:
            return None, None

        from google.genai import types as genai_types  # pylint: disable=import-outside-toplevel

        # Determine cacheable conversation prefix (all but last user message)
        # Include history in cache for tool loops and long conversations
        cache_contents = None
        remaining_contents = google_contents
        if google_contents and len(google_contents) > 1:
            cache_contents = google_contents[:-1]
            remaining_contents = google_contents[-1:]

        # Build content hash
        hash_parts = [model_id]
        if system_instruction:
            hash_parts.append(system_instruction)
        if google_tools:
            hash_parts.append(repr(google_tools))
        if cache_contents:
            hash_parts.append(repr(cache_contents))
        content_hash = hashlib.sha256(
            "||".join(hash_parts).encode()).hexdigest()[:16]

        now = time.time()

        # Skip if recently failed (negative cache, 5 min cooldown)
        if content_hash in self._cache_creation_failures:
            if now < self._cache_creation_failures[content_hash]:
                return None, None
            del self._cache_creation_failures[content_hash]

        # Check existing cache (with expiration)
        if content_hash in self._content_caches:
            cache_name, expire_ts = self._content_caches[content_hash]
            if now < expire_ts - 60:  # 60s safety margin
                self._last_cache_creation_tokens = 0
                logger.debug(
                    "gemini.cache.hit",
                    cache_name=cache_name,
                    content_hash=content_hash,
                    ttl_remaining=round(expire_ts - now),
                )
                return cache_name, remaining_contents
            # Expired — remove and recreate
            del self._content_caches[content_hash]

        # Clean up expired entries
        expired = [
            k for k, (_, ts) in self._content_caches.items()
            if now >= ts - 60
        ]
        for k in expired:
            del self._content_caches[k]

        # Create new cache
        try:
            client = get_google_client()

            cache_config_kwargs: dict = {"ttl": "3600s"}
            if system_instruction:
                cache_config_kwargs["system_instruction"] = system_instruction
            if google_tools:
                cache_config_kwargs["tools"] = google_tools
            if cache_contents:
                cache_config_kwargs["contents"] = cache_contents

            cache = await asyncio.to_thread(
                client.caches.create,
                model=model_id,
                config=genai_types.CreateCachedContentConfig(
                    **cache_config_kwargs),
            )

            expire_ts = now + 3600  # 1 hour from now
            self._content_caches[content_hash] = (cache.name, expire_ts)

            # Log cache token count if available
            cache_tokens = 0
            if hasattr(cache, 'usage_metadata') and cache.usage_metadata:
                cache_tokens = getattr(
                    cache.usage_metadata, 'total_token_count', 0) or 0

            self._last_cache_creation_tokens = cache_tokens
            logger.info(
                "gemini.cache.created",
                model=model_id,
                cache_name=cache.name,
                cache_tokens=cache_tokens,
                content_hash=content_hash,
                has_contents=cache_contents is not None,
            )
            return cache.name, remaining_contents

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_msg = str(e)[:200]
            # Negative cache: don't retry for 5 minutes
            self._cache_creation_failures[content_hash] = now + 300
            self._last_cache_creation_tokens = 0
            logger.info(
                "gemini.cache.create_failed",
                model=model_id,
                error=error_msg,
                content_hash=content_hash,
            )
            return None, None

    @staticmethod
    async def _resolve_file_bytes(
        conversation: list[dict],
    ) -> list[dict]:
        """Pre-resolve file references to inline bytes for Gemini.

        Replaces Anthropic-style image/document blocks with inline base64
        data that Gemini can consume. Must be called before
        _convert_messages_for_google().

        Args:
            conversation: Messages in LLM intermediate format.

        Returns:
            Messages with file blocks replaced by inline_data blocks.
        """
        from cache.file_cache import get_cached_file  # pylint: disable=import-outside-toplevel

        resolved = []
        files_resolved = 0
        total_inline_bytes = 0
        for msg in conversation:
            content = msg["content"]
            if not isinstance(content, list):
                resolved.append(msg)
                continue

            new_blocks = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type in ("image", "document"):
                        telegram_file_id = block.get("telegram_file_id")
                        mime_type = block.get("mime_type", "image/jpeg")
                        if telegram_file_id:
                            file_bytes = await get_cached_file(
                                telegram_file_id)
                            if file_bytes:
                                encoded = base64.b64encode(
                                    file_bytes).decode()
                                new_blocks.append({
                                    "type": "inline_data",
                                    "mime_type": mime_type,
                                    "data": encoded,
                                })
                                files_resolved += 1
                                total_inline_bytes += len(encoded)
                                continue
                        # No bytes available - skip silently
                        logger.debug(
                            "gemini.resolve_file_bytes.skip",
                            block_type=block_type,
                            has_telegram_id=bool(telegram_file_id),
                        )
                        continue
                    new_blocks.append(block)
                else:
                    new_blocks.append(block)

            resolved.append({
                "role": msg["role"],
                "content": new_blocks if new_blocks else msg["content"],
            })

        if files_resolved > 0:
            logger.info(
                "gemini.resolve_file_bytes.complete",
                files_resolved=files_resolved,
                total_inline_kb=round(total_inline_bytes / 1024, 1),
                estimated_tokens=total_inline_bytes // 4,
            )

        return resolved

    async def stream_message(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream response text from Gemini.

        Args:
            request: LLM request.

        Yields:
            Text chunks.
        """
        async for event in self.stream_events(request):
            if event.type == "text_delta":
                yield event.content

    async def stream_events(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamEvent]:
        """Stream structured events from Gemini.

        Converts LLMRequest to Google format, streams, yields StreamEvents.

        Args:
            request: LLM request.

        Yields:
            StreamEvent objects.
        """
        from google.genai import types as genai_types  # pylint: disable=import-outside-toplevel

        # Validate model
        try:
            model_config = get_model(request.model)
        except KeyError as e:
            raise InvalidModelError(str(e)) from e

        if model_config.provider != "google":
            raise InvalidModelError(
                f"Model {request.model} is not a Google model")

        # Reset state
        self._last_usage = None
        self._last_stop_reason = None
        self._last_thinking = None
        self._last_assistant_content = None
        self._last_model_id = model_config.model_id

        # Convert messages to Google format
        conversation = []
        for msg in request.messages:
            content = msg.content
            conversation.append({
                "role": msg.role,
                "content": content,
            })

        # Resolve file references to inline bytes before conversion
        conversation = await self._resolve_file_bytes(conversation)
        google_contents = _convert_messages_for_google(conversation)

        # Convert tool definitions
        google_tools = []
        if request.tools:
            declarations = _convert_tools_for_google(request.tools)
            if declarations:
                google_tools.append(
                    genai_types.Tool(
                        function_declarations=[
                            genai_types.FunctionDeclaration(**d)
                            for d in declarations
                        ]
                    )
                )

        # Add Google Search grounding if model supports it.
        # Google API doesn't allow combining built-in tools (google_search)
        # with custom function declarations in the same request.
        if model_config.has_capability("grounding") and not google_tools:
            google_tools.append(
                genai_types.Tool(google_search=genai_types.GoogleSearch()))

        # Build system instruction
        system_instruction = None
        if request.system_prompt:
            if isinstance(request.system_prompt, str):
                system_instruction = request.system_prompt
            elif isinstance(request.system_prompt, list):
                # Multi-block format: concatenate text blocks
                parts = []
                for block in request.system_prompt:
                    if isinstance(block, dict):
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                system_instruction = "\n\n".join(p for p in parts if p)

        # Try explicit cache for system prompt + tools + conversation
        cache_name = None
        if model_config.has_capability("caching"):
            cache_name, cached_remaining = await self._get_or_create_cache(
                model_id=model_config.model_id,
                system_instruction=system_instruction,
                google_tools=google_tools,
                google_contents=google_contents,
            )
            if cache_name and cached_remaining is not None:
                google_contents = cached_remaining

        # Build config (omit system_instruction/tools when using cache)
        if cache_name:
            generate_config = genai_types.GenerateContentConfig(
                cached_content=cache_name,
                max_output_tokens=request.max_tokens,
                temperature=request.temperature,
            )
        else:
            generate_config = genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=request.max_tokens,
                temperature=request.temperature,
                tools=google_tools if google_tools else None,
            )

        # Enable thinking for capable models
        if model_config.has_capability("thinking"):
            generate_config.thinking_config = genai_types.ThinkingConfig(
                thinking_level="HIGH",
                include_thoughts=True,
            )

        logger.info(
            "gemini.stream_events.start",
            model=model_config.model_id,
            messages=len(google_contents),
            tools=len(google_tools),
            has_system=system_instruction is not None,
            using_cache=cache_name is not None,
        )

        start_time = time.perf_counter()

        # Stream response
        try:
            client = get_google_client()

            response_text = ""
            thinking_text = ""
            assistant_parts = []
            input_tokens = 0
            output_tokens = 0
            thinking_tokens = 0
            cache_read_tokens = 0
            grounding_requests = 0

            def _sync_stream():
                return client.models.generate_content_stream(
                    model=model_config.model_id,
                    contents=google_contents,
                    config=generate_config,
                )

            # Run sync streaming in thread
            stream_iter = await asyncio.to_thread(_sync_stream)

            # Iterate asynchronously: each next() runs in the thread
            # pool so the event loop stays free between chunks (unlike
            # a bare ``for chunk in stream_iter`` which would block).
            loop = asyncio.get_running_loop()
            while True:
                chunk = await loop.run_in_executor(
                    None, next, stream_iter, _STREAM_DONE)
                if chunk is _STREAM_DONE:
                    break
                if not chunk.candidates:
                    # Check for usage metadata on final chunk
                    if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                        meta = chunk.usage_metadata
                        input_tokens = getattr(meta, 'prompt_token_count', 0) or 0
                        output_tokens = getattr(meta, 'candidates_token_count', 0) or 0
                        thinking_tokens = getattr(meta, 'thoughts_token_count', 0) or 0
                        cache_read_tokens = getattr(meta, 'cached_content_token_count', 0) or 0
                    continue

                candidate = chunk.candidates[0]

                # Extract usage metadata
                if hasattr(chunk, 'usage_metadata') and chunk.usage_metadata:
                    meta = chunk.usage_metadata
                    input_tokens = getattr(meta, 'prompt_token_count', 0) or 0
                    output_tokens = getattr(meta, 'candidates_token_count', 0) or 0
                    thinking_tokens = getattr(meta, 'thoughts_token_count', 0) or 0
                    cache_read_tokens = getattr(meta, 'cached_content_token_count', 0) or 0

                # Check finish reason
                finish_reason = getattr(candidate, 'finish_reason', None)

                if not candidate.content or not candidate.content.parts:
                    continue

                for part in candidate.content.parts:
                    # Handle thinking
                    if getattr(part, 'thought', False) and part.text:
                        thinking_text += part.text
                        yield StreamEvent(
                            type="thinking_delta",
                            content=part.text,
                        )

                    # Handle function calls
                    elif part.function_call:
                        fc = part.function_call
                        tool_id = f"google_{uuid.uuid4().hex[:12]}"
                        tool_input = {}
                        if fc.args:
                            # fc.args may be a proto MapComposite or dict
                            if hasattr(fc.args, 'items'):
                                tool_input = dict(fc.args.items())
                            elif isinstance(fc.args, dict):
                                tool_input = fc.args

                        fc_part = {
                            "function_call": {
                                "name": fc.name,
                                "args": tool_input,
                            }
                        }

                        # Preserve thought signature for Gemini 3
                        # Required for function calling multi-turn
                        thought_sig = getattr(
                            part, 'thought_signature', None)
                        if thought_sig:
                            fc_part["thought_signature"] = thought_sig

                        assistant_parts.append(fc_part)

                        yield StreamEvent(
                            type="tool_use",
                            tool_name=fc.name,
                            tool_id=tool_id,
                        )
                        yield StreamEvent(
                            type="block_end",
                            tool_name=fc.name,
                            tool_id=tool_id,
                            tool_input=tool_input,
                        )

                    # Handle text
                    elif part.text and not getattr(part, 'thought', False):
                        response_text += part.text
                        text_part = {"text": part.text}
                        # Preserve thought signature on text parts too
                        thought_sig = getattr(
                            part, 'thought_signature', None)
                        if thought_sig:
                            text_part["thought_signature"] = thought_sig
                        assistant_parts.append(text_part)
                        yield StreamEvent(
                            type="text_delta",
                            content=part.text,
                        )

                # Track grounding metadata (outside parts loop)
                # grounding_metadata is on the candidate, not on individual parts
                g_meta = getattr(candidate, 'grounding_metadata', None)
                if g_meta and getattr(g_meta, 'grounding_chunks', None):
                    grounding_requests += 1

            # Determine stop reason
            stop_reason = "end_turn"
            if assistant_parts and any(
                "function_call" in p for p in assistant_parts
            ):
                stop_reason = "tool_use"

            self._last_stop_reason = stop_reason
            self._last_thinking = thinking_text if thinking_text else None
            self._last_assistant_content = assistant_parts if assistant_parts else None

            # Build usage (grounding_requests maps to web_search_requests
            # for unified cost tracking in the handler)
            self._last_usage = TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thinking_tokens=thinking_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=self._last_cache_creation_tokens,
                web_search_requests=grounding_requests,
            )

            elapsed = time.perf_counter() - start_time
            logger.info(
                "gemini.stream_events.complete",
                model=model_config.model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thinking_tokens=thinking_tokens,
                cache_read_tokens=cache_read_tokens,
                grounding_requests=grounding_requests,
                stop_reason=stop_reason,
                using_cache=cache_name is not None,
                elapsed_ms=round(elapsed * 1000, 2),
            )

            # Yield completion events
            yield StreamEvent(
                type="message_end",
                stop_reason=stop_reason,
            )
            yield StreamEvent(
                type="stream_complete",
                usage=self._last_usage,
                thinking=self._last_thinking,
            )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(
                "gemini.stream_events.error",
                model=model_config.model_id,
                error_type=error_type,
                error=error_msg[:500],
                using_cache=cache_name is not None,
            )

            # Invalidate cache on cache-related errors (expired, not found)
            if cache_name and ("cachedContent" in error_msg
                               or "NOT_FOUND" in error_msg
                               or "cached" in error_msg.lower()):
                self._content_caches = {
                    k: v for k, v in self._content_caches.items()
                    if v[0] != cache_name
                }
                logger.warning(
                    "gemini.cache.invalidated",
                    cache_name=cache_name,
                    error=error_msg[:200],
                )

            # Map Google errors to our exception types
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                raise RateLimitError(
                    f"Google API rate limit: {error_msg}") from e
            if "503" in error_msg or "UNAVAILABLE" in error_msg:
                raise OverloadedError(
                    f"Google API overloaded: {error_msg}") from e
            if "timeout" in error_msg.lower():
                raise APITimeoutError(
                    f"Google API timeout: {error_msg}") from e
            if "connection" in error_msg.lower():
                raise APIConnectionError(
                    f"Google API connection error: {error_msg}") from e
            if "PERMISSION_DENIED" in error_msg or "403" in error_msg:
                raise APIConnectionError(
                    f"Google API permission denied: {error_msg}") from e
            if "UNAUTHENTICATED" in error_msg or "401" in error_msg:
                raise APIConnectionError(
                    f"Google API authentication error: {error_msg}") from e
            if "INVALID_ARGUMENT" in error_msg or "400" in error_msg:
                raise InvalidModelError(
                    f"Google API invalid request: {error_msg}") from e

            raise

    async def get_token_count(self, text: str) -> int:
        """Count tokens using Google's count_tokens API.

        Uses the model from the last request for accurate tokenization.
        Falls back to estimation (~4 chars per token) if API call fails.

        Args:
            text: Text to count tokens for.

        Returns:
            Token count.
        """
        try:
            client = get_google_client()
            count_model = getattr(self, '_last_model_id', None) or \
                "gemini-3.1-flash-lite-preview"

            def _sync_count():
                response = client.models.count_tokens(
                    model=count_model,
                    contents=text,
                )
                return response.total_tokens

            return await asyncio.wait_for(
                asyncio.to_thread(_sync_count),
                timeout=5.0,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # Fallback to estimation
            return len(text) // 4

    async def get_usage(self) -> TokenUsage:
        """Return usage from last request.

        Returns:
            TokenUsage from last request.

        Raises:
            ValueError: If no request has been made.
        """
        if self._last_usage is None:
            raise ValueError("No usage available - no API call made yet")
        return self._last_usage

    def get_stop_reason(self) -> str | None:
        """Get stop reason from last API call."""
        return self._last_stop_reason

    def get_thinking(self) -> str | None:
        """Get thinking text from last API call."""
        return self._last_thinking

    def get_serialized_assistant_content(self) -> list[dict] | None:
        """Get last assistant content for tool loop continuation."""
        return self._last_assistant_content
