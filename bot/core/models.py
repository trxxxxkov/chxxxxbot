"""Pydantic models for LLM requests and responses.

This module defines data models used for communication with LLM providers.
All models use Pydantic v2 for validation and serialization.

NO __init__.py - use direct import: from core.models import LLMRequest
"""

from typing import List, Optional

from pydantic import BaseModel
from pydantic import Field


class Message(BaseModel):
    """Single message in conversation.

    Represents a message in the conversation history that is sent to
    the LLM provider.

    Attributes:
        role: Message role ("user" or "assistant").
        content: Message text content.
    """

    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message text content")


class LLMRequest(BaseModel):
    """Request to LLM provider.

    Contains all information needed to make a request to an LLM provider,
    including conversation history, system prompt, and model parameters.

    Attributes:
        messages: Conversation history (chronological order, oldest first).
        system_prompt: System prompt (instructions for LLM behavior).
        model: Model identifier (e.g., "claude-sonnet-4-5-20250514").
        max_tokens: Maximum tokens to generate in response.
        temperature: Sampling temperature (0.0-2.0, higher = more random).
    """

    messages: List[Message] = Field(
        ..., description="Conversation history (oldest first)")
    system_prompt: Optional[str] = Field(
        None, description="System prompt for LLM behavior")
    model: str = Field(..., description="Model identifier")
    max_tokens: int = Field(default=4096,
                            ge=1,
                            le=8192,
                            description="Max tokens to generate")
    temperature: float = Field(default=1.0,
                               ge=0.0,
                               le=2.0,
                               description="Sampling temperature")


class TokenUsage(BaseModel):
    """Token usage statistics.

    Tracks token usage for billing and analytics. Includes cache tokens
    for providers that support prompt caching (Phase 1.4).

    Attributes:
        input_tokens: Input tokens (user messages + system prompt).
        output_tokens: Output tokens (LLM response).
        cache_read_tokens: Tokens read from cache (Phase 1.4).
        cache_creation_tokens: Tokens written to cache (Phase 1.4).
    """

    input_tokens: int = Field(..., ge=0, description="Input tokens")
    output_tokens: int = Field(..., ge=0, description="Output tokens")
    cache_read_tokens: int = Field(default=0,
                                   ge=0,
                                   description="Cache read tokens (Phase 1.4)")
    cache_creation_tokens: int = Field(
        default=0, ge=0, description="Cache creation tokens (Phase 1.4)")


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
