"""Display block manager for streaming responses.

Manages the lifecycle of display blocks (thinking and text) during streaming.
Provides clean API for adding content, formatting, and clearing.
"""

from telegram.streaming.types import BlockType
from telegram.streaming.types import DisplayBlock


class DisplayManager:
    """Manages display blocks for streaming responses.

    Handles:
    - Appending content with automatic merging of same-type blocks
    - Filtering blocks by type
    - Clearing state for new iterations or file commits
    - Tracking current block type for proper interleaving

    Example:
        display = DisplayManager()
        display.append(BlockType.THINKING, "Let me analyze...")
        display.append(BlockType.THINKING, " the data.")  # Merges
        display.append(BlockType.TEXT, "Here's what I found:")

        text_only = display.get_text_blocks()
        display.clear()
    """

    def __init__(self) -> None:
        """Initialize empty display manager."""
        self._blocks: list[DisplayBlock] = []
        self._current_type: BlockType | None = None

    @property
    def blocks(self) -> list[DisplayBlock]:
        """Return all display blocks as a read-only copy."""
        return list(self._blocks)

    @property
    def current_type(self) -> BlockType | None:
        """Get the current block type being accumulated."""
        return self._current_type

    def append(self, block_type: BlockType, content: str) -> None:
        """Append content, merging with last block if same type.

        This maintains proper interleaving: consecutive content of the
        same type is merged into one block, while type changes create
        new blocks.

        Args:
            block_type: Type of content (THINKING or TEXT).
            content: Content string to append.
        """
        if not content:
            return

        if self._blocks and self._blocks[-1].block_type == block_type:
            # Merge with existing block of same type
            self._blocks[-1].content += content
        else:
            # Create new block
            self._blocks.append(
                DisplayBlock(block_type=block_type, content=content))

        self._current_type = block_type

    def get_text_blocks(self) -> list[DisplayBlock]:
        """Get only text blocks (for final message without thinking).

        Returns:
            List of DisplayBlock with block_type == TEXT.
        """
        return [b for b in self._blocks if b.block_type == BlockType.TEXT]

    def get_thinking_blocks(self) -> list[DisplayBlock]:
        """Get only thinking blocks.

        Returns:
            List of DisplayBlock with block_type == THINKING.
        """
        return [b for b in self._blocks if b.block_type == BlockType.THINKING]

    def clear(self) -> None:
        """Clear all blocks and reset state.

        Called when committing content before files or starting new iteration.
        """
        self._blocks.clear()
        self._current_type = None

    def has_content(self) -> bool:
        """Check if there's any content.

        Returns:
            True if there's at least one non-empty block.
        """
        return any(b.content.strip() for b in self._blocks)

    def has_text_content(self) -> bool:
        """Check if there's any text content (not just thinking).

        Returns:
            True if there's at least one non-empty text block.
        """
        return any(b.content.strip()
                   for b in self._blocks
                   if b.block_type == BlockType.TEXT)

    def get_all_text(self) -> str:
        """Join all text blocks into single string.

        Returns:
            All text content joined with double newlines.
        """
        return "\n\n".join(
            b.content.strip()
            for b in self._blocks
            if b.block_type == BlockType.TEXT and b.content.strip())

    def total_thinking_length(self) -> int:
        """Get total length of thinking content.

        Returns:
            Sum of all thinking block lengths.
        """
        return sum(
            len(b.content)
            for b in self._blocks
            if b.block_type == BlockType.THINKING)

    def total_text_length(self) -> int:
        """Get total length of text content.

        Returns:
            Sum of all text block lengths.
        """
        return sum(
            len(b.content)
            for b in self._blocks
            if b.block_type == BlockType.TEXT)
