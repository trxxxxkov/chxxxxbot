"""Tests for format_tool_results function (bug fix verification).

Tests the fix for: "content cannot be empty if is_error is true"
Empty error strings should be treated as success, not error.

Also tests image preview handling for render_latex and similar tools.
"""

import base64

from core.tools.helpers import format_tool_results
import pytest


class TestFormatToolResultsEmptyError:
    """Test format_tool_results with empty error strings."""

    def test_empty_error_string_treated_as_success(self):
        """Empty error string should not set is_error=true."""
        tool_uses = [{"id": "tool_123", "name": "execute_python"}]
        results = [{"error": "", "stdout": "Hello", "success": "true"}]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 1
        assert formatted[0]["type"] == "tool_result"
        assert formatted[0]["tool_use_id"] == "tool_123"
        # Empty error should NOT set is_error
        assert "is_error" not in formatted[0] or formatted[0][
            "is_error"] is False
        # Content should be JSON serialized result
        assert "stdout" in formatted[0]["content"]

    def test_none_error_treated_as_success(self):
        """None error should not set is_error=true."""
        tool_uses = [{"id": "tool_456", "name": "analyze_image"}]
        results = [{"error": None, "result": "success"}]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 1
        assert "is_error" not in formatted[0] or formatted[0][
            "is_error"] is False

    def test_non_empty_error_sets_is_error(self):
        """Non-empty error string should set is_error=true."""
        tool_uses = [{"id": "tool_789", "name": "execute_python"}]
        results = [{"error": "NameError: undefined variable"}]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 1
        assert formatted[0]["is_error"] is True
        assert formatted[0]["content"] == "NameError: undefined variable"

    def test_multiple_results_mixed_errors(self):
        """Test multiple results with mixed error states."""
        tool_uses = [
            {
                "id": "tool_1",
                "name": "tool_a"
            },
            {
                "id": "tool_2",
                "name": "tool_b"
            },
            {
                "id": "tool_3",
                "name": "tool_c"
            },
        ]
        results = [
            {
                "error": "",
                "success": "true"
            },  # Empty error - success
            {
                "error": "Real error"
            },  # Real error
            {
                "error": None,
                "result": "ok"
            },  # None error - success
        ]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 3
        # First: success (empty error)
        assert "is_error" not in formatted[0] or formatted[0][
            "is_error"] is False
        # Second: error
        assert formatted[1]["is_error"] is True
        # Third: success (None error)
        assert "is_error" not in formatted[2] or formatted[2][
            "is_error"] is False


class TestFormatToolResultsWithImagePreview:
    """Test format_tool_results with _image_preview key."""

    def test_image_preview_creates_multi_part_content(self):
        """Test that _image_preview creates image + text content blocks."""
        # Create a small test image (1x1 red pixel PNG)
        test_image_base64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42"
            "mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")

        tool_uses = [{"id": "tool_render", "name": "render_latex"}]
        results = [{
            "success": "true",
            "output_files": [{
                "temp_id": "exec_abc123",
                "filename": "formula.png",
                "preview": "Image 100x50"
            }],
            "_image_preview": {
                "data": test_image_base64,
                "media_type": "image/png",
            },
            "message": "Rendered formula"
        }]

        formatted = format_tool_results(tool_uses, results)

        assert len(formatted) == 1
        assert formatted[0]["type"] == "tool_result"
        assert formatted[0]["tool_use_id"] == "tool_render"

        # Content should be a list with image + text blocks
        content = formatted[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 2

        # First block: image
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["media_type"] == "image/png"
        assert content[0]["source"]["data"] == test_image_base64

        # Second block: text (JSON of result without _image_preview)
        assert content[1]["type"] == "text"
        # _image_preview should be removed from the text result
        assert "_image_preview" not in content[1]["text"]
        assert "output_files" in content[1]["text"]

    def test_image_preview_removed_from_text_result(self):
        """Test that _image_preview is removed from the serialized text."""
        test_image_base64 = "dGVzdA=="  # "test" in base64

        tool_uses = [{"id": "tool_1", "name": "render_latex"}]
        results = [{
            "success": "true",
            "_image_preview": {
                "data": test_image_base64,
                "media_type": "image/png",
            },
        }]

        formatted = format_tool_results(tool_uses, results)

        content = formatted[0]["content"]
        # The text block should not contain _image_preview
        import json
        text_content = json.loads(content[1]["text"])
        assert "_image_preview" not in text_content

    def test_result_without_image_preview_unchanged(self):
        """Test that results without _image_preview work as before."""
        tool_uses = [{"id": "tool_1", "name": "web_search"}]
        results = [{"success": "true", "results": ["result1", "result2"]}]

        formatted = format_tool_results(tool_uses, results)

        # Content should be a JSON string, not a list
        assert isinstance(formatted[0]["content"], str)
        assert "results" in formatted[0]["content"]

    def test_multiple_image_previews(self):
        """Test that _image_previews (plural) creates multiple image blocks."""
        test_image_1 = "aW1hZ2UxCg=="  # "image1" in base64
        test_image_2 = "aW1hZ2UyCg=="  # "image2" in base64

        tool_uses = [{"id": "tool_exec", "name": "execute_python"}]
        results = [{
            "success":
                "true",
            "stdout":
                "Generated 2 charts",
            "output_files": [
                {
                    "temp_id": "exec_abc",
                    "filename": "chart1.png"
                },
                {
                    "temp_id": "exec_def",
                    "filename": "chart2.png"
                },
            ],
            "_image_previews": [
                {
                    "data": test_image_1,
                    "media_type": "image/png",
                    "filename": "chart1.png"
                },
                {
                    "data": test_image_2,
                    "media_type": "image/png",
                    "filename": "chart2.png"
                },
            ],
        }]

        formatted = format_tool_results(tool_uses, results)

        content = formatted[0]["content"]
        assert isinstance(content, list)
        # 2 images + 1 text block = 3 blocks
        assert len(content) == 3

        # First two blocks are images
        assert content[0]["type"] == "image"
        assert content[0]["source"]["data"] == test_image_1
        assert content[1]["type"] == "image"
        assert content[1]["source"]["data"] == test_image_2

        # Third block is text
        assert content[2]["type"] == "text"
        # _image_previews should be removed
        assert "_image_previews" not in content[2]["text"]
