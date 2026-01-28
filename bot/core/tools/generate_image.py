"""Image generation and editing tool using Google Gemini 3 Pro Image API.

This module implements the generate_image tool for high-quality image
generation, editing, and composition using Google's Nano Banana Pro model
(gemini-3-pro-image-preview).

Capabilities:
- Text-to-image generation (up to 4K resolution)
- Image editing with natural language instructions
- Multi-image composition (up to 14 reference images)
- Google Search grounding for real-time data visualization

Files are saved to exec_cache for model review before delivery.
Model can iterate on results or deliver directly to user.

NO __init__.py - use direct import:
    from core.tools.generate_image import (
        generate_image,
        GENERATE_IMAGE_TOOL
    )
"""

import asyncio
import base64
from datetime import datetime
from datetime import UTC
import io
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from cache.exec_cache import store_exec_file
from core.clients import get_google_client
from core.pricing import calculate_gemini_image_cost
from core.pricing import cost_to_float
from google.genai import types as genai_types
from PIL import Image
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Tool definition for Claude API
# Follows Claude 4 best practices: explicit instructions, context for WHY,
# positive framing, XML tags for structure
GENERATE_IMAGE_TOOL = {
    "name":
        "generate_image",
    "description":
        """Create, edit, or compose images using Gemini 3 Pro Image.

This tool operates in three modes based on the parameters you provide:

<generation_mode>
When source_file_ids is empty or omitted, the tool generates a new image
from your text prompt. Write detailed prompts in English describing the
subject, style, composition, lighting, colors, and mood. The model excels
at photorealistic images, artistic styles, and creative compositions.
</generation_mode>

<editing_mode>
When source_file_ids contains one or more image file IDs, the tool edits
or transforms those images according to your prompt. You can remove objects,
change backgrounds, adjust lighting, apply style transfers, or combine
elements from multiple images. The model preserves visual context and
maintains consistency with the source material.

For identity preservation across multiple outputs, include face reference
images and specify "preserve identity" or "maintain facial features" in
your prompt.
</editing_mode>

<grounded_mode>
When use_google_search is true, the tool grounds generation in real-time
web data before creating the image. Use this for current weather maps,
live stock charts, recent news visualizations, or any content requiring
up-to-date information. The model searches, verifies facts, then generates
accurate imagery.
</grounded_mode>

<output_handling>
Generated images are saved to temporary cache for your review. You receive
a visual preview to verify the result meets requirements. If the image
needs adjustments, call generate_image again with refined prompt or
source_file_ids pointing to the generated image for iterative editing.

When satisfied with the result, use deliver_file(temp_id) to send the
image to the user. You can also use preview_file(temp_id) for detailed
analysis before delivery.

4K images are automatically delivered as documents (preserving full quality).
For other resolutions, you can override with send_mode="document" if user
explicitly requests maximum quality or uncompressed delivery.
</output_handling>

<prompt_writing>
Effective prompts describe the scene rather than listing keywords. Include:
- Subject and main focus with specific details
- Visual style (photorealistic, oil painting, watercolor, anime, minimalist)
- Composition (close-up, wide shot, birds-eye view, symmetrical)
- Lighting conditions (natural, dramatic, soft, golden hour, neon)
- Color palette and mood

Example: "A serene Japanese garden at sunset, photorealistic style. Cherry
blossom trees in full bloom, koi pond reflecting golden light, traditional
wooden bridge. Soft warm lighting, pastel pink and orange palette, peaceful
contemplative mood."
</prompt_writing>

<parameters_guide>
aspect_ratio: Choose based on intended use
- 1:1 square for avatars, icons, social media posts
- 3:4 portrait for character portraits, mobile wallpapers
- 4:3 landscape for scenes, presentations, thumbnails
- 9:16 vertical for stories, phone backgrounds, vertical displays
- 16:9 widescreen for desktop wallpapers, banners, cinematic shots

image_size: Match resolution to user's quality requirements
- 1K for quick previews and thumbnails
- 2K for standard quality, suitable for most uses
- 4K for high detail, print quality, professional assets

Choose 4K automatically when user mentions: "high quality", "maximum quality",
"high resolution", "high res", "4K", "print quality", "detailed", "professional",
"wallpaper", "poster", or similar quality-focused requests.

source_file_ids: Provide file IDs from Available Files or Pending Files
- Single image for direct editing or style transfer
- Multiple images for composition or identity preservation
- Up to 14 reference images supported (6 objects + 5 humans max)
- Accepts both claude_file_id (file_xxx) and temp_id (exec_xxx)
</parameters_guide>

<cost_info>
Generation costs $0.134 per image at 1K/2K, $0.240 at 4K resolution.
Google Search grounding adds approximately $0.02 per query.
Editing uses the same pricing as generation.
</cost_info>

<appropriate_uses>
Use this tool for photos, portraits, artwork, illustrations, logos, icons,
memes, abstract art, patterns, textures, product mockups, and concept art.

For charts, graphs, data visualizations, diagrams, flowcharts, or any
content requiring precise data representation, use execute_python with
matplotlib or plotly instead.
</appropriate_uses>""",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description":
                    "Detailed image description in English. Describe the scene "
                    "including subject, style, composition, lighting, colors, "
                    "and mood. For editing, describe the desired changes."
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["1:1", "3:4", "4:3", "9:16", "16:9"],
                "description": "Image dimensions. Default 1:1 square."
            },
            "image_size": {
                "type": "string",
                "enum": ["1K", "2K", "4K"],
                "description": "Output resolution. Default 2K."
            },
            "source_file_ids": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description":
                    "File IDs of images to edit or use as references. "
                    "From Available Files or Pending Files. Leave empty for generation."
            },
            "use_google_search": {
                "type": "boolean",
                "description":
                    "Ground generation in real-time web data. "
                    "Enable for weather, stocks, news, current events."
            },
        },
        "required": ["prompt"],
    },
}


async def _get_image_from_file_id(
    file_id: str,
    bot: 'Bot',
    session: 'AsyncSession',
) -> Optional[Image.Image]:
    """Load image from file ID using unified FileManager.

    Args:
        file_id: Any file ID format (exec_xxx, file_xxx, or telegram_file_id).
        bot: Telegram bot instance.
        session: Database session.

    Returns:
        PIL Image object or None if not found/not image.
    """
    # Import here to avoid circular dependencies
    from core.file_manager import \
        FileManager  # pylint: disable=import-outside-toplevel

    try:
        file_manager = FileManager(bot, session)
        content, metadata = await file_manager.get_file_content(file_id)

        mime_type = metadata.get("mime_type", "")
        if not mime_type.startswith("image/"):
            logger.info("generate_image.file_not_image",
                        file_id=file_id,
                        mime_type=mime_type)
            return None

        return Image.open(io.BytesIO(content))

    except FileNotFoundError:
        logger.info("generate_image.file_not_found", file_id=file_id)
        return None
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.info("generate_image.file_load_error",
                    file_id=file_id,
                    error=str(e))
        return None


async def generate_image(  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    prompt: str,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: int | None = None,
    aspect_ratio: str = "1:1",
    image_size: str = "2K",
    source_file_ids: List[str] | None = None,
    use_google_search: bool = False,
) -> Dict[str, Any]:
    """Generate, edit, or compose images using Google Gemini 3 Pro Image API.

    This function supports three modes:
    1. Generation: Create new image from text prompt (source_file_ids empty)
    2. Editing: Modify existing images (source_file_ids provided)
    3. Grounded: Generate based on real-time web data (use_google_search=True)

    Images are saved to exec_cache for model review. Use deliver_file() to
    send to user after verification.

    Args:
        prompt: Image description or editing instructions (English).
        bot: Telegram Bot instance (unused, for interface consistency).
        session: Database session for file operations.
        thread_id: Thread ID for exec_cache association.
        aspect_ratio: Image aspect ratio (1:1, 3:4, 4:3, 9:16, 16:9).
        image_size: Resolution (1K, 2K, 4K).
        source_file_ids: File IDs of images to edit/compose (up to 14).
        use_google_search: Ground generation in real-time web data.

    Returns:
        Dictionary with generation result including temp_id and preview.

    Raises:
        ValueError: If prompt is empty.
        Exception: If generation fails (API error, content policy).
    """
    _ = bot  # Unused
    _ = session  # Unused

    # Determine mode for logging
    mode = "generate"
    if source_file_ids:
        mode = "edit" if len(source_file_ids) == 1 else "compose"
    if use_google_search:
        mode = f"grounded_{mode}"

    logger.info("tools.generate_image.called",
                mode=mode,
                prompt_length=len(prompt),
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                source_count=len(source_file_ids) if source_file_ids else 0,
                use_google_search=use_google_search)

    # Validate prompt
    if not prompt or not prompt.strip():
        raise ValueError("Prompt cannot be empty")

    try:
        # Step 1: Build contents array
        contents: List[Any] = [prompt]

        # Load source images if provided
        if source_file_ids:
            loaded_count = 0
            for file_id in source_file_ids[:14]:  # Max 14 reference images
                img = await _get_image_from_file_id(file_id, bot, session)
                if img:
                    contents.append(img)
                    loaded_count += 1
                else:
                    logger.warning("tools.generate_image.source_not_loaded",
                                   file_id=file_id)

            if loaded_count == 0 and source_file_ids:
                return {
                    "success": "false",
                    "error":
                        "Could not load any source images. Verify file IDs "
                        "are correct and files are images. Use file IDs from "
                        "Available Files (file_xxx) or Pending Files (exec_xxx).",
                }

            logger.info("tools.generate_image.sources_loaded",
                        requested=len(source_file_ids),
                        loaded=loaded_count)

        # Step 2: Configure tools for grounding
        tools = None
        if use_google_search:
            tools = [genai_types.Tool(google_search=genai_types.GoogleSearch())]
            logger.info("tools.generate_image.grounding_enabled")

        # Step 3: Call Google GenAI API
        logger.info("tools.generate_image.api_call_start",
                    prompt=prompt[:100],
                    content_parts=len(contents))

        client = get_google_client()

        def _sync_generate() -> Any:
            return client.models.generate_content(
                model="gemini-3-pro-image-preview",
                contents=contents,
                config=genai_types.GenerateContentConfig(
                    response_modalities=['TEXT', 'IMAGE'],
                    tools=tools,
                    image_config=genai_types.ImageConfig(
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                    ),
                ),
            )

        response = await asyncio.to_thread(_sync_generate)

        logger.info("tools.generate_image.api_call_success",
                    parts_count=len(response.parts) if response.parts else 0)

        # Step 4: Extract image from response
        image_bytes = None
        generated_text = None

        if not response.parts:
            logger.info("tools.generate_image.no_parts",
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
                image_bytes = part.inline_data.data
                logger.info("tools.generate_image.image_received",
                            size_bytes=len(image_bytes))
                break

        if not image_bytes:
            logger.info(
                "tools.generate_image.no_image",
                response_parts=len(response.parts) if response.parts else 0,
                generated_text=generated_text[:200] if generated_text else None)
            return {
                "success":
                    "false",
                "error":
                    "No image generated. " +
                    (f"Model response: {generated_text[:200]}"
                     if generated_text else "Try a different prompt."),
            }

        # Step 5: Save to exec_cache (NOT auto-deliver)
        action = "edited" if source_file_ids else "generated"
        filename = f"{action}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.png"
        mime_type = "image/png"

        # Context describes what this file is
        prompt_context = prompt[:200] + ("..." if len(prompt) > 200 else "")
        if source_file_ids:
            file_context = f"Edited image ({len(source_file_ids)} sources): {prompt_context}"
        elif use_google_search:
            file_context = f"Grounded image: {prompt_context}"
        else:
            file_context = f"Generated image: {prompt_context}"

        # Store in exec_cache with delivery hint for 4K images
        import uuid  # pylint: disable=import-outside-toplevel
        execution_id = uuid.uuid4().hex[:8]

        # 4K images should be sent as documents to preserve quality
        delivery_hint = "document" if image_size == "4K" else None

        metadata = await store_exec_file(
            filename=filename,
            content=image_bytes,
            mime_type=mime_type,
            context=file_context,
            execution_id=execution_id,
            thread_id=thread_id,
            delivery_hint=delivery_hint,
        )

        if not metadata:
            return {
                "success": "false",
                "error": "Failed to cache generated image. Try again.",
            }

        temp_id = metadata["temp_id"]

        logger.info("tools.generate_image.cached",
                    temp_id=temp_id,
                    filename=filename,
                    size_bytes=len(image_bytes))

        # Step 6: Calculate cost
        resolution = "4096x4096" if image_size == "4K" else "2048x2048"
        cost_usd = calculate_gemini_image_cost(resolution)

        # Add grounding cost if used
        if use_google_search:
            from core.pricing import \
                GOOGLE_SEARCH_GROUNDING_COST  # pylint: disable=import-outside-toplevel
            cost_usd += GOOGLE_SEARCH_GROUNDING_COST

        logger.info("tools.generate_image.complete",
                    mode=mode,
                    temp_id=temp_id,
                    filename=filename,
                    cost_usd=cost_to_float(cost_usd),
                    image_size=image_size,
                    size_bytes=len(image_bytes))

        # Build result with preview for model verification
        result: Dict[str, Any] = {
            "success": "true",
            "mode": mode,
            "cost_usd": f"{cost_to_float(cost_usd):.3f}",
            "output_file": {
                "temp_id":
                    temp_id,
                "filename":
                    filename,
                "size_bytes":
                    len(image_bytes),
                "mime_type":
                    mime_type,
                "preview":
                    metadata.get("preview", f"Image {len(image_bytes)} bytes"),
            },
            "next_steps":
                "Review the image preview below. If satisfactory, use "
                "deliver_file(temp_id) to send to user. For adjustments, "
                "call generate_image again with refined prompt.",
        }

        # Add image preview for Claude to visually verify
        # Limited to images under 2MB to avoid context bloat
        if len(image_bytes) < 2 * 1024 * 1024:
            result["_image_preview"] = {
                "data": base64.b64encode(image_bytes).decode('utf-8'),
                "media_type": mime_type,
            }
            logger.info("tools.generate_image.preview_included",
                        temp_id=temp_id,
                        size_kb=len(image_bytes) / 1024)

        if generated_text:
            result["generated_text"] = generated_text

        return result

    except Exception as e:
        logger.info("tools.generate_image.external_error", error=str(e))

        error_msg = str(e).lower()
        if "content" in error_msg and ("policy" in error_msg or "violation"
                                       in error_msg or "blocked" in error_msg):
            return {
                "success": "false",
                "error":
                    "Content policy violation: The prompt was blocked by "
                    "Google's safety filters. Please try a different prompt.",
            }

        raise


def format_generate_image_result(
    tool_input: Dict[str, Any],
    result: Dict[str, Any],
) -> str:
    """Format generate_image result for user display.

    Args:
        tool_input: The input parameters.
        result: The result dictionary.

    Returns:
        Formatted system message string.
    """
    if "error" in result:
        error = result.get("error", "unknown error")
        preview = error[:80] + "..." if len(error) > 80 else error
        return f"[❌ Ошибка: {preview}]"

    mode = result.get("mode", "generate")
    resolution = tool_input.get("image_size", "2K")

    if "edit" in mode:
        return f"[🖌️ Изображение отредактировано ({resolution}), ожидает проверки]"
    if "compose" in mode:
        return f"[🎭 Композиция создана ({resolution}), ожидает проверки]"
    if "grounded" in mode:
        return f"[🌐 Изображение с веб-данными ({resolution}), ожидает проверки]"

    return f"[🎨 Изображение создано ({resolution}), ожидает проверки]"


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
