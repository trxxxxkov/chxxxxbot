"""Image generation and editing tool using Google Gemini 3 Pro Image API.

This module implements the generate_image tool for high-quality image
generation, editing, and composition using Google's Nano Banana Pro model
(gemini-3-pro-image-preview).

Capabilities:
- Text-to-image generation (up to 4K resolution)
- Image editing with natural language instructions
- Multi-image composition (up to 14 reference images)
- Google Search grounding for real-time data visualization

NO __init__.py - use direct import:
    from core.tools.generate_image import (
        generate_image,
        GENERATE_IMAGE_TOOL
    )
"""

import asyncio
from datetime import datetime
from datetime import UTC
import io
from typing import Any, Dict, List, Optional, TYPE_CHECKING

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
# positive framing, minimal aggressive language
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

image_size: Balance quality against cost
- 1K for quick previews and thumbnails
- 2K for standard quality, suitable for most uses
- 4K for high detail, print quality, professional assets

source_file_ids: Provide file IDs from Available Files section when editing
- Single image for direct editing or style transfer
- Multiple images for composition or identity preservation
- Up to 14 reference images supported (6 objects + 5 humans max)
</parameters_guide>

<cost_info>
Generation costs $0.134 per image at 1K/2K, $0.240 at 4K resolution.
Google Search grounding adds approximately $0.01-0.03 per query.
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
                    "From Available Files section. Leave empty for generation."
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
    session: 'AsyncSession',
) -> Optional[Image.Image]:
    """Load image from file ID (Claude Files API or exec_cache).

    Args:
        file_id: Either claude_file_id (file_xxx) or temp_id (exec_xxx).
        session: Database session (unused, for interface consistency).

    Returns:
        PIL Image object or None if not found/not image.
    """
    _ = session  # Unused, kept for interface consistency

    try:
        # Check exec_cache first (temporary generated files)
        if file_id.startswith("exec_"):
            from cache.exec_cache import \
                get_exec_file  # pylint: disable=import-outside-toplevel
            content, meta = await get_exec_file(file_id)
            if content and meta:
                mime = meta.get("mime_type", "")
                if mime.startswith("image/"):
                    return Image.open(io.BytesIO(content))
            logger.info("generate_image.file_not_image",
                        file_id=file_id,
                        mime_type=meta.get("mime_type") if meta else None)
            return None

        # Download from Claude Files API
        if file_id.startswith("file_"):
            from core.clients import \
                get_anthropic_client  # pylint: disable=import-outside-toplevel

            client = get_anthropic_client(use_files_api=True)

            # Run in thread pool to avoid blocking
            def _download() -> bytes:
                response = client.files.content(file_id)
                return response.read()

            content = await asyncio.to_thread(_download)
            return Image.open(io.BytesIO(content))

        logger.warning("generate_image.unknown_file_id_format", file_id=file_id)
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

    Args:
        prompt: Image description or editing instructions (English).
        bot: Telegram Bot instance (unused, for interface consistency).
        session: Database session for file operations.
        thread_id: Thread ID (unused, for interface consistency).
        aspect_ratio: Image aspect ratio (1:1, 3:4, 4:3, 9:16, 16:9).
        image_size: Resolution (1K, 2K, 4K).
        source_file_ids: File IDs of images to edit/compose (up to 14).
        use_google_search: Ground generation in real-time web data.

    Returns:
        Dictionary with generation result including _file_contents for delivery.

    Raises:
        ValueError: If prompt is empty.
        Exception: If generation fails (API error, content policy).
    """
    _ = bot  # Unused
    _ = thread_id  # Unused

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
                img = await _get_image_from_file_id(file_id, session)
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
                        "are correct and files are images.",
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

        # Step 5: Prepare file for delivery
        action = "edited" if source_file_ids else "generated"
        filename = f"{action}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.png"
        mime_type = "image/png"

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
                    filename=filename,
                    cost_usd=cost_to_float(cost_usd),
                    image_size=image_size,
                    size_bytes=len(image_bytes))

        # Build context description
        prompt_context = prompt[:200] + ("..." if len(prompt) > 200 else "")
        if source_file_ids:
            context = f"Edited image ({len(source_file_ids)} sources): {prompt_context}"
        elif use_google_search:
            context = f"Grounded image: {prompt_context}"
        else:
            context = f"Generated image: {prompt_context}"

        result: Dict[str, Any] = {
            "success":
                "true",
            "mode":
                mode,
            "cost_usd":
                f"{cost_to_float(cost_usd):.3f}",
            "_file_contents": [{
                "filename": filename,
                "content": image_bytes,
                "mime_type": mime_type,
                "context": context,
            }],
        }

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
    aspect = tool_input.get("aspect_ratio", "")
    aspect_info = f", {aspect}" if aspect else ""

    if "edit" in mode:
        return f"[🖌️ Изображение отредактировано ({resolution}{aspect_info})]"
    if "compose" in mode:
        return f"[🎭 Композиция создана ({resolution}{aspect_info})]"
    if "grounded" in mode:
        return f"[🌐 Изображение создано с веб-данными ({resolution}{aspect_info})]"

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
