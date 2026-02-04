"""Tests for utils.serialization module."""

from pydantic import BaseModel
import pytest
from utils.serialization import serialize_content_block


class MockContentBlock(BaseModel):
    """Mock Pydantic content block for testing."""
    type: str
    text: str = ""
    parsed_output: dict | None = None


class TestSerializeContentBlock:
    """Tests for serialize_content_block function."""

    def test_removes_parsed_output_from_pydantic(self):
        """Should remove parsed_output field from Pydantic model."""
        block = MockContentBlock(type="text",
                                 text="Hello",
                                 parsed_output={"key": "value"})

        result = serialize_content_block(block)

        assert "parsed_output" not in result
        assert result["type"] == "text"
        assert result["text"] == "Hello"

    def test_removes_parsed_output_from_dict(self):
        """Should remove parsed_output field from dict."""
        block = {
            "type": "text",
            "text": "Hello",
            "parsed_output": {
                "key": "value"
            }
        }

        result = serialize_content_block(block)

        assert "parsed_output" not in result
        assert result["type"] == "text"
        assert result["text"] == "Hello"

    def test_removes_citations_from_server_tool_result(self):
        """Should remove citations from server_tool_result blocks."""
        block = {
            "type": "server_tool_result",
            "tool_use_id": "123",
            "citations": [{
                "url": "http://example.com"
            }],
            "text": "Some text"
        }

        result = serialize_content_block(block)

        assert "citations" not in result
        assert "text" not in result
        assert result["type"] == "server_tool_result"
        assert result["tool_use_id"] == "123"

    def test_removes_fields_from_nested_content(self):
        """Should remove API-only fields from nested content."""
        block = {
            "type":
                "tool_result",
            "tool_use_id":
                "123",
            "content": [{
                "type": "text",
                "text": "Result",
                "parsed_output": {
                    "x": 1
                }
            }, {
                "type": "text",
                "text": "More",
                "citations": ["cite1"]
            }]
        }

        result = serialize_content_block(block)

        assert len(result["content"]) == 2
        assert "parsed_output" not in result["content"][0]
        assert "citations" not in result["content"][1]
        assert result["content"][0]["text"] == "Result"
        assert result["content"][1]["text"] == "More"

    def test_preserves_required_fields(self):
        """Should preserve all non-API-only fields."""
        block = {
            "type": "tool_use",
            "id": "tool_123",
            "name": "execute_python",
            "input": {
                "code": "print('hello')"
            }
        }

        result = serialize_content_block(block)

        assert result == block

    def test_handles_non_dict_input(self):
        """Should return non-dict/non-model input unchanged."""
        result = serialize_content_block("string_input")
        assert result == "string_input"

        result = serialize_content_block(123)
        assert result == 123

    def test_does_not_modify_original_dict(self):
        """Should not modify the original dict."""
        block = {
            "type": "text",
            "text": "Hello",
            "parsed_output": {
                "key": "value"
            }
        }
        original_block = block.copy()

        serialize_content_block(block)

        assert block == original_block

    def test_web_search_tool_result(self):
        """Should handle web_search_tool_result blocks."""
        block = {
            "type": "web_search_tool_result",
            "tool_use_id": "search_123",
            "citations": [{
                "title": "Result 1"
            }],
            "text": "Search results..."
        }

        result = serialize_content_block(block)

        assert "citations" not in result
        assert "text" not in result
        assert result["type"] == "web_search_tool_result"

    def test_web_fetch_tool_result(self):
        """Should handle web_fetch_tool_result blocks."""
        block = {
            "type": "web_fetch_tool_result",
            "tool_use_id": "fetch_123",
            "citations": [],
            "text": "Fetched content..."
        }

        result = serialize_content_block(block)

        assert "citations" not in result
        assert "text" not in result
        assert result["type"] == "web_fetch_tool_result"
