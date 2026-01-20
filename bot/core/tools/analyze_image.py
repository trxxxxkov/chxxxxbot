"""Analyze image tool using Claude Vision API with Files API.

This module implements the analyze_image tool for processing user-uploaded
images through Claude's vision capabilities. Uses Files API file IDs.

NO __init__.py - use direct import:
    from core.tools.analyze_image import analyze_image, ANALYZE_IMAGE_TOOL
"""

import asyncio
from typing import Any, Dict

from anthropic import APIStatusError
from core.clients import get_anthropic_client
from core.pricing import calculate_claude_cost
from core.pricing import cost_to_float
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Retry configuration for transient API errors
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0
RETRYABLE_STATUS_CODES = {500, 502, 503, 504, 529}


async def analyze_image(claude_file_id: str, question: str) -> Dict[str, str]:
    """Analyze an image using Claude's vision capabilities.

    Uses Claude Vision API to analyze images uploaded via Files API.
    Supports object detection, OCR, scene understanding, chart analysis,
    and visual question answering.

    Args:
        claude_file_id: Files API file ID (from user_files table).
        question: What to analyze or extract from the image.
            Be specific about information needed.

    Returns:
        Dictionary with 'analysis' key containing Claude's response,
        and 'tokens_used' key with token count.

    Raises:
        Exception: If API call fails or file not found.

    Examples:
        >>> result = await analyze_image(
        ...     claude_file_id="file_abc123...",
        ...     question="What objects are visible in this image?"
        ... )
        >>> print(result['analysis'])
    """
    logger.info("tools.analyze_image.called",
                claude_file_id=claude_file_id,
                question_length=len(question))

    # Use centralized client factory with Files API beta header
    client = get_anthropic_client(use_files_api=True)
    model_id = "claude-opus-4-5-20251101"

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            # Call Claude Vision API with file from Files API
            # Run in thread pool to avoid blocking event loop
            # This allows keepalive updates during long API calls
            def _sync_call() -> Any:
                return client.messages.create(
                    model=model_id,
                    max_tokens=8192,
                    messages=[{
                        "role":
                            "user",
                        "content": [{
                            "type": "image",
                            "source": {
                                "type": "file",
                                "file_id": claude_file_id
                            }
                        }, {
                            "type": "text",
                            "text": question
                        }]
                    }])

            response = await asyncio.to_thread(_sync_call)

            analysis = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            tokens_used = input_tokens + output_tokens

            # Use centralized pricing calculation
            cost_usd = calculate_claude_cost(
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

            logger.info("tools.analyze_image.success",
                        claude_file_id=claude_file_id,
                        tokens_used=tokens_used,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=cost_to_float(cost_usd),
                        analysis_length=len(analysis))

            return {
                "analysis": analysis,
                "tokens_used": str(tokens_used),
                "cost_usd": f"{cost_to_float(cost_usd):.6f}"
            }

        except APIStatusError as e:
            last_error = e
            if e.status_code in RETRYABLE_STATUS_CODES:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_SECONDS * (2**attempt)
                    logger.warning("tools.analyze_image.retry",
                                   claude_file_id=claude_file_id,
                                   attempt=attempt + 1,
                                   max_retries=MAX_RETRIES,
                                   status_code=e.status_code,
                                   delay_seconds=delay)
                    await asyncio.sleep(delay)
                    continue
            # Non-retryable error or max retries reached
            logger.error("tools.analyze_image.failed",
                         claude_file_id=claude_file_id,
                         error=str(e),
                         exc_info=True)
            raise

        except Exception as e:
            logger.error("tools.analyze_image.failed",
                         claude_file_id=claude_file_id,
                         error=str(e),
                         exc_info=True)
            raise

    # Should not reach here, but satisfy mypy
    if last_error:
        raise last_error
    raise RuntimeError("Unexpected: retry loop completed without result")


# Tool definition for Claude API (anthropic tools format)
ANALYZE_IMAGE_TOOL = {
    "name":
        "analyze_image",
    "description":
        """Analyze an image using Claude's vision capabilities.

IMPORTANT: This tool ONLY works with IMAGE files (JPEG, PNG, GIF, WebP).
Check the file's mime_type in "Available files" - it MUST start with "image/".
For data files (.json, .jsonl, .csv, .txt), use execute_python to read them directly.

Use this tool for photos, screenshots, diagrams, charts when you need
visual understanding. The tool uses Claude Sonnet 4.5's vision API to analyze
images and answer questions about content. It can identify objects, read text (OCR),
describe scenes, analyze visual data, understand charts and diagrams, and extract
information from screenshots.

<supported_formats>
ONLY these MIME types are supported:
- image/jpeg, image/png, image/gif, image/webp
Check mime_type in "Available files" section before calling this tool.
</supported_formats>

<verification_use_case>
CRITICAL: This tool is essential for verifying image outputs from execute_python.
When you generate images (charts, diagrams, processed photos), you MUST use this
tool to verify the output is correct before considering the task complete. This
catches issues like wrong colors, missing elements, incorrect text rendering,
or visual artifacts that code-level checks cannot detect.

Example: After generating chart.png, call analyze_image to verify axes labels,
data points, legend, and overall visual quality match expectations.
</verification_use_case>

<when_to_use>
Use when:
- User asks about image content or visual elements
- Extracting text from images (OCR)
- Analyzing charts, diagrams, or data visualizations
- Verifying generated images from execute_python (quality check)
- Understanding file content before processing (e.g., analyzing PPTX screenshot)
- Answering questions about uploaded photos

Note: You can call this tool in PARALLEL with execute_python when analyzing
input files before processing them (e.g., understand image content while
preparing processing code).
</when_to_use>

<when_not_to_use>
Do NOT use for:
- NON-IMAGE files (.json, .jsonl, .csv, .txt, .pdf) - use execute_python instead
- PDF files (use analyze_pdf instead for better text extraction)
- Text-only questions where image is not relevant
- When user explicitly asks not to analyze images
</when_not_to_use>

<limitations>
- Cannot identify people by name (AUP violation)
- Limited spatial reasoning (analog clocks, chess positions)
- Approximate counting only (not precise for many small objects)
- Cannot detect AI-generated images
- No healthcare diagnostics (CTs, MRIs, X-rays)
</limitations>

Token cost: ~1600 tokens per 1092x1092px image. Larger images consume proportionally more.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "claude_file_id": {
                "type":
                    "string",
                "description": ("File ID from Files API. MUST be an image file "
                                "(mime_type starting with 'image/'). Check "
                                "'Available files' section for file details.")
            },
            "question": {
                "type":
                    "string",
                "description": ("What to analyze or extract from the image. "
                                "Be specific about what information is needed "
                                "(e.g., 'What objects are visible?', "
                                "'Extract all text from this screenshot', "
                                "'What does this chart show?')")
            }
        },
        "required": ["claude_file_id", "question"]
    }
}

# Unified tool configuration (no format_result - internal analysis tool)
from core.tools.base import ToolConfig  # pylint: disable=wrong-import-position

TOOL_CONFIG = ToolConfig(
    name="analyze_image",
    definition=ANALYZE_IMAGE_TOOL,
    executor=analyze_image,
    emoji="🖼️",
    needs_bot_session=False,
    format_result=None,  # No system message for analysis tools
    file_id_param="claude_file_id",
    allowed_mime_prefixes=["image/"],  # Only image/* MIME types
)
