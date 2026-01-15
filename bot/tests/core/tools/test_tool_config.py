"""Tests for ToolConfig base class (Phase 1.5+).

Tests the ToolConfig dataclass functionality:
- Initialization and validation
- Server-side tool handling
- Name mismatch detection
- System message formatting
"""

import pytest
from unittest.mock import Mock

from core.tools.base import ToolConfig


class TestToolConfigInit:
    """Tests for ToolConfig initialization."""

    def test_basic_initialization_with_executor(self):
        """Test that ToolConfig initializes correctly with executor."""
        mock_executor = Mock()
        config = ToolConfig(
            name="test_tool",
            definition={"name": "test_tool", "description": "Test"},
            executor=mock_executor,
            emoji="🔧",
        )

        assert config.name == "test_tool"
        assert config.executor == mock_executor
        assert config.emoji == "🔧"
        assert config.is_server_side is False
        assert config.needs_bot_session is False

    def test_server_side_tool_without_executor(self):
        """Test that server-side tools can be created without executor."""
        config = ToolConfig(
            name="web_search",
            definition={"type": "web_search_20250305", "name": "web_search"},
            executor=None,
            emoji="🔍",
            is_server_side=True,
        )

        assert config.name == "web_search"
        assert config.executor is None
        assert config.is_server_side is True

    def test_non_server_side_without_executor_raises_error(self):
        """Test that non-server-side tools without executor raise error."""
        with pytest.raises(ValueError, match="must have an executor"):
            ToolConfig(
                name="bad_tool",
                definition={"name": "bad_tool"},
                executor=None,
                is_server_side=False,
            )

    def test_name_mismatch_raises_error(self):
        """Test that name mismatch between config and definition raises error."""
        mock_executor = Mock()
        with pytest.raises(ValueError, match="Tool name mismatch"):
            ToolConfig(
                name="config_name",
                definition={"name": "definition_name"},
                executor=mock_executor,
            )

    def test_definition_without_name_passes(self):
        """Test that definition without name field passes validation."""
        mock_executor = Mock()
        config = ToolConfig(
            name="tool_without_def_name",
            definition={"type": "some_type"},
            executor=mock_executor,
        )
        assert config.name == "tool_without_def_name"

    def test_default_emoji(self):
        """Test that default emoji is wrench."""
        mock_executor = Mock()
        config = ToolConfig(
            name="test",
            definition={"name": "test"},
            executor=mock_executor,
        )
        assert config.emoji == "🔧"

    def test_custom_emoji(self):
        """Test that custom emoji can be set."""
        mock_executor = Mock()
        config = ToolConfig(
            name="python_tool",
            definition={"name": "python_tool"},
            executor=mock_executor,
            emoji="🐍",
        )
        assert config.emoji == "🐍"

    def test_needs_bot_session_flag(self):
        """Test that needs_bot_session flag is set correctly."""
        mock_executor = Mock()
        config = ToolConfig(
            name="file_tool",
            definition={"name": "file_tool"},
            executor=mock_executor,
            needs_bot_session=True,
        )
        assert config.needs_bot_session is True


class TestToolConfigGetSystemMessage:
    """Tests for ToolConfig.get_system_message() method."""

    def test_get_system_message_with_formatter(self):
        """Test that system message is generated when formatter exists."""
        mock_executor = Mock()
        mock_formatter = Mock(return_value="Executed tool successfully")

        config = ToolConfig(
            name="test_tool",
            definition={"name": "test_tool"},
            executor=mock_executor,
            format_result=mock_formatter,
        )

        tool_input = {"param": "value"}
        result = {"status": "ok"}

        message = config.get_system_message(tool_input, result)

        assert message == "Executed tool successfully"
        mock_formatter.assert_called_once_with(tool_input, result)

    def test_get_system_message_without_formatter(self):
        """Test that empty string returned when no formatter."""
        mock_executor = Mock()
        config = ToolConfig(
            name="test_tool",
            definition={"name": "test_tool"},
            executor=mock_executor,
            format_result=None,
        )

        message = config.get_system_message({"param": "value"}, {"status": "ok"})

        assert message == ""

    def test_formatter_receives_correct_arguments(self):
        """Test that formatter receives tool_input and result correctly."""
        mock_executor = Mock()
        captured_args = {}

        def capturing_formatter(tool_input, result):
            captured_args["tool_input"] = tool_input
            captured_args["result"] = result
            return "formatted"

        config = ToolConfig(
            name="test_tool",
            definition={"name": "test_tool"},
            executor=mock_executor,
            format_result=capturing_formatter,
        )

        tool_input = {"code": "print('hello')"}
        result = {"stdout": "hello", "success": "true"}

        config.get_system_message(tool_input, result)

        assert captured_args["tool_input"] == tool_input
        assert captured_args["result"] == result


class TestToolConfigEdgeCases:
    """Tests for edge cases in ToolConfig."""

    def test_empty_definition(self):
        """Test that empty definition is allowed."""
        mock_executor = Mock()
        config = ToolConfig(
            name="minimal_tool",
            definition={},
            executor=mock_executor,
        )
        assert config.definition == {}

    def test_complex_definition_structure(self):
        """Test that complex definition structures are preserved."""
        mock_executor = Mock()
        complex_def = {
            "name": "complex_tool",
            "description": "A complex tool",
            "input_schema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                    "param2": {"type": "integer"},
                },
                "required": ["param1"],
            },
        }

        config = ToolConfig(
            name="complex_tool",
            definition=complex_def,
            executor=mock_executor,
        )

        assert config.definition == complex_def
        assert config.definition["input_schema"]["properties"]["param1"] == {
            "type": "string"
        }

    def test_async_executor_accepted(self):
        """Test that async functions are accepted as executors."""
        async def async_executor(**kwargs):
            return {"result": "ok"}

        config = ToolConfig(
            name="async_tool",
            definition={"name": "async_tool"},
            executor=async_executor,
        )

        assert config.executor == async_executor
        assert callable(config.executor)
