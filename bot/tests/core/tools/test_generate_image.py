"""Tests for generate_image tool (Phase 1.7+).

Tests Google Gemini 3 Pro Image API integration:
- Success flow (image generation) with exec_cache storage
- Parameter handling (aspect_ratio, image_size)
- Error handling (API errors, content policy violations)
- Cost calculation
- Client singleton pattern
- Tool definition schema
"""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from core.tools.generate_image import generate_image
from core.tools.generate_image import GENERATE_IMAGE_TOOL
import pytest


@pytest.fixture(autouse=True)
def reset_client():
    """Reset global client before and after each test."""
    # Reset before test
    import core.clients
    core.clients._google_client = None
    yield
    # Reset after test
    core.clients._google_client = None


@pytest.fixture
def mock_exec_cache():
    """Mock exec_cache storage returning proper metadata."""

    async def mock_store(filename,
                         content,
                         mime_type,
                         context,
                         execution_id,
                         thread_id,
                         delivery_hint=None):
        return {
            "temp_id": f"exec_{execution_id}",
            "filename": filename,
            "mime_type": mime_type,
            "preview": f"Image {len(content)} bytes",
            "delivery_hint": delivery_hint,
        }

    with patch('core.tools.generate_image.store_exec_file',
               side_effect=mock_store):
        yield


# ============================================================================
# GENERATE_IMAGE_TOOL Schema Tests
# ============================================================================


def test_tool_definition_structure():
    """Test GENERATE_IMAGE_TOOL has correct structure."""
    assert "name" in GENERATE_IMAGE_TOOL
    assert "description" in GENERATE_IMAGE_TOOL
    assert "input_schema" in GENERATE_IMAGE_TOOL

    # Check tool name
    assert GENERATE_IMAGE_TOOL["name"] == "generate_image"

    # Check input schema
    schema = GENERATE_IMAGE_TOOL["input_schema"]
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "required" in schema

    # Check required parameters
    assert set(schema["required"]) == {"prompt"}

    # Check properties
    properties = schema["properties"]
    assert "prompt" in properties
    assert "aspect_ratio" in properties
    assert "image_size" in properties

    # Check aspect_ratio enum
    assert "enum" in properties["aspect_ratio"]
    assert set(properties["aspect_ratio"]["enum"]) == {
        "1:1", "3:4", "4:3", "9:16", "16:9"
    }

    # Check image_size enum
    assert "enum" in properties["image_size"]
    assert set(properties["image_size"]["enum"]) == {"1K", "2K", "4K"}


# ============================================================================
# generate_image() Tests
# ============================================================================


@pytest.mark.asyncio
async def test_generate_image_success(mock_exec_cache):
    """Test successful image generation with default parameters."""
    # Mock response from Google API
    mock_response = MagicMock()
    mock_response.parts = [
        MagicMock(text=None,
                  inline_data=MagicMock(data=b"fake_image_bytes_here"))
    ]

    # Mock client
    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="A robot with a skateboard",
            bot=MagicMock(),
            session=MagicMock(),
        )

        # Verify result structure (exec_cache pattern)
        assert result["success"] == "true"
        assert "cost_usd" in result
        assert result["cost_usd"] == "0.134"  # Default 2K cost
        assert result["mode"] == "generate"

        # Check output_file with temp_id (exec_cache pattern)
        assert "output_file" in result
        output_file = result["output_file"]
        assert "temp_id" in output_file
        assert output_file["temp_id"].startswith("exec_")
        assert "filename" in output_file
        assert output_file["mime_type"] == "image/png"

        # Check image preview for Claude verification
        assert "_image_preview" in result
        assert "data" in result["_image_preview"]
        assert "media_type" in result["_image_preview"]

        # Check next_steps guidance
        assert "next_steps" in result
        assert "deliver_file" in result["next_steps"]


@pytest.mark.asyncio
async def test_generate_image_custom_parameters(mock_exec_cache):
    """Test image generation with custom aspect ratio and size."""
    mock_response = MagicMock()
    mock_response.parts = [
        MagicMock(text=None, inline_data=MagicMock(data=b"fake_4k_image"))
    ]

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="A landscape",
            bot=MagicMock(),
            session=MagicMock(),
            aspect_ratio="16:9",
            image_size="4K",
        )

        # Verify result (4K costs more)
        assert result["success"] == "true"
        assert result["cost_usd"] == "0.240"  # 4K cost

        # Check output_file with temp_id (exec_cache pattern)
        assert "output_file" in result
        assert result["output_file"]["temp_id"].startswith("exec_")


@pytest.mark.asyncio
async def test_generate_image_with_generated_text(mock_exec_cache):
    """Test image generation when model also returns text."""
    mock_response = MagicMock()
    mock_response.parts = [
        MagicMock(text="Here's your generated image!", inline_data=None),
        MagicMock(text=None, inline_data=MagicMock(data=b"image_bytes"))
    ]

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="Test",
            bot=MagicMock(),
            session=MagicMock(),
        )

        # Check that generated_text is included
        assert "generated_text" in result
        assert result["generated_text"] == "Here's your generated image!"
        # Also check success
        assert result["success"] == "true"


@pytest.mark.asyncio
async def test_generate_image_empty_prompt():
    """Test that empty prompt raises ValueError."""
    with pytest.raises(ValueError, match="Prompt cannot be empty"):
        await generate_image(
            prompt="",
            bot=MagicMock(),
            session=MagicMock(),
        )


@pytest.mark.asyncio
async def test_generate_image_no_image_in_response():
    """Test handling when API doesn't return image."""
    mock_response = MagicMock()
    mock_response.parts = [
        MagicMock(text="Sorry, couldn't generate image", inline_data=None)
    ]

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="Test",
            bot=MagicMock(),
            session=MagicMock(),
        )

        # Should return error
        assert result["success"] == "false"
        assert "error" in result
        assert "No image generated" in result["error"]


@pytest.mark.asyncio
async def test_generate_image_response_parts_none():
    """Test handling when API returns response.parts = None.

    Regression test for production bug where Google API returned
    a response with parts=None, causing TypeError: 'NoneType' object
    is not iterable.
    """
    mock_response = MagicMock()
    mock_response.parts = None  # API sometimes returns None

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="Test prompt",
            bot=MagicMock(),
            session=MagicMock(),
        )

        # Should return error, not raise exception
        assert result["success"] == "false"
        assert "error" in result
        assert "empty response" in result["error"].lower()


@pytest.mark.asyncio
async def test_generate_image_content_policy_violation():
    """Test handling of content policy violations."""
    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(
        side_effect=Exception("Content policy violation detected"))

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="Inappropriate content",
            bot=MagicMock(),
            session=MagicMock(),
        )

        # Should return content policy error
        assert result["success"] == "false"
        assert "error" in result
        assert "Content policy violation" in result["error"]
        assert "safety filters" in result["error"]


@pytest.mark.asyncio
async def test_generate_image_api_error():
    """Test handling of general API errors."""
    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(
        side_effect=Exception("API connection timeout"))

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        with pytest.raises(Exception, match="API connection timeout"):
            await generate_image(
                prompt="Test",
                bot=MagicMock(),
                session=MagicMock(),
            )


# ============================================================================
# Cost Calculation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_cost_calculation_1k(mock_exec_cache):
    """Test cost calculation for 1K images."""
    mock_response = MagicMock()
    mock_response.parts = [
        MagicMock(text=None, inline_data=MagicMock(data=b"image"))
    ]

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="Test",
            bot=MagicMock(),
            session=MagicMock(),
            image_size="1K",
        )

        assert result["success"] == "true"
        assert result["cost_usd"] == "0.134"


@pytest.mark.asyncio
async def test_cost_calculation_2k(mock_exec_cache):
    """Test cost calculation for 2K images."""
    mock_response = MagicMock()
    mock_response.parts = [
        MagicMock(text=None, inline_data=MagicMock(data=b"image"))
    ]

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="Test",
            bot=MagicMock(),
            session=MagicMock(),
            image_size="2K",
        )

        assert result["success"] == "true"
        assert result["cost_usd"] == "0.134"


@pytest.mark.asyncio
async def test_cost_calculation_4k(mock_exec_cache):
    """Test cost calculation for 4K images."""
    mock_response = MagicMock()
    mock_response.parts = [
        MagicMock(text=None, inline_data=MagicMock(data=b"image"))
    ]

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch('core.tools.generate_image.get_google_client',
               return_value=mock_client):

        result = await generate_image(
            prompt="Test",
            bot=MagicMock(),
            session=MagicMock(),
            image_size="4K",
        )

        assert result["success"] == "true"
        assert result["cost_usd"] == "0.240"
