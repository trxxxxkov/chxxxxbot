"""Tests for deliver_file tool.

Tests file delivery from Redis cache to user.

Phase 5.3 Refactored:
- Cleaner fixture organization
- Reduced redundant mock setup
- Added more edge case tests
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

from core.tools.deliver_file import deliver_file
from core.tools.deliver_file import DELIVER_FILE_TOOL
from core.tools.deliver_file import format_deliver_file_result
from core.tools.deliver_file import TOOL_CONFIG
import pytest

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_bot():
    """Create mock Telegram bot."""
    return AsyncMock()


@pytest.fixture
def mock_session():
    """Create mock database session."""
    return AsyncMock()


@pytest.fixture
def sample_temp_id():
    """Sample temp ID for testing."""
    return "exec_abc12345_chart.png"


@pytest.fixture
def sample_metadata():
    """Sample file metadata from Redis."""
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
def sample_content():
    """Sample PNG file content."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 12339


@pytest.fixture
def pdf_metadata():
    """Sample PDF metadata."""
    return {
        "temp_id": "exec_def67890_report.pdf",
        "filename": "report.pdf",
        "size_bytes": 50000,
        "mime_type": "application/pdf",
    }


@pytest.fixture
def pdf_content():
    """Sample PDF file content."""
    return b"%PDF-1.4\n" + b"\x00" * 49991


# ============================================================================
# Tests for deliver_file tool execution
# ============================================================================


class TestDeliverFile:
    """Tests for deliver_file function."""

    @pytest.mark.asyncio
    async def test_success(self, mock_bot, mock_session, sample_temp_id,
                           sample_metadata, sample_content):
        """Test successful file delivery."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=sample_content), \
             patch("core.tools.deliver_file.delete_exec_file",
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
    async def test_with_caption(self, mock_bot, mock_session, sample_temp_id,
                                sample_metadata, sample_content):
        """Test file delivery with caption."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=sample_content), \
             patch("core.tools.deliver_file.delete_exec_file",
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
    async def test_meta_not_found(self, mock_bot, mock_session, sample_temp_id):
        """Test error when metadata not found (expired)."""
        with patch("core.tools.deliver_file.get_exec_meta", return_value=None):
            result = await deliver_file(
                temp_id=sample_temp_id,
                bot=mock_bot,
                session=mock_session,
            )

        assert result["success"] == "false"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_content_not_found(self, mock_bot, mock_session,
                                     sample_temp_id, sample_metadata):
        """Test error when content not found (expired)."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=None):
            result = await deliver_file(
                temp_id=sample_temp_id,
                bot=mock_bot,
                session=mock_session,
            )

        assert result["success"] == "false"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_cleans_cache_after_delivery(self, mock_bot, mock_session,
                                               sample_temp_id, sample_metadata,
                                               sample_content):
        """Test file is deleted from cache after delivery."""
        mock_delete = AsyncMock(return_value=True)

        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=sample_content), \
             patch("core.tools.deliver_file.delete_exec_file",
                   mock_delete):
            await deliver_file(
                temp_id=sample_temp_id,
                bot=mock_bot,
                session=mock_session,
            )

        mock_delete.assert_called_once_with(sample_temp_id)

    @pytest.mark.asyncio
    async def test_exception_handling(self, mock_bot, mock_session,
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

    @pytest.mark.asyncio
    async def test_pdf_delivery(self, mock_bot, mock_session, pdf_metadata,
                                pdf_content):
        """Test PDF file delivery."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=pdf_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=pdf_content), \
             patch("core.tools.deliver_file.delete_exec_file",
                   return_value=True):
            result = await deliver_file(
                temp_id=pdf_metadata["temp_id"],
                bot=mock_bot,
                session=mock_session,
            )

        assert result["success"] == "true"
        assert result["_file_contents"][0]["mime_type"] == "application/pdf"
        assert result["_file_contents"][0]["filename"] == "report.pdf"


# ============================================================================
# Tests for sequential delivery mode
# ============================================================================


class TestSequentialDelivery:
    """Tests for sequential delivery mode (Phase 3.4)."""

    @pytest.mark.asyncio
    async def test_sequential_false_no_turn_break(self, mock_bot, mock_session,
                                                  sample_metadata,
                                                  sample_content):
        """Test default (sequential=False) has no turn break marker."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=sample_content), \
             patch("core.tools.deliver_file.delete_exec_file",
                   return_value=True):
            result = await deliver_file(
                temp_id="exec_abc12345",
                bot=mock_bot,
                session=mock_session,
                sequential=False,
            )

        assert result["success"] == "true"
        assert "_force_turn_break" not in result

    @pytest.mark.asyncio
    async def test_sequential_true_has_turn_break(self, mock_bot, mock_session,
                                                  sample_metadata,
                                                  sample_content):
        """Test sequential=True adds turn break marker."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=sample_content), \
             patch("core.tools.deliver_file.delete_exec_file",
                   return_value=True):
            result = await deliver_file(
                temp_id="exec_abc12345",
                bot=mock_bot,
                session=mock_session,
                sequential=True,
            )

        assert result["success"] == "true"
        assert result["_force_turn_break"] is True

    @pytest.mark.asyncio
    async def test_sequential_error_no_turn_break(self, mock_bot, mock_session):
        """Test error result has no turn break marker."""
        with patch("core.tools.deliver_file.get_exec_meta", return_value=None):
            result = await deliver_file(
                temp_id="nonexistent",
                bot=mock_bot,
                session=mock_session,
                sequential=True,
            )

        assert result["success"] == "false"
        assert "_force_turn_break" not in result

    @pytest.mark.asyncio
    async def test_sequential_with_caption(self, mock_bot, mock_session,
                                           sample_metadata, sample_content):
        """Test sequential works with caption."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=sample_content), \
             patch("core.tools.deliver_file.delete_exec_file",
                   return_value=True):
            result = await deliver_file(
                temp_id="exec_abc12345",
                bot=mock_bot,
                session=mock_session,
                caption="First chart",
                sequential=True,
            )

        assert result["success"] == "true"
        assert result["_force_turn_break"] is True
        assert result["caption"] == "First chart"


# ============================================================================
# Tests for result formatting
# ============================================================================


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
        assert len(formatted) < 120

    def test_format_error_with_special_chars(self):
        """Test error message with special characters."""
        result = {"success": "false", "error": "File 'test.png' <expired>"}
        tool_input = {"temp_id": "exec_abc_test.png"}

        formatted = format_deliver_file_result(tool_input, result)

        assert "expired" in formatted


# ============================================================================
# Tests for tool configuration
# ============================================================================


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
        assert TOOL_CONFIG.format_result == format_deliver_file_result


class TestToolDefinition:
    """Tests for DELIVER_FILE_TOOL definition."""

    def test_definition_name(self):
        """Test tool definition has correct name."""
        assert DELIVER_FILE_TOOL["name"] == "deliver_file"

    def test_definition_has_description(self):
        """Test tool definition has description."""
        assert "description" in DELIVER_FILE_TOOL
        assert len(DELIVER_FILE_TOOL["description"]) > 100

    def test_definition_required_params(self):
        """Test tool definition has required parameters."""
        schema = DELIVER_FILE_TOOL["input_schema"]
        assert "temp_id" in schema["properties"]
        assert "temp_id" in schema["required"]

    def test_definition_optional_caption(self):
        """Test caption is optional."""
        schema = DELIVER_FILE_TOOL["input_schema"]
        assert "caption" in schema["properties"]
        assert "caption" not in schema["required"]

    def test_definition_sequential_param(self):
        """Test sequential parameter is defined."""
        schema = DELIVER_FILE_TOOL["input_schema"]
        assert "sequential" in schema["properties"]
        assert schema["properties"]["sequential"]["type"] == "boolean"
        assert "sequential" not in schema["required"]

    def test_description_mentions_key_concepts(self):
        """Test description mentions key concepts."""
        description = DELIVER_FILE_TOOL["description"]
        assert "execute_python" in description.lower()
        assert "temp_id" in description
        assert "cache" in description.lower() or "30 min" in description


# ============================================================================
# Edge case tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_empty_temp_id(self, mock_bot, mock_session):
        """Test empty temp_id is handled."""
        with patch("core.tools.deliver_file.get_exec_meta", return_value=None):
            result = await deliver_file(
                temp_id="",
                bot=mock_bot,
                session=mock_session,
            )

        assert result["success"] == "false"

    @pytest.mark.asyncio
    async def test_very_long_caption(self, mock_bot, mock_session,
                                     sample_metadata, sample_content):
        """Test very long caption is handled."""
        long_caption = "A" * 5000

        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=sample_content), \
             patch("core.tools.deliver_file.delete_exec_file",
                   return_value=True):
            result = await deliver_file(
                temp_id="exec_abc12345",
                bot=mock_bot,
                session=mock_session,
                caption=long_caption,
            )

        assert result["success"] == "true"
        assert result["caption"] == long_caption

    @pytest.mark.asyncio
    async def test_unicode_filename(self, mock_bot, mock_session):
        """Test unicode filename is handled."""
        metadata = {
            "temp_id": "exec_xyz_график.png",
            "filename": "график.png",
            "size_bytes": 1000,
            "mime_type": "image/png",
        }

        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=b"\x89PNG"), \
             patch("core.tools.deliver_file.delete_exec_file",
                   return_value=True):
            result = await deliver_file(
                temp_id="exec_xyz_график.png",
                bot=mock_bot,
                session=mock_session,
            )

        assert result["success"] == "true"
        assert result["_file_contents"][0]["filename"] == "график.png"

    @pytest.mark.asyncio
    async def test_delete_failure_still_succeeds(self, mock_bot, mock_session,
                                                 sample_metadata,
                                                 sample_content):
        """Test delivery succeeds even if cache delete fails."""
        with patch("core.tools.deliver_file.get_exec_meta",
                   return_value=sample_metadata), \
             patch("core.tools.deliver_file.get_exec_file",
                   return_value=sample_content), \
             patch("core.tools.deliver_file.delete_exec_file",
                   return_value=False):  # Delete fails
            result = await deliver_file(
                temp_id="exec_abc12345",
                bot=mock_bot,
                session=mock_session,
            )

        # Delivery still succeeds
        assert result["success"] == "true"
