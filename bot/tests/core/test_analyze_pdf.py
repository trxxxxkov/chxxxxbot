"""Tests for analyze_pdf tool (Phase 1.5 Stage 3).

Tests PDF analysis tool functionality, including:
- Successful PDF analysis
- Page range support
- Prompt caching
- Error handling
- Retry logic for transient errors
"""

from unittest.mock import Mock
from unittest.mock import patch

from anthropic import APIStatusError
# Import the module to test
from core.tools.analyze_pdf import analyze_pdf
from core.tools.analyze_pdf import ANALYZE_PDF_TOOL
from core.tools.analyze_pdf import MAX_RETRIES
from core.tools.analyze_pdf import RETRYABLE_STATUS_CODES
import pytest


@pytest.fixture(autouse=True)
def reset_client():
    """Reset global client before and after each test."""
    # Reset before test
    import core.clients
    core.clients._anthropic_sync_files = None
    yield
    # Reset after test
    core.clients._anthropic_sync_files = None


class TestAnalyzePdf:
    """Tests for analyze_pdf() function."""

    @pytest.mark.asyncio
    @patch('core.tools.analyze_pdf.get_anthropic_client')
    async def test_analyze_pdf_success(self, mock_get_client):
        """Test successful PDF analysis."""
        # Setup mock
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="This is a test document.")]
        mock_response.usage = Mock(input_tokens=1000,
                                   output_tokens=50,
                                   cache_creation_input_tokens=0,
                                   cache_read_input_tokens=0)
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Test
        result = await analyze_pdf(claude_file_id="file_test123",
                                   question="What is this document about?")

        # Verify
        assert result["analysis"] == "This is a test document."
        assert result["tokens_used"] == "1050"
        assert result["cached_tokens"] == "0"
        assert "cost_usd" in result  # Phase 2.1: Cost tracking
        assert float(result["cost_usd"]) > 0

        # Verify API call
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args[1]
        assert call_args["model"] == "claude-opus-4-5-20251101"
        assert call_args["max_tokens"] == 16384

        # Check message structure
        messages = call_args["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert len(messages[0]["content"]) == 2

        # Check document block
        doc_block = messages[0]["content"][0]
        assert doc_block["type"] == "document"
        assert doc_block["source"]["type"] == "file"
        assert doc_block["source"]["file_id"] == "file_test123"
        assert doc_block["cache_control"]["type"] == "ephemeral"

        # Check text block
        text_block = messages[0]["content"][1]
        assert text_block["type"] == "text"
        assert text_block["text"] == "What is this document about?"

    @pytest.mark.asyncio
    @patch('core.tools.analyze_pdf.get_anthropic_client')
    async def test_analyze_pdf_with_page_range(self, mock_get_client):
        """Test PDF analysis with specific page range."""
        # Setup mock
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="Page 1-3 content")]
        mock_response.usage = Mock(input_tokens=500,
                                   output_tokens=30,
                                   cache_creation_input_tokens=0,
                                   cache_read_input_tokens=0)
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Test
        result = await analyze_pdf(claude_file_id="file_test123",
                                   question="Summarize these pages",
                                   pages="1-3")

        # Verify
        assert result["analysis"] == "Page 1-3 content"
        assert result["tokens_used"] == "530"
        assert "cost_usd" in result  # Phase 2.1: Cost tracking

        # Verify question includes page range
        call_args = mock_client.messages.create.call_args[1]
        text_block = call_args["messages"][0]["content"][1]
        assert "1-3" in text_block["text"]
        assert "Summarize these pages" in text_block["text"]

    @pytest.mark.asyncio
    @patch('core.tools.analyze_pdf.get_anthropic_client')
    async def test_analyze_pdf_with_cache_hit(self, mock_get_client):
        """Test PDF analysis with prompt cache hit."""
        # Setup mock with cache hit
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="Cached analysis")]
        mock_response.usage = Mock(
            input_tokens=100,  # Few new tokens
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=5000  # Many cached tokens
        )
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Test
        result = await analyze_pdf(claude_file_id="file_test123",
                                   question="What is this?")

        # Verify cache hit
        assert result["cached_tokens"] == "5000"
        assert result["tokens_used"] == "150"
        assert "cost_usd" in result  # Phase 2.1: Cost tracking

    @pytest.mark.asyncio
    @patch('core.tools.analyze_pdf.get_anthropic_client')
    async def test_analyze_pdf_api_error(self, mock_get_client):
        """Test analyze_pdf with API error."""
        # Setup mock to raise exception
        mock_client = Mock()
        mock_client.messages.create.side_effect = Exception("API Error")
        mock_get_client.return_value = mock_client

        # Test
        with pytest.raises(Exception, match="API Error"):
            await analyze_pdf(claude_file_id="file_test123", question="Test")


class TestAnalyzePdfToolDefinition:
    """Tests for ANALYZE_PDF_TOOL definition."""

    def test_tool_definition_structure(self):
        """Test that ANALYZE_PDF_TOOL has correct structure."""
        tool = ANALYZE_PDF_TOOL

        # Check basic structure
        assert tool["name"] == "analyze_pdf"
        assert "description" in tool
        assert "input_schema" in tool

        # Check input schema
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema

        # Check required parameters
        assert set(schema["required"]) == {"claude_file_id", "question"}

        # Check properties
        properties = schema["properties"]
        assert "claude_file_id" in properties
        assert "question" in properties
        assert "pages" in properties

        # Check property types
        assert properties["claude_file_id"]["type"] == "string"
        assert properties["question"]["type"] == "string"
        assert properties["pages"]["type"] == "string"

    def test_tool_description_content(self):
        """Test that tool description contains key information."""
        description = ANALYZE_PDF_TOOL["description"]

        # Should mention key features
        assert "PDF" in description or "pdf" in description
        assert "page" in description.lower()
        assert "token" in description.lower()

        # Should mention mime_type requirement (Claude 4 best practices)
        assert "mime_type" in description

        # Should mention cost
        assert "cost" in description.lower() or "token" in description.lower()


class TestAnalyzePdfRetry:
    """Tests for retry logic in analyze_pdf."""

    @pytest.mark.asyncio
    @patch('core.tools.analyze_pdf.asyncio.sleep')
    @patch('core.tools.analyze_pdf.get_anthropic_client')
    async def test_retry_on_503_then_success(self, mock_get_client, mock_sleep):
        """Test that 503 error triggers retry and eventually succeeds."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="Success after retry")]
        mock_response.usage = Mock(input_tokens=100,
                                   output_tokens=50,
                                   cache_creation_input_tokens=0,
                                   cache_read_input_tokens=0)

        # First call fails with 503, second succeeds
        error_response = Mock()
        error_response.status_code = 503
        error = APIStatusError(message="Service unavailable",
                               response=error_response,
                               body={"error": "overloaded"})
        mock_client.messages.create.side_effect = [error, mock_response]
        mock_get_client.return_value = mock_client

        result = await analyze_pdf(claude_file_id="file_test", question="Test?")

        assert result["analysis"] == "Success after retry"
        assert mock_client.messages.create.call_count == 2
        mock_sleep.assert_called_once()

    @pytest.mark.asyncio
    @patch('core.tools.analyze_pdf.asyncio.sleep')
    @patch('core.tools.analyze_pdf.get_anthropic_client')
    async def test_max_retries_exceeded(self, mock_get_client, mock_sleep):
        """Test that max retries exceeded raises error."""
        mock_client = Mock()
        error_response = Mock()
        error_response.status_code = 500

        error = APIStatusError(message="Internal server error",
                               response=error_response,
                               body={"error": "internal"})
        mock_client.messages.create.side_effect = error
        mock_get_client.return_value = mock_client

        with pytest.raises(APIStatusError):
            await analyze_pdf(claude_file_id="file_test", question="Test?")

        assert mock_client.messages.create.call_count == MAX_RETRIES

    @pytest.mark.asyncio
    @patch('core.tools.analyze_pdf.get_anthropic_client')
    async def test_non_retryable_error_not_retried(self, mock_get_client):
        """Test that 400 error is not retried."""
        mock_client = Mock()
        error_response = Mock()
        error_response.status_code = 400

        error = APIStatusError(message="Bad request",
                               response=error_response,
                               body={"error": "invalid"})
        mock_client.messages.create.side_effect = error
        mock_get_client.return_value = mock_client

        with pytest.raises(APIStatusError):
            await analyze_pdf(claude_file_id="file_test", question="Test?")

        # Should only be called once (no retries for 400)
        assert mock_client.messages.create.call_count == 1

    def test_retryable_status_codes(self):
        """Test that correct status codes are marked as retryable."""
        expected = {500, 502, 503, 504, 529}
        assert RETRYABLE_STATUS_CODES == expected

    def test_max_retries_constant(self):
        """Test that MAX_RETRIES is set correctly."""
        assert MAX_RETRIES == 3
