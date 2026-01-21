"""Tests for deliver_file tool.

Tests file delivery from Redis cache to user.
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

from core.tools.deliver_file import deliver_file
from core.tools.deliver_file import DELIVER_FILE_TOOL
from core.tools.deliver_file import format_deliver_file_result
from core.tools.deliver_file import TOOL_CONFIG
import pytest


class TestDeliverFileTool:
    """Tests for deliver_file tool execution."""

    @pytest.fixture
    def mock_bot(self):
        """Create mock Telegram bot."""
        return AsyncMock()

    @pytest.fixture
    def mock_session(self):
        """Create mock database session."""
        return AsyncMock()

    @pytest.fixture
    def sample_temp_id(self):
        """Sample temp ID."""
        return "exec_abc12345_chart.png"

    @pytest.fixture
    def sample_metadata(self):
        """Sample file metadata."""
        return {
            "temp_id": "exec_abc12345_chart.png",
            "filename": "chart.png",
            "size_bytes": 12345,
            "mime_type": "image/png",
            "preview": "Image 800x600 (RGB), 12.1 KB",
            "execution_id": "xyz789",
            "created_at": 1234567890.0,
            "expires_at": 1234569690.0,
        }

    @pytest.fixture
    def sample_content(self):
        """Sample file content."""
        return b"\x89PNG\r\n" + b"\x00" * 12339

    @pytest.mark.asyncio
    async def test_deliver_file_success(self, mock_bot, mock_session,
                                        sample_temp_id, sample_metadata,
                                        sample_content):
        """Test successful file delivery."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata):
            with patch("core.tools.deliver_file.get_exec_file",
                       return_value=sample_content):
                with patch("core.tools.deliver_file.delete_exec_file",
                           return_value=True):
                    result = await deliver_file(
                        temp_id=sample_temp_id,
                        bot=mock_bot,
                        session=mock_session,
                    )

        assert result["success"] == "true"
        assert "_file_contents" in result
        assert len(result["_file_contents"]) == 1
        assert result["_file_contents"][0]["filename"] == "chart.png"
        assert result["_file_contents"][0]["content"] == sample_content
        assert result["_file_contents"][0]["mime_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_deliver_file_with_caption(self, mock_bot, mock_session,
                                             sample_temp_id, sample_metadata,
                                             sample_content):
        """Test file delivery with caption."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata):
            with patch("core.tools.deliver_file.get_exec_file",
                       return_value=sample_content):
                with patch("core.tools.deliver_file.delete_exec_file",
                           return_value=True):
                    result = await deliver_file(
                        temp_id=sample_temp_id,
                        bot=mock_bot,
                        session=mock_session,
                        caption="Your chart is ready!",
                    )

        assert result["success"] == "true"
        assert result["caption"] == "Your chart is ready!"

    @pytest.mark.asyncio
    async def test_deliver_file_meta_not_found(self, mock_bot, mock_session,
                                               sample_temp_id):
        """Test error when metadata not found (expired)."""
        with patch("core.tools.deliver_file.get_exec_meta", return_value=None):
            result = await deliver_file(
                temp_id=sample_temp_id,
                bot=mock_bot,
                session=mock_session,
            )

        assert result["success"] == "false"
        assert "not found" in result["error"]
        assert "expired" in result["error"] or "TTL" in result["error"]

    @pytest.mark.asyncio
    async def test_deliver_file_content_not_found(self, mock_bot, mock_session,
                                                  sample_temp_id,
                                                  sample_metadata):
        """Test error when content not found (expired)."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata):
            with patch("core.tools.deliver_file.get_exec_file",
                       return_value=None):
                result = await deliver_file(
                    temp_id=sample_temp_id,
                    bot=mock_bot,
                    session=mock_session,
                )

        assert result["success"] == "false"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_deliver_file_cleans_cache(self, mock_bot, mock_session,
                                             sample_temp_id, sample_metadata,
                                             sample_content):
        """Test file is deleted from cache after delivery."""
        mock_delete = AsyncMock(return_value=True)

        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata):
            with patch("core.tools.deliver_file.get_exec_file",
                       return_value=sample_content):
                with patch("core.tools.deliver_file.delete_exec_file",
                           mock_delete):
                    await deliver_file(
                        temp_id=sample_temp_id,
                        bot=mock_bot,
                        session=mock_session,
                    )

        mock_delete.assert_called_once_with(sample_temp_id)

    @pytest.mark.asyncio
    async def test_deliver_file_exception_handling(self, mock_bot, mock_session,
                                                   sample_temp_id):
        """Test exception returns error result."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   side_effect=Exception("Redis connection error")):
            result = await deliver_file(
                temp_id=sample_temp_id,
                bot=mock_bot,
                session=mock_session,
            )

        assert result["success"] == "false"
        assert "Redis connection error" in result["error"]


class TestFormatDeliverFileResult:
    """Tests for result formatting."""

    def test_format_success_empty(self):
        """Test success result returns empty string (file speaks for itself)."""
        result = {"success": "true"}
        tool_input = {"temp_id": "exec_abc_test.png"}

        formatted = format_deliver_file_result(tool_input, result)

        assert formatted == ""

    def test_format_error_short(self):
        """Test short error message."""
        result = {"success": "false", "error": "File not found"}
        tool_input = {"temp_id": "exec_abc_test.png"}

        formatted = format_deliver_file_result(tool_input, result)

        assert "File not found" in formatted

    def test_format_error_truncated(self):
        """Test long error message is truncated."""
        long_error = "x" * 100
        result = {"success": "false", "error": long_error}
        tool_input = {"temp_id": "exec_abc_test.png"}

        formatted = format_deliver_file_result(tool_input, result)

        assert "..." in formatted
        # Error is truncated to 80 chars + prefix "[Failed to deliver file: " + "...]"
        assert len(formatted) < 120


class TestToolConfig:
    """Tests for tool configuration."""

    def test_tool_config_name(self):
        """Test tool config has correct name."""
        assert TOOL_CONFIG.name == "deliver_file"

    def test_tool_config_needs_bot_session(self):
        """Test tool requires bot and session."""
        assert TOOL_CONFIG.needs_bot_session is True

    def test_tool_config_emoji(self):
        """Test tool has emoji."""
        assert TOOL_CONFIG.emoji == "📤"

    def test_tool_config_has_formatter(self):
        """Test tool has result formatter."""
        assert TOOL_CONFIG.format_result is not None

    def test_tool_definition_name(self):
        """Test tool definition has correct name."""
        assert DELIVER_FILE_TOOL["name"] == "deliver_file"

    def test_tool_definition_required_params(self):
        """Test tool definition has required parameters."""
        schema = DELIVER_FILE_TOOL["input_schema"]

        assert "temp_id" in schema["properties"]
        assert "temp_id" in schema["required"]

    def test_tool_definition_optional_caption(self):
        """Test caption is optional."""
        schema = DELIVER_FILE_TOOL["input_schema"]

        assert "caption" in schema["properties"]
        assert "caption" not in schema["required"]

    def test_tool_definition_description(self):
        """Test description mentions key concepts."""
        description = DELIVER_FILE_TOOL["description"]

        assert "execute_python" in description.lower()
        assert "temp_id" in description
        assert "cache" in description.lower() or "30 min" in description
