"""Generate image tool using Google Gemini 3 Pro Image API.

This module implements the generate_image tool for high-quality image
generation up to 4K resolution using Google's Nano Banana Pro model
(gemini-3-pro-image-preview).

NO __init__.py - use direct import:
    from core.tools.generate_image import (
        generate_image,
        GENERATE_IMAGE_TOOL
    )
"""

import asyncio
from datetime import datetime
from datetime import UTC
from typing import Any, Dict, TYPE_CHECKING

from core.clients import get_google_client
from core.pricing import calculate_gemini_image_cost
from core.pricing import cost_to_float
from google.genai import types as genai_types
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Tool definition for Claude API
GENERATE_IMAGE_TOOL = {
    "name": "generate_image",
    "description":
        ("Generate high-quality images up to 4K resolution using Google's "
         "Nano Banana Pro (Gemini 3 Pro Image) model. Supports advanced "
         "features like Google Search grounding for reference images. "
         "Always generates ONE image per call. English prompts only."),
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type":
                    "string",
                "description":
                    ("Detailed image description in English (max 480 tokens). "
                     "Be specific about style, composition, lighting, colors, "
                     "mood, and any other visual details."),
            },
            "aspect_ratio": {
                "type":
                    "string",
                "enum": ["1:1", "3:4", "4:3", "9:16", "16:9"],
                "description":
                    ("Image aspect ratio. Options: "
                     "1:1 (square), 3:4 (portrait), 4:3 (landscape), "
                     "9:16 (vertical), 16:9 (widescreen). Default: 1:1"),
            },
            "image_size": {
                "type":
                    "string",
                "enum": ["1K", "2K", "4K"],
                "description":
                    ("Image resolution. 1K: ~1024px, 2K: ~2048px, 4K: ~4096px. "
                     "Higher resolution costs more. Default: 2K"),
            },
        },
        "required": ["prompt"],
    },
}


async def generate_image(  # pylint: disable=unused-argument,too-many-locals
    prompt: str,
    bot: 'Bot',
    session: 'AsyncSession',
    aspect_ratio: str = "1:1",
    image_size: str = "2K",
) -> Dict[str, Any]:
    """Generate image using Google Gemini 3 Pro Image API.

    Args:
        prompt: Image description (English, max 480 tokens).
        bot: Telegram Bot instance for sending generated image to user.
        session: Database session for saving file metadata.
        aspect_ratio: Image aspect ratio (1:1, 3:4, 4:3, 9:16, 16:9).
        image_size: Resolution (1K, 2K, 4K).

    Returns:
        Dictionary with generation result:
        {
            "success": "true",
            "file_id": "file_abc...",
            "cost_usd": "0.134",
            "parameters_used": {
                "aspect_ratio": "1:1",
                "image_size": "2K",
                "model": "gemini-3-pro-image-preview"
            }
        }

    Raises:
        ValueError: If prompt is empty or parameters are invalid.
        Exception: If generation fails (API error, content policy violation).

    Examples:
        >>> result = await generate_image(
        ...     prompt="Robot holding a red skateboard in cyberpunk style",
        ...     aspect_ratio="16:9",
        ...     image_size="4K",
        ...     bot=bot,
        ...     session=session
        ... )
        >>> print(result['file_id'])
    """
    logger.info("tools.generate_image.called",
                prompt_length=len(prompt),
                aspect_ratio=aspect_ratio,
                image_size=image_size)

    # Validate prompt
    if not prompt or not prompt.strip():
        raise ValueError("Prompt cannot be empty")

    try:
        # Step 1: Call Google GenAI API
        logger.info("tools.generate_image.api_call_start", prompt=prompt[:100])

        # Use centralized client factory
        client = get_google_client()

        # Run in thread pool to avoid blocking event loop
        # This allows keepalive updates during long API calls
        def _sync_generate() -> Any:
            return client.models.generate_content(
                model="gemini-3-pro-image-preview",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_modalities=['TEXT', 'IMAGE'],
                    image_config=genai_types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                    ),
                ),
            )

        response = await asyncio.to_thread(_sync_generate)

        logger.info("tools.generate_image.api_call_success",
                    parts_count=len(response.parts) if response.parts else 0)

        # Step 2: Extract image from response
        image_bytes = None
        generated_text = None

        # Check if response has parts
        if not response.parts:
            logger.error("tools.generate_image.no_parts",
                         response=str(response)[:500])
            return {
                "success": "false",
                "error":
                    "API returned empty response. The prompt may have "
                    "been blocked by content filters. Try a different prompt.",
            }

        for part in response.parts:
            if part.text is not None:
                generated_text = part.text
                logger.info("tools.generate_image.text_received",
                            text_length=len(part.text))
            elif part.inline_data is not None:
                # Get image bytes directly from inline_data
                image_bytes = part.inline_data.data
                logger.info("tools.generate_image.image_received",
                            size_bytes=len(image_bytes))
                break

        if not image_bytes:
            error_msg = "No image generated in response"
            logger.error(
                "tools.generate_image.no_image",
                response_parts=len(response.parts) if response.parts else 0)
            return {
                "success": "false",
                "error": error_msg,
            }

        # Step 3: Prepare file for delivery
        filename = f"generated_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.png"
        mime_type = "image/png"

        # Step 4: Use centralized pricing calculation
        # Maps image_size to resolution string for pricing
        resolution = "4096x4096" if image_size == "4K" else "2048x2048"
        cost_usd = calculate_gemini_image_cost(resolution)

        logger.info("tools.generate_image.complete",
                    filename=filename,
                    cost_usd=cost_to_float(cost_usd),
                    image_size=image_size,
                    size_bytes=len(image_bytes))

        # Return result with _file_contents for automatic delivery
        # Handler will: upload to Files API, save to DB, send to user
        # Note: Keep result minimal - image is auto-delivered to user,
        # Claude doesn't need to include image links in response
        result = {
            "success":
                "true",
            "cost_usd":
                f"{cost_to_float(cost_usd):.3f}",
            "_file_contents": [{
                "filename": filename,
                "content": image_bytes,
                "mime_type": mime_type,
            }],
        }

        # Add generated text if present (for text-to-image responses)
        if generated_text:
            result["generated_text"] = generated_text

        return result

    except Exception as e:
        # Log as info - external API errors handled correctly by our service
        logger.info("tools.generate_image.external_error", error=str(e))

        # Check for content policy violation
        error_msg = str(e).lower()
        if "content" in error_msg and ("policy" in error_msg or "violation"
                                       in error_msg or "blocked" in error_msg):
            return {
                "success": "false",
                "error":
                    "Content policy violation: The prompt was blocked by "
                    "Google's safety filters. Please try a different prompt.",
            }

        # Re-raise other exceptions
        raise


def format_generate_image_result(
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> str:
    """Format generate_image result for user display.

    Args:
        tool_input: The input parameters (prompt, aspect_ratio, image_size).
        result: The result dictionary with success, cost_usd.

    Returns:
        Formatted system message string (without newlines - handled by caller).
    """
    if "error" in result:
        error = result.get("error", "unknown error")
        preview = error[:80] + "..." if len(error) > 80 else error
        return f"[❌ Ошибка генерации: {preview}]"

    # Get params from tool_input since we removed parameters_used from result
    resolution = tool_input.get("image_size", "2K")
    aspect = tool_input.get("aspect_ratio", "")
    aspect_info = f", {aspect}" if aspect else ""
    return f"[🎨 Изображение создано ({resolution}{aspect_info})]"


# Unified tool configuration
from core.tools.base import ToolConfig  # pylint: disable=wrong-import-position

TOOL_CONFIG = ToolConfig(
    name="generate_image",
    definition=GENERATE_IMAGE_TOOL,
    executor=generate_image,
    emoji="🎨",
    needs_bot_session=True,
    format_result=format_generate_image_result,
)
