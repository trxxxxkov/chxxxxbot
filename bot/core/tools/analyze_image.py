"""Analyze image tool using Claude Vision API with Files API.

This module implements the analyze_image tool for processing user-uploaded
images through Claude's vision capabilities. Uses Files API file IDs.

NO __init__.py - use direct import:
    from core.tools.analyze_image import analyze_image, ANALYZE_IMAGE_TOOL
"""

from pathlib import Path
from typing import Dict

import anthropic
from utils.structured_logging import get_logger

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
_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    """Get or create Anthropic client for tool execution.

    Returns:
        Anthropic client instance.
    """
    global _client  # pylint: disable=global-statement
    if _client is None:
        api_key = read_secret("anthropic_api_key")
        _client = anthropic.Anthropic(
            api_key=api_key,
            default_headers={"anthropic-beta": "files-api-2025-04-14"})
        logger.info("tools.analyze_image.client_initialized")
    return _client


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
    try:
        logger.info("tools.analyze_image.called",
                    claude_file_id=claude_file_id,
                    question_length=len(question))

        client = get_client()

        # Call Claude Vision API with file from Files API
        response = client.messages.create(model="claude-sonnet-4-5-20250929",
                                          max_tokens=2048,
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

        analysis = response.content[0].text
        tokens_used = response.usage.input_tokens + response.usage.output_tokens

        logger.info("tools.analyze_image.success",
                    claude_file_id=claude_file_id,
                    tokens_used=tokens_used,
                    analysis_length=len(analysis))

        return {"analysis": analysis, "tokens_used": str(tokens_used)}

    except Exception as e:
        logger.error("tools.analyze_image.failed",
                     claude_file_id=claude_file_id,
                     error=str(e),
                     exc_info=True)
        # Re-raise to let caller handle
        raise


# Tool definition for Claude API (anthropic tools format)
ANALYZE_IMAGE_TOOL = {
    "name":
        "analyze_image",
    "description":
        """Analyze an image using Claude's vision capabilities.

Use this tool for photos, screenshots, diagrams, charts when you need
visual understanding. The tool uses Claude's vision API to analyze the
image and answer questions about its content. It can identify objects,
read text (OCR), describe scenes, analyze visual data, understand charts
and diagrams, and extract information from screenshots.

When to use: User asks about image content, wants to extract text from
images, needs description of visual elements, wants to analyze charts/diagrams,
or asks questions about photos they uploaded.

When NOT to use: For text-only questions, when image is not relevant to
the query, or when file is a PDF (use analyze_pdf instead).

Limitations: Cannot identify people by name (AUP violation), limited
spatial reasoning (analog clocks, chess positions), approximate counting
only (not precise for many small objects), cannot detect AI-generated images,
no healthcare diagnostics (CTs, MRIs, X-rays).

Token cost: Approximately 1600 tokens per 1092x1092px image. Larger images
consume proportionally more tokens.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "claude_file_id": {
                "type":
                    "string",
                "description": ("File ID from Files API (claude_file_id from "
                                "available files list in conversation)")
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
