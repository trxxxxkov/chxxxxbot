"""Tests for ClaudeProvider thinking blocks serialization.

REGRESSION TESTS: Verify that thinking blocks are serialized correctly
to prevent 'thinking blocks cannot be modified' API errors.

Bug: We were saving only thinking blocks, then reconstructing content by
adding a text block. This modified the original response structure.

Fix: Save the ENTIRE content array and restore it as-is.
"""

import json
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


class MockThinkingBlock:
    """Mock thinking block as returned by Claude API."""

    def __init__(
        self,
        thinking: str,
        signature: str | None = None,
    ):
        self.type = "thinking"
        self.thinking = thinking
        self.signature = signature

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        """Serialize like Pydantic model."""
        result = {
            "type": self.type,
            "thinking": self.thinking,
        }
        if self.signature is not None or not exclude_none:
            result["signature"] = self.signature
        return result


class MockRedactedThinkingBlock:
    """Mock redacted_thinking block as returned by Claude API."""

    def __init__(self, data: str):
        self.type = "redacted_thinking"
        self.data = data

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        """Serialize like Pydantic model."""
        return {
            "type": self.type,
            "data": self.data,
        }


class MockTextBlock:
    """Mock text block as returned by Claude API."""

    def __init__(self, text: str):
        self.type = "text"
        self.text = text

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        """Serialize like Pydantic model."""
        return {
            "type": self.type,
            "text": self.text,
        }


class MockToolUseBlock:
    """Mock tool_use block as returned by Claude API."""

    def __init__(self, tool_id: str, name: str, input_data: dict):
        self.type = "tool_use"
        self.id = tool_id
        self.name = name
        self.input = input_data

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        """Serialize like Pydantic model."""
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }


class MockMessage:
    """Mock Claude API Message response."""

    def __init__(self, content: list):
        self.content = content


class TestGetThinkingBlocksJson:
    """Tests for ClaudeProvider.get_thinking_blocks_json method."""

    @pytest.fixture
    def provider(self):
        """Create ClaudeProvider with mocked client."""
        with patch("core.claude.client.anthropic.AsyncAnthropic"):
            from core.claude.client import ClaudeProvider
            return ClaudeProvider(api_key="test-key")

    def test_returns_none_without_message(self, provider):
        """No message = None result."""
        provider.last_message = None
        assert provider.get_thinking_blocks_json() is None

    def test_returns_none_without_thinking(self, provider):
        """Message without thinking blocks returns None."""
        provider.last_message = MockMessage([
            MockTextBlock("Just a text response"),
        ])
        assert provider.get_thinking_blocks_json() is None

    def test_serializes_thinking_with_text(self, provider):
        """REGRESSION: Full content including text block must be serialized."""
        thinking = MockThinkingBlock(
            thinking="Step by step analysis...",
            signature="sig_abc123",
        )
        text = MockTextBlock("The final answer is 42.")

        provider.last_message = MockMessage([thinking, text])
        result = provider.get_thinking_blocks_json()

        assert result is not None
        parsed = json.loads(result)

        # CRITICAL: Must contain BOTH blocks
        assert len(parsed) == 2
        assert parsed[0]["type"] == "thinking"
        assert parsed[0]["thinking"] == "Step by step analysis..."
        assert parsed[0]["signature"] == "sig_abc123"
        assert parsed[1]["type"] == "text"
        assert parsed[1]["text"] == "The final answer is 42."

    def test_regression_redacted_thinking_preserved(self, provider):
        """REGRESSION: redacted_thinking blocks must be preserved."""
        redacted = MockRedactedThinkingBlock(data="encrypted_content")
        thinking = MockThinkingBlock(
            thinking="Visible thinking...",
            signature="sig_xyz",
        )
        text = MockTextBlock("Response text")

        provider.last_message = MockMessage([redacted, thinking, text])
        result = provider.get_thinking_blocks_json()

        parsed = json.loads(result)

        # CRITICAL: redacted_thinking must be included
        assert len(parsed) == 3
        assert parsed[0]["type"] == "redacted_thinking"
        assert parsed[0]["data"] == "encrypted_content"
        assert parsed[1]["type"] == "thinking"
        assert parsed[2]["type"] == "text"

    def test_regression_tool_use_preserved(self, provider):
        """REGRESSION: tool_use blocks in response must be preserved."""
        thinking = MockThinkingBlock(
            thinking="Need to search...",
            signature="sig_tool",
        )
        text = MockTextBlock("Let me search.")
        tool = MockToolUseBlock(
            tool_id="tool_123",
            name="web_search",
            input_data={"query": "weather"},
        )

        provider.last_message = MockMessage([thinking, text, tool])
        result = provider.get_thinking_blocks_json()

        parsed = json.loads(result)

        # CRITICAL: tool_use must be included
        assert len(parsed) == 3
        assert parsed[2]["type"] == "tool_use"
        assert parsed[2]["id"] == "tool_123"
        assert parsed[2]["name"] == "web_search"
        assert parsed[2]["input"] == {"query": "weather"}

    def test_multiple_thinking_blocks(self, provider):
        """Multiple thinking blocks in interleaved response."""
        thinking1 = MockThinkingBlock(
            thinking="First thought...",
            signature="sig_1",
        )
        text1 = MockTextBlock("First part of response.")
        thinking2 = MockThinkingBlock(
            thinking="Second thought...",
            signature="sig_2",
        )
        text2 = MockTextBlock("Second part of response.")

        provider.last_message = MockMessage(
            [thinking1, text1, thinking2, text2])
        result = provider.get_thinking_blocks_json()

        parsed = json.loads(result)

        # All blocks preserved in order
        assert len(parsed) == 4
        assert parsed[0]["type"] == "thinking"
        assert parsed[1]["type"] == "text"
        assert parsed[2]["type"] == "thinking"
        assert parsed[3]["type"] == "text"

    def test_content_round_trip_exact(self, provider):
        """REGRESSION: Serialization must be reversible exactly.

        Content saved to DB must be identical when loaded back.
        This prevents 'thinking blocks cannot be modified' errors.
        """
        original_content = [
            MockThinkingBlock("Analysis...", "sig_round"),
            MockTextBlock("Final answer."),
        ]

        provider.last_message = MockMessage(original_content)
        json_result = provider.get_thinking_blocks_json()

        # Simulate loading from DB
        loaded = json.loads(json_result)

        # Compare with what model_dump would produce
        expected = [
            block.model_dump(exclude_none=True) for block in original_content
        ]

        assert loaded == expected
