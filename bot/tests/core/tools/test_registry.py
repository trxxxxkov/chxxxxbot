"""Tests for tools registry (Phase 1.5 Stage 4).

Tests registry module functionality:
- Tool definitions structure
- Server-side tools configuration
- Client-side tools registration
- execute_tool dispatcher
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

from core.tools.registry import execute_tool
from core.tools.registry import TOOL_DEFINITIONS
from core.tools.registry import TOOL_EXECUTORS
from core.tools.registry import WEB_FETCH_TOOL
from core.tools.registry import WEB_SEARCH_TOOL
import pytest


class TestToolDefinitions:
    """Tests for TOOL_DEFINITIONS list."""

    def test_tool_definitions_is_list(self):
        """Test that TOOL_DEFINITIONS is a list."""
        assert isinstance(TOOL_DEFINITIONS, list)
        assert len(TOOL_DEFINITIONS) >= 4  # 2 client + 2 server

    def test_all_tools_have_required_fields(self):
        """Test that all tools have name field."""
        for tool in TOOL_DEFINITIONS:
            assert isinstance(tool, dict)
            assert "name" in tool

    def test_client_side_tools_have_description(self):
        """Test that client-side tools have description and input_schema."""
        client_tools = ["analyze_image", "analyze_pdf"]
        for tool in TOOL_DEFINITIONS:
            if tool["name"] in client_tools:
                assert "description" in tool
                assert "input_schema" in tool

    def test_server_side_tools_have_type(self):
        """Test that server-side tools have type field."""
        server_tools = ["web_search", "web_fetch"]
        for tool in TOOL_DEFINITIONS:
            if tool["name"] in server_tools:
                assert "type" in tool


class TestWebSearchTool:
    """Tests for WEB_SEARCH_TOOL definition."""

    def test_web_search_structure(self):
        """Test that WEB_SEARCH_TOOL has correct structure."""
        assert WEB_SEARCH_TOOL["type"] == "web_search_20250305"
        assert WEB_SEARCH_TOOL["name"] == "web_search"

    def test_web_search_in_definitions(self):
        """Test that web_search is in TOOL_DEFINITIONS."""
        tool_names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "web_search" in tool_names

    def test_web_search_not_in_executors(self):
        """Test that web_search is NOT in TOOL_EXECUTORS (server-side)."""
        assert "web_search" not in TOOL_EXECUTORS


class TestWebFetchTool:
    """Tests for WEB_FETCH_TOOL definition."""

    def test_web_fetch_structure(self):
        """Test that WEB_FETCH_TOOL has correct structure."""
        assert WEB_FETCH_TOOL["type"] == "web_fetch_20250910"
        assert WEB_FETCH_TOOL["name"] == "web_fetch"

    def test_web_fetch_in_definitions(self):
        """Test that web_fetch is in TOOL_DEFINITIONS."""
        tool_names = [t["name"] for t in TOOL_DEFINITIONS]
        assert "web_fetch" in tool_names

    def test_web_fetch_not_in_executors(self):
        """Test that web_fetch is NOT in TOOL_EXECUTORS (server-side)."""
        assert "web_fetch" not in TOOL_EXECUTORS


class TestToolExecutors:
    """Tests for TOOL_EXECUTORS mapping."""

    def test_tool_executors_is_dict(self):
        """Test that TOOL_EXECUTORS is a dictionary."""
        assert isinstance(TOOL_EXECUTORS, dict)

    def test_client_tools_have_executors(self):
        """Test that client-side tools have executors."""
        assert "analyze_image" in TOOL_EXECUTORS
        assert "analyze_pdf" in TOOL_EXECUTORS

    def test_server_tools_have_no_executors(self):
        """Test that server-side tools have NO executors."""
        assert "web_search" not in TOOL_EXECUTORS
        assert "web_fetch" not in TOOL_EXECUTORS

    def test_executors_are_callable(self):
        """Test that all executors are callable."""
        for tool_name, executor in TOOL_EXECUTORS.items():
            assert callable(executor), f"{tool_name} executor is not callable"


class TestExecuteTool:
    """Tests for execute_tool() dispatcher function."""

    @pytest.mark.asyncio
    @patch('core.tools.analyze_image.get_client')
    async def test_execute_client_tool_success(self, mock_get_client):
        """Test executing client-side tool successfully."""
        # Setup mock client
        from unittest.mock import Mock
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="Test result")]
        mock_response.usage = Mock(input_tokens=100, output_tokens=50)
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Execute
        result = await execute_tool(tool_name="analyze_image",
                                    tool_input={
                                        "claude_file_id": "file_123",
                                        "question": "Test?"
                                    })

        # Verify
        assert result["analysis"] == "Test result"
        assert result["tokens_used"] == "150"

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_raises_error(self):
        """Test that unknown tool raises ValueError."""
        with pytest.raises(ValueError, match="Tool 'unknown_tool' not found"):
            await execute_tool(tool_name="unknown_tool", tool_input={})

    @pytest.mark.asyncio
    async def test_execute_server_tool_raises_error(self):
        """Test that server-side tool raises error (should not be called)."""
        # Server-side tools should never reach execute_tool
        # (they're executed by Anthropic automatically)
        with pytest.raises(ValueError, match="not found"):
            await execute_tool(tool_name="web_search",
                               tool_input={"query": "test"})

    @pytest.mark.asyncio
    @patch('core.tools.analyze_pdf.get_client')
    async def test_execute_tool_with_error(self, mock_get_client):
        """Test that tool execution errors are propagated."""
        # Setup mock to raise error
        from unittest.mock import Mock
        mock_client = Mock()
        mock_client.messages.create.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        # Execute and verify exception is raised
        with pytest.raises(Exception, match="API error"):
            await execute_tool(tool_name="analyze_pdf",
                               tool_input={
                                   "claude_file_id": "file_123",
                                   "question": "Test?"
                               })

    @pytest.mark.asyncio
    @patch('core.tools.analyze_image.get_client')
    async def test_execute_tool_passes_all_parameters(self, mock_get_client):
        """Test that all input parameters are passed to tool."""
        # Setup mock
        from unittest.mock import Mock
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="OK")]
        mock_response.usage = Mock(input_tokens=50, output_tokens=10)
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Execute with multiple parameters
        result = await execute_tool(tool_name="analyze_image",
                                    tool_input={
                                        "claude_file_id": "file_abc",
                                        "question": "What is this?"
                                    })

        # Verify result returned correctly
        assert result["analysis"] == "OK"
        assert result["tokens_used"] == "60"
