"""Tests for format_tool_results function (bug fix verification).

Tests the fix for: "content cannot be empty if is_error is true"
Empty error strings should be treated as success, not error.
"""

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
