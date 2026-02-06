"""Pydantic models for LLM requests and responses.

This module defines data models used for communication with LLM providers.
All models use Pydantic v2 for validation and serialization.

NO __init__.py - use direct import: from core.models import LLMRequest
"""

from dataclasses import dataclass
from dataclasses import field
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel
from pydantic import Field


@dataclass
class StreamEvent:  # pylint: disable=too-many-instance-attributes
    """Streaming event from LLM provider.

    Represents a single event during streaming response. Used for unified
    streaming of thinking, text, and tool use.

    Attributes:
        type: Event type indicating what happened.
        content: Text content (for thinking_delta, text_delta).
        tool_name: Tool name (for tool_use events).
        tool_id: Tool use ID (for tool_use events).
        tool_input: Accumulated tool input JSON (for tool_use events).
        stop_reason: Why message ended (for message_end events).
        final_message: Complete API response message (for stream_complete).
        usage: Token usage statistics (for stream_complete).
        thinking: Thinking text (for stream_complete).
        is_server_tool: True for server-side tools (web_search, web_fetch).

    Event Types:
        - thinking_delta: Chunk of thinking/reasoning text
        - text_delta: Chunk of response text
        - tool_use: Tool call detected (contains tool_name, tool_id)
        - input_json_delta: Partial JSON for tool input
        - block_end: End of content block (thinking/text/tool)
        - message_end: End of message (contains stop_reason)
        - stream_complete: Stream finished (contains final_message, usage)
    """

    type: Literal["thinking_delta", "text_delta", "tool_use",
                  "input_json_delta", "block_end", "message_end",
                  "stream_complete"]
    content: str = ""
    tool_name: str = ""
    tool_id: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    stop_reason: str = ""  # "end_turn" | "tool_use" | "max_tokens"
    # For stream_complete event (avoids race condition with shared state)
    final_message: Any = None  # anthropic.types.Message
    usage: Any = None  # TokenUsage
    thinking: Optional[str] = None
    # Server-side tools (web_search, web_fetch) are executed by API automatically
    is_server_tool: bool = False


class Message(BaseModel):
    """Single message in conversation.

    Represents a message in the conversation history that is sent to
    the LLM provider.

    Attributes:
        role: Message role ("user" or "assistant").
        content: Message content (string for text, list for tool use).
    """

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: Union[str, List[Any]] = Field(
        ..., description="Message content (string or list of content blocks)")


class LLMRequest(BaseModel):
    """Request to LLM provider.

    Contains all information needed to make a request to an LLM provider,
    including conversation history, system prompt, and model parameters.

    Attributes:
        messages: Conversation history (chronological order, oldest first).
        system_prompt: System prompt - either string (legacy) or list of blocks
            (multi-block caching). List format allows separate cache_control
            per block for optimal caching.
        model: Model identifier (e.g., "claude-sonnet-4-5-20250514").
        max_tokens: Maximum tokens to generate in response.
        temperature: Sampling temperature (0.0-2.0, higher = more random).
        tools: Optional list of tool definitions (Phase 1.5).
    """

    messages: List[Message] = Field(
        ..., description="Conversation history (oldest first)")
    system_prompt: Optional[Union[str, List[Dict[str, Any]]]] = Field(
        None,
        description="System prompt - string or list of blocks for multi-caching"
    )
    model: str = Field(..., description="Model identifier")
    max_tokens: int = Field(default=64000,
                            ge=1,
                            le=128000,
                            description="Max tokens to generate")
    temperature: float = Field(default=1.0,
                               ge=0.0,
                               le=2.0,
                               description="Sampling temperature")
    tools: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Tool definitions for tool use (Phase 1.5)")
    thinking_budget: Optional[int] = Field(
        default=None,
        description=
        "Extended Thinking budget in tokens. None = thinking disabled.")


class TokenUsage(BaseModel):
    """Token usage statistics.

    Tracks token usage for billing and analytics. Includes cache tokens
    for providers that support prompt caching (Phase 1.4.2) and thinking
    tokens for extended thinking (Phase 1.4.3).

    Attributes:
        input_tokens: Input tokens (user messages + system prompt).
        output_tokens: Output tokens (LLM response text only).
        cache_read_tokens: Tokens read from cache (Phase 1.4.2).
        cache_creation_tokens: Tokens written to cache (Phase 1.4.2).
        thinking_tokens: Tokens used for extended thinking (Phase 1.4.3).
        web_search_requests: Number of web search requests (Phase 1.5).
    """

    input_tokens: int = Field(..., ge=0, description="Input tokens")
    output_tokens: int = Field(..., ge=0, description="Output tokens")
    cache_read_tokens: int = Field(
        default=0, ge=0, description="Cache read tokens (Phase 1.4.2)")
    cache_creation_tokens: int = Field(
        default=0, ge=0, description="Cache creation tokens (Phase 1.4.2)")
    thinking_tokens: int = Field(
        default=0, ge=0, description="Extended thinking tokens (Phase 1.4.3)")
    web_search_requests: int = Field(
        default=0, ge=0, description="Web search requests (Phase 1.5)")


class LLMResponse(BaseModel):
    """Complete LLM response metadata.

    Contains full response after streaming completes, including final
    text content, token usage, and stop reason.

    Attributes:
        content: Complete response text.
        usage: Token usage statistics.
        model: Model that generated response.
        stop_reason: Why generation stopped.
    """

    content: str = Field(..., description="Complete response text")
    usage: TokenUsage = Field(..., description="Token usage statistics")
    model: str = Field(..., description="Model identifier")
    stop_reason: str = Field(
        ...,
        description="Stop reason: 'end_turn', 'max_tokens', 'stop_sequence'")
