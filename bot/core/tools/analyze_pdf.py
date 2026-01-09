"""Analyze PDF tool using Claude PDF API with Files API.

This module implements the analyze_pdf tool for processing user-uploaded
PDF documents through Claude's multimodal capabilities. Uses Files API file IDs.

NO __init__.py - use direct import:
    from core.tools.analyze_pdf import analyze_pdf, ANALYZE_PDF_TOOL
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
        logger.info("tools.analyze_pdf.client_initialized")
    return _client


async def analyze_pdf(claude_file_id: str,
                      question: str,
                      pages: str = "all") -> Dict[str, str]:
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
    try:
        logger.info("tools.analyze_pdf.called",
                    claude_file_id=claude_file_id,
                    question_length=len(question),
                    pages=pages)

        client = get_client()

        # Build question with page range
        if pages != "all":
            full_question = f"{question}\n\nAnalyze pages: {pages}"
        else:
            full_question = question

        # Call Claude PDF API with prompt caching
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
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
                            "type": "ephemeral"
                        }  # Cache PDF content!
                    },
                    {
                        "type": "text",
                        "text": full_question
                    }
                ]
            }])

        analysis = response.content[0].text
        tokens_used = response.usage.input_tokens + response.usage.output_tokens
        cached_tokens = response.usage.cache_read_input_tokens

        logger.info("tools.analyze_pdf.success",
                    claude_file_id=claude_file_id,
                    tokens_used=tokens_used,
                    cached_tokens=cached_tokens,
                    cache_hit=cached_tokens > 0,
                    analysis_length=len(analysis))

        return {
            "analysis": analysis,
            "tokens_used": str(tokens_used),
            "cached_tokens": str(cached_tokens)
        }

    except Exception as e:
        logger.error("tools.analyze_pdf.failed",
                     claude_file_id=claude_file_id,
                     error=str(e),
                     exc_info=True)
        # Re-raise to let caller handle
        raise


# Tool definition for Claude API (anthropic tools format)
ANALYZE_PDF_TOOL = {
    "name":
        "analyze_pdf",
    "description":
        """Analyze a PDF document using Claude's vision and text extraction.

Use this when the user asks about PDF content, wants to extract information,
or needs to understand document structure. The tool processes both text and
visual elements (charts, diagrams, tables) using Claude's multimodal
capabilities. Each page is converted to both text and image for comprehensive
analysis.

It accepts page ranges to analyze specific sections for cost optimization.
For large documents, analyzing specific pages is much cheaper than processing
the entire document.

Returns extracted text and analysis. Does NOT support password-protected or
encrypted PDFs. Best for documents under 100 pages (larger documents may hit
200K context limits).

When to use: User asks about PDF content, wants to summarize a document,
needs to extract specific information, wants to analyze charts/tables in PDFs,
or asks questions about uploaded PDFs.

When NOT to use: For images (use analyze_image), for very large PDFs without
specifying pages (suggest user to specify page range first), for password-protected
PDFs (inform user it's not supported).

Token cost: Approximately 3,000-5,000 tokens per page depending on content
density. A 10-page PDF costs ~40,000 tokens. Use page ranges to reduce cost.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "claude_file_id": {
                "type":
                    "string",
                "description":
                    ("File ID from Files API (claude_file_id from "
                     "available files list in conversation)")
            },
            "question": {
                "type":
                    "string",
                "description":
                    ("What to analyze or extract from the PDF. "
                     "Be specific about what information is needed "
                     "(e.g., 'Summarize this document', "
                     "'Extract all tables from this PDF', "
                     "'What are the main conclusions?')")
            },
            "pages": {
                "type":
                    "string",
                "description":
                    ("Page range to analyze. Format: '1-5' for pages 1 through 5, "
                     "'3' for page 3 only, 'all' for entire document. "
                     "Default: 'all'. Using specific pages reduces token cost.")
            }
        },
        "required": ["claude_file_id", "question"]
    }
}
