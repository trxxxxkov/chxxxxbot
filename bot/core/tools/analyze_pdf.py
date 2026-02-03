"""Analyze PDF tool using Claude PDF API with Files API.

This module implements the analyze_pdf tool for processing user-uploaded
PDF documents through Claude's multimodal capabilities. Uses Files API file IDs.

NO __init__.py - use direct import:
    from core.tools.analyze_pdf import analyze_pdf, ANALYZE_PDF_TOOL
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


async def analyze_pdf(claude_file_id: str,
                      question: str,
                      pages: str = "all") -> Dict[str, Any]:
    """Analyze a PDF document using Claude's vision and text extraction.

    Uses Claude PDF API to analyze PDFs uploaded via Files API.
    Processes both text and visual elements (charts, diagrams, tables).
    Supports page range specification for cost optimization.

    Args:
        claude_file_id: Files API file ID (from user_files table).
        question: What to analyze or extract from the PDF.
            Be specific about information needed.
        pages: Page range to analyze. Format: '1-5' for pages 1 through 5,
            '3' for page 3 only, 'all' for entire document (default).
            Using specific pages dramatically reduces token cost for large PDFs.

    Returns:
        Dictionary with 'analysis' key containing Claude's response,
        'tokens_used' key with token count, and 'cached_tokens' key
        with cache read tokens (if caching was used).

    Raises:
        Exception: If API call fails or file not found.

    Examples:
        >>> result = await analyze_pdf(
        ...     claude_file_id="file_abc123...",
        ...     question="Summarize the main points of this document"
        ... )
        >>> print(result['analysis'])
    """
    logger.info("tools.analyze_pdf.called",
                claude_file_id=claude_file_id,
                question_length=len(question),
                pages=pages)

    # Use centralized client factory with Files API beta header
    client = get_anthropic_client(use_files_api=True)
    model_id = "claude-opus-4-5-20251101"

    # Build question with page range
    if pages != "all":
        full_question = f"{question}\n\nAnalyze pages: {pages}"
    else:
        full_question = question

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            # Call Claude PDF API with prompt caching
            # Run in thread pool to avoid blocking event loop
            # This allows keepalive updates during long API calls
            def _sync_call() -> Any:
                return client.messages.create(
                    model=model_id,
                    max_tokens=16384,
                    messages=[{
                        "role":
                            "user",
                        "content": [
                            {
                                "type": "document",
                                "source": {
                                    "type": "file",
                                    "file_id": claude_file_id
                                },
                                "cache_control": {
                                    "type": "ephemeral",
                                    "ttl": "1h"
                                }  # Cache PDF content for 1 hour
                            },
                            {
                                "type": "text",
                                "text": full_question
                            }
                        ]
                    }])

            response = await asyncio.to_thread(_sync_call)

            analysis = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cache_creation_tokens = response.usage.cache_creation_input_tokens
            cache_read_tokens = response.usage.cache_read_input_tokens
            tokens_used = input_tokens + output_tokens

            # Use centralized pricing calculation
            cost_usd = calculate_claude_cost(
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
            )

            logger.info("tools.analyze_pdf.success",
                        claude_file_id=claude_file_id,
                        tokens_used=tokens_used,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_creation_tokens=cache_creation_tokens,
                        cache_read_tokens=cache_read_tokens,
                        cache_hit=cache_read_tokens > 0,
                        cost_usd=cost_to_float(cost_usd),
                        analysis_length=len(analysis))

            return {
                "analysis": analysis,
                "tokens_used": str(tokens_used),
                "cached_tokens": str(cache_read_tokens),
                "cost_usd": f"{cost_to_float(cost_usd):.6f}",
                # Detailed token info for cost tracking
                "_model_id": model_id,
                "_input_tokens": input_tokens,
                "_output_tokens": output_tokens,
                "_cache_read_tokens": cache_read_tokens or 0,
                "_cache_creation_tokens": cache_creation_tokens or 0,
            }

        except APIStatusError as e:
            last_error = e
            if e.status_code in RETRYABLE_STATUS_CODES:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_SECONDS * (2**attempt)
                    logger.info("tools.analyze_pdf.retry",
                                claude_file_id=claude_file_id,
                                attempt=attempt + 1,
                                max_retries=MAX_RETRIES,
                                status_code=e.status_code,
                                delay_seconds=delay)
                    await asyncio.sleep(delay)
                    continue
            # Non-retryable error or max retries reached
            # Claude API failures are external service issues
            logger.info("tools.analyze_pdf.failed",
                        claude_file_id=claude_file_id,
                        error=str(e))
            raise

        except Exception as e:
            # External API failures, not internal bugs
            logger.info("tools.analyze_pdf.failed",
                        claude_file_id=claude_file_id,
                        error=str(e))
            raise

    # Should not reach here, but satisfy mypy
    if last_error:
        raise last_error
    raise RuntimeError("Unexpected: retry loop completed without result")


# Tool definition for Claude API (anthropic tools format)
ANALYZE_PDF_TOOL = {
    "name":
        "analyze_pdf",
    "description":
        """Analyze PDF using Claude's text extraction and vision.

Extracts text and analyzes visual elements (charts, tables, diagrams).
Pass claude_file_id from "Available files" (mime_type "application/pdf") and specific question.
Use pages parameter to limit scope: "1-5", "1,3,5", or "all".

Prompt caching makes repeated analysis 90% cheaper.
Cost: ~3,000-5,000 tokens per page.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "claude_file_id": {
                "type":
                    "string",
                "description": ("File ID where mime_type is 'application/pdf'. "
                                "Check 'Available files' for each file's "
                                "mime_type before selecting.")
            },
            "question": {
                "type":
                    "string",
                "description":
                    ("What to analyze or extract from the PDF. "
                     "Be specific: 'Summarize this document', "
                     "'Extract all tables', 'What are the conclusions?'")
            },
            "pages": {
                "type":
                    "string",
                "description": ("Page range: '1-5' (range), '3' (single), "
                                "'all' (default). Specific pages reduce cost.")
            }
        },
        "required": ["claude_file_id", "question"]
    }
}

# Unified tool configuration (no format_result - internal analysis tool)
from core.tools.base import ToolConfig  # pylint: disable=wrong-import-position

TOOL_CONFIG = ToolConfig(
    name="analyze_pdf",
    definition=ANALYZE_PDF_TOOL,
    executor=analyze_pdf,
    emoji="📄",
    needs_bot_session=False,
    format_result=None,  # No system message for analysis tools
    file_id_param="claude_file_id",
    allowed_mime_prefixes=["application/pdf"],  # Only PDF MIME type
)
