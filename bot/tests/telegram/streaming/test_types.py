"""Tests for streaming types module."""

import pytest
from telegram.streaming.types import BlockType
from telegram.streaming.types import DisplayBlock
from telegram.streaming.types import ToolCall


class TestBlockType:
    """Tests for BlockType enum."""

    def test_thinking_value(self):
        """BlockType.THINKING should have value 'thinking'."""
        assert BlockType.THINKING == "thinking"
        assert BlockType.THINKING.value == "thinking"

    def test_text_value(self):
        """BlockType.TEXT should have value 'text'."""
        assert BlockType.TEXT == "text"
        assert BlockType.TEXT.value == "text"

    def test_from_string(self):
        """BlockType should be constructible from string."""
        assert BlockType("thinking") == BlockType.THINKING
        assert BlockType("text") == BlockType.TEXT

    def test_string_comparison(self):
        """BlockType should compare equal to strings."""
        assert BlockType.THINKING == "thinking"
        assert BlockType.TEXT == "text"


class TestDisplayBlock:
    """Tests for DisplayBlock dataclass."""

    def test_create_thinking_block(self):
        """Should create thinking block."""
        block = DisplayBlock(block_type=BlockType.THINKING, content="test")
        assert block.block_type == BlockType.THINKING
        assert block.content == "test"

    def test_create_text_block(self):
        """Should create text block."""
        block = DisplayBlock(block_type=BlockType.TEXT, content="hello")
        assert block.block_type == BlockType.TEXT
        assert block.content == "hello"

    def test_create_from_string_type(self):
        """Should convert string to BlockType."""
        block = DisplayBlock(block_type="thinking", content="test")
        assert block.block_type == BlockType.THINKING

    def test_empty_content(self):
        """Should allow empty content."""
        block = DisplayBlock(block_type=BlockType.TEXT, content="")
        assert block.content == ""


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_create_tool_call(self):
        """Should create tool call."""
        tool = ToolCall(tool_id="tool_123",
                        name="generate_image",
                        input={"prompt": "a cat"})
        assert tool.tool_id == "tool_123"
        assert tool.name == "generate_image"
        assert tool.input == {"prompt": "a cat"}

    def test_default_empty_input(self):
        """Input should default to empty dict."""
        tool = ToolCall(tool_id="id", name="test")
        assert tool.input == {}
