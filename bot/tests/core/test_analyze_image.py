"""Tests for analyze_image tool (Phase 1.5 Stage 2).

Tests image analysis tool functionality, including:
- Successful image analysis
- Error handling
- Vision API integration
"""

from unittest.mock import Mock
from unittest.mock import patch

# Import the module to test
from core.tools.analyze_image import analyze_image
from core.tools.analyze_image import ANALYZE_IMAGE_TOOL
from core.tools.analyze_image import get_client
import pytest


@pytest.fixture(autouse=True)
def reset_client():
    """Reset global client before and after each test."""
    # Reset before test
    import core.tools.analyze_image
    core.tools.analyze_image._client = None
    yield
    # Reset after test
    core.tools.analyze_image._client = None


class TestAnalyzeImage:
    """Tests for analyze_image() function."""

    @pytest.mark.asyncio
    @patch('core.tools.analyze_image.get_client')
    async def test_analyze_image_success(self, mock_get_client):
        """Test successful image analysis."""
        # Setup mock
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="This is a beautiful sunset.")]
        mock_response.usage = Mock(input_tokens=1600, output_tokens=50)
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Test
        result = await analyze_image(claude_file_id="file_test123",
                                     question="What's in this image?")

        # Verify
        assert result["analysis"] == "This is a beautiful sunset."
        assert result["tokens_used"] == "1650"

        # Verify API call
        mock_client.messages.create.assert_called_once()
        call_args = mock_client.messages.create.call_args[1]
        assert call_args["model"] == "claude-sonnet-4-5-20250929"
        assert call_args["max_tokens"] == 2048

        # Check message structure
        messages = call_args["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert len(messages[0]["content"]) == 2

        # Check image block
        image_block = messages[0]["content"][0]
        assert image_block["type"] == "image"
        assert image_block["source"]["type"] == "file"
        assert image_block["source"]["file_id"] == "file_test123"

        # Check text block
        text_block = messages[0]["content"][1]
        assert text_block["type"] == "text"
        assert text_block["text"] == "What's in this image?"

    @pytest.mark.asyncio
    @patch('core.tools.analyze_image.get_client')
    async def test_analyze_image_detailed_question(self, mock_get_client):
        """Test image analysis with detailed question."""
        # Setup mock
        mock_client = Mock()
        mock_response = Mock()
        mock_response.content = [Mock(text="The image shows 5 red apples.")]
        mock_response.usage = Mock(input_tokens=1600, output_tokens=20)
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Test
        result = await analyze_image(
            claude_file_id="file_abc",
            question="Count how many apples are visible in this image")

        # Verify
        assert result["analysis"] == "The image shows 5 red apples."
        assert result["tokens_used"] == "1620"

        # Verify question was passed
        call_args = mock_client.messages.create.call_args[1]
        text_block = call_args["messages"][0]["content"][1]
        assert "Count how many apples" in text_block["text"]

    @pytest.mark.asyncio
    @patch('core.tools.analyze_image.get_client')
    async def test_analyze_image_api_error(self, mock_get_client):
        """Test analyze_image with API error."""
        # Setup mock to raise exception
        mock_client = Mock()
        mock_client.messages.create.side_effect = Exception("Vision API Error")
        mock_get_client.return_value = mock_client

        # Test
        with pytest.raises(Exception, match="Vision API Error"):
            await analyze_image(claude_file_id="file_test123",
                                question="What is this?")

    @pytest.mark.asyncio
    @patch('core.tools.analyze_image.get_client')
    async def test_analyze_image_large_response(self, mock_get_client):
        """Test analyze_image with large token response."""
        # Setup mock with large response
        mock_client = Mock()
        mock_response = Mock()
        long_text = "This is a detailed analysis. " * 100
        mock_response.content = [Mock(text=long_text)]
        mock_response.usage = Mock(input_tokens=1600, output_tokens=500)
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        # Test
        result = await analyze_image(claude_file_id="file_large",
                                     question="Describe this image in detail")

        # Verify
        assert result["analysis"] == long_text
        assert result["tokens_used"] == "2100"


class TestAnalyzeImageToolDefinition:
    """Tests for ANALYZE_IMAGE_TOOL definition."""

    def test_tool_definition_structure(self):
        """Test that ANALYZE_IMAGE_TOOL has correct structure."""
        tool = ANALYZE_IMAGE_TOOL

        # Check basic structure
        assert tool["name"] == "analyze_image"
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

        # Check property types
        assert properties["claude_file_id"]["type"] == "string"
        assert properties["question"]["type"] == "string"

    def test_tool_description_content(self):
        """Test that tool description contains key information."""
        description = ANALYZE_IMAGE_TOOL["description"]

        # Should mention key features
        assert "image" in description.lower()
        assert "vision" in description.lower(
        ) or "analyze" in description.lower()

        # Should mention when to use (XML format)
        assert "<when_to_use>" in description
        assert "<when_not_to_use>" in description

        # Should mention limitations (XML format)
        assert "<limitations>" in description
        assert "token" in description.lower()

    def test_tool_description_mentions_use_cases(self):
        """Test that description includes common use cases."""
        description = ANALYZE_IMAGE_TOOL["description"]

        # Should mention at least some use cases
        assert any(keyword in description.lower() for keyword in
                   ["photo", "screenshot", "chart", "diagram", "ocr", "text"])
