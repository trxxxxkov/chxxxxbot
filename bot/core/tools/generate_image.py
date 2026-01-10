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

from datetime import datetime
from datetime import UTC
from pathlib import Path
from typing import Any, Dict, TYPE_CHECKING

from google import genai
from google.genai import types as genai_types
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


def read_secret(secret_name: str) -> str:
    """Read secret from Docker secrets.

    Args:
        secret_name: Name of the secret file.

    Returns:
        Secret value as string.
    """
    secret_path = Path(f"/run/secrets/{secret_name}")
    return secret_path.read_text(encoding="utf-8").strip()


# Lazy client initialization
_client: genai.Client | None = None


def get_client() -> genai.Client:
    """Get or create Google GenAI client.

    Returns:
        Google GenAI client instance.
    """
    global _client  # pylint: disable=global-statement
    if _client is None:
        api_key = read_secret("google_api_key")
        _client = genai.Client(api_key=api_key)
        logger.info("tools.generate_image.client_initialized")
    return _client


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

        client = get_client()
        response = client.models.generate_content(
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

        logger.info("tools.generate_image.api_call_success",
                    parts_count=len(response.parts) if response.parts else 0)

        # Step 2: Extract image from response
        image_bytes = None
        generated_text = None

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

        # Step 4: Calculate cost
        # Pricing: 1K/2K = $0.134, 4K = $0.24
        cost_usd = 0.24 if image_size == "4K" else 0.134

        logger.info("tools.generate_image.complete",
                    filename=filename,
                    cost_usd=cost_usd,
                    image_size=image_size,
                    size_bytes=len(image_bytes))

        # Return result with _file_contents for automatic delivery
        # Handler will: upload to Files API, save to DB, send to user
        result = {
            "success":
                "true",
            "cost_usd":
                f"{cost_usd:.3f}",
            "parameters_used": {
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
                "model": "gemini-3-pro-image-preview",
            },
            "_file_contents": [{
                "filename": filename,
                "content": image_bytes,
                "mime_type": mime_type,
            }],
        }

        # Add generated text if present
        if generated_text:
            result["generated_text"] = generated_text

        return result

    except Exception as e:
        logger.error("tools.generate_image.failed", error=str(e), exc_info=True)

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
