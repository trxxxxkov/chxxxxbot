"""Content block serialization utilities for Claude API.

This module provides functions to serialize Pydantic content blocks
for sending back to Claude API, removing fields that API returns
but doesn't accept on input.

NO __init__.py - use direct import:
    from utils.serialization import serialize_content_block
"""

from typing import Any

# Fields that API returns but doesn't accept on input
# These are removed during serialization
API_OUTPUT_ONLY_FIELDS = frozenset({
    "parsed_output",  # Structured Outputs parsing result
    "citations",  # Server tool citations
})

# Block types that have additional output-only fields
# Includes dynamic filtering result blocks from web_search/web_fetch v2
SERVER_TOOL_BLOCK_TYPES = frozenset({
    "server_tool_result",
    "web_search_tool_result",
    "web_fetch_tool_result",
    "bash_code_execution_tool_result",
    "text_editor_code_execution_tool_result",
})


def serialize_content_block(block: Any) -> dict:
    """Serialize a content block for Claude API.

    Removes fields that are returned by API but not accepted on input:
    - parsed_output: Added by SDK for Structured Outputs
    - citations: Present in server_tool_result blocks
    - text: Present in some server tool results

    Args:
        block: Content block (Pydantic model or dict).

    Returns:
        Serialized dict safe to send back to API.
    """
    # Convert to dict
    if hasattr(block, 'model_dump'):
        block_dict = block.model_dump()
    elif isinstance(block, dict):
        block_dict = block.copy()
    else:
        return block

    # Remove API output-only fields
    for field in API_OUTPUT_ONLY_FIELDS:
        block_dict.pop(field, None)

    # Handle server tool-specific fields
    block_type = block_dict.get("type", "")
    if block_type in SERVER_TOOL_BLOCK_TYPES:
        block_dict.pop("text", None)

    # Recursively clean nested content
    if "content" in block_dict and isinstance(block_dict["content"], list):
        block_dict["content"] = [
            _clean_nested_item(item) for item in block_dict["content"]
        ]

    return block_dict


def _clean_nested_item(item: Any) -> Any:
    """Clean a nested content item.

    Args:
        item: Item from nested content list.

    Returns:
        Cleaned item (dict with API-only fields removed, or original).
    """
    if isinstance(item, dict):
        item_copy = item.copy()
        for field in API_OUTPUT_ONLY_FIELDS:
            item_copy.pop(field, None)
        # Only remove 'text' from server tool result items
        item_type = item_copy.get("type", "")
        if item_type in SERVER_TOOL_BLOCK_TYPES:
            item_copy.pop("text", None)
        return item_copy
    return item
