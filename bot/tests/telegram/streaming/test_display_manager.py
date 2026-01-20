"""Tests for DisplayManager class."""

import pytest
from telegram.streaming.display_manager import DisplayManager
from telegram.streaming.types import BlockType


class TestDisplayManagerAppend:
    """Tests for append() method."""

    def test_append_creates_new_block(self):
        """append() should create new block."""
        dm = DisplayManager()
        dm.append(BlockType.THINKING, "hello")

        assert len(dm.blocks) == 1
        assert dm.blocks[0].block_type == BlockType.THINKING
        assert dm.blocks[0].content == "hello"

    def test_append_merges_same_type(self):
        """append() should merge consecutive blocks of same type."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "hello ")
        dm.append(BlockType.TEXT, "world")

        assert len(dm.blocks) == 1
        assert dm.blocks[0].content == "hello world"

    def test_append_creates_new_for_different_type(self):
        """append() should create new block for different type."""
        dm = DisplayManager()
        dm.append(BlockType.THINKING, "thinking")
        dm.append(BlockType.TEXT, "text")

        assert len(dm.blocks) == 2
        assert dm.blocks[0].block_type == BlockType.THINKING
        assert dm.blocks[1].block_type == BlockType.TEXT

    def test_append_ignores_empty_content(self):
        """append() should ignore empty content."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "")
        dm.append(BlockType.TEXT, None)  # type: ignore

        assert len(dm.blocks) == 0

    def test_current_type_tracking(self):
        """current_type should track last appended type."""
        dm = DisplayManager()
        assert dm.current_type is None

        dm.append(BlockType.THINKING, "test")
        assert dm.current_type == BlockType.THINKING

        dm.append(BlockType.TEXT, "test")
        assert dm.current_type == BlockType.TEXT


class TestDisplayManagerFilters:
    """Tests for filter methods."""

    def test_get_text_blocks(self):
        """get_text_blocks() should return only text blocks."""
        dm = DisplayManager()
        dm.append(BlockType.THINKING, "think")
        dm.append(BlockType.TEXT, "text1")
        dm.append(BlockType.THINKING, "think2")
        dm.append(BlockType.TEXT, "text2")

        text_blocks = dm.get_text_blocks()
        assert len(text_blocks) == 2
        assert all(b.block_type == BlockType.TEXT for b in text_blocks)

    def test_get_thinking_blocks(self):
        """get_thinking_blocks() should return only thinking blocks."""
        dm = DisplayManager()
        dm.append(BlockType.THINKING, "think1")
        dm.append(BlockType.TEXT, "text")
        dm.append(BlockType.THINKING, "think2")

        thinking_blocks = dm.get_thinking_blocks()
        assert len(thinking_blocks) == 2
        assert all(b.block_type == BlockType.THINKING for b in thinking_blocks)


class TestDisplayManagerClear:
    """Tests for clear() method."""

    def test_clear_removes_all_blocks(self):
        """clear() should remove all blocks."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "test")
        dm.append(BlockType.THINKING, "think")

        dm.clear()

        assert len(dm.blocks) == 0
        assert dm.current_type is None


class TestDisplayManagerContent:
    """Tests for content checking methods."""

    def test_has_content_empty(self):
        """has_content() should return False for empty."""
        dm = DisplayManager()
        assert dm.has_content() is False

    def test_has_content_with_blocks(self):
        """has_content() should return True with blocks."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "test")
        assert dm.has_content() is True

    def test_has_content_whitespace_only(self):
        """has_content() should return False for whitespace only."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "   ")
        assert dm.has_content() is False

    def test_has_text_content_no_text(self):
        """has_text_content() should return False without text blocks."""
        dm = DisplayManager()
        dm.append(BlockType.THINKING, "think")
        assert dm.has_text_content() is False

    def test_has_text_content_with_text(self):
        """has_text_content() should return True with text blocks."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "hello")
        assert dm.has_text_content() is True


class TestDisplayManagerLength:
    """Tests for length calculation methods."""

    def test_total_thinking_length(self):
        """total_thinking_length() should sum thinking content."""
        dm = DisplayManager()
        dm.append(BlockType.THINKING, "abc")  # 3
        dm.append(BlockType.TEXT, "xyz")
        dm.append(BlockType.THINKING, "de")  # 2

        assert dm.total_thinking_length() == 5

    def test_total_text_length(self):
        """total_text_length() should sum text content."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "hello")  # 5
        dm.append(BlockType.THINKING, "think")
        dm.append(BlockType.TEXT, "world")  # 5

        assert dm.total_text_length() == 10

    def test_get_all_text(self):
        """get_all_text() should join all text blocks."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "hello")
        dm.append(BlockType.THINKING, "think")
        dm.append(BlockType.TEXT, "world")

        result = dm.get_all_text()
        assert result == "hello\n\nworld"


class TestDisplayManagerBlocks:
    """Tests for blocks property."""

    def test_blocks_returns_copy(self):
        """blocks should return a copy, not the internal list."""
        dm = DisplayManager()
        dm.append(BlockType.TEXT, "test")

        blocks = dm.blocks
        blocks.clear()

        # Internal list should not be affected
        assert len(dm.blocks) == 1
