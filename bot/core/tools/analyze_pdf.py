"""Analyze PDF tool using Claude PDF API with Files API.

This module implements the analyze_pdf tool for processing user-uploaded
PDF documents through Claude's multimodal capabilities. Uses Files API file IDs.

NO __init__.py - use direct import:
    from core.tools.analyze_pdf import analyze_pdf, ANALYZE_PDF_TOOL
"""

from typing import Dict

from core.clients import get_anthropic_client
from core.pricing import calculate_claude_cost, cost_to_float
from utils.structured_logging import get_logger

logger = get_logger(__name__)


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

        # Use centralized client factory with Files API beta header
        client = get_anthropic_client(use_files_api=True)
        model_id = "claude-sonnet-4-5-20250929"

        # Build question with page range
        if pages != "all":
            full_question = f"{question}\n\nAnalyze pages: {pages}"
        else:
            full_question = question

        # Call Claude PDF API with prompt caching
        response = client.messages.create(
            model=model_id,
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
            "cost_usd": f"{cost_to_float(cost_usd):.6f}"
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
or needs to understand document structure. The tool uses Claude Sonnet 4.5's
multimodal capabilities to process both text and visual elements (charts, diagrams,
tables). Each page is converted to both text and image for comprehensive analysis.

<verification_use_case>
CRITICAL: This tool is essential for verifying PDF outputs from execute_python.
When you generate PDFs (reports, converted documents, data exports), you MUST use
this tool to verify the output is correct before considering the task complete. This
catches issues like corrupted files, encoding problems (Cyrillic/UTF-8), missing
content, wrong formatting, or incomplete conversions that file size checks cannot detect.

Example: After converting presentation.pptx to PDF, call analyze_pdf to verify all
slides are present, text is readable (not garbled), images are included, and formatting
is preserved. A file size check alone would miss these quality issues.
</verification_use_case>

<page_ranges_optimization>
Accepts page ranges to analyze specific sections for cost optimization. For large
documents, analyzing specific pages is much cheaper than processing the entire document.
This is important because it allows you to focus on relevant sections and reduce token costs.

Syntax: "1-5" (pages 1 through 5), "1,3,5" (specific pages), "all" (entire document)
</page_ranges_optimization>

<when_to_use>
Use when:
- User asks about PDF content or document structure
- Summarizing documents or extracting specific information
- Analyzing charts, tables, or diagrams within PDFs
- Verifying generated PDFs from execute_python (quality check)
- Understanding PDF content before processing
- Answering questions about uploaded PDFs

Note: This tool uses prompt caching for PDF content, making repeated analysis
of the same document very cost-effective (90% cheaper on cache hits).
</when_to_use>

<when_not_to_use>
Do NOT use for:
- Image files (use analyze_image instead for photos, screenshots)
- Very large PDFs without page range (suggest user specify pages first)
- Password-protected or encrypted PDFs (not supported, inform user)
- When user explicitly asks not to analyze document
</when_not_to_use>

<limitations>
- Does NOT support password-protected or encrypted PDFs
- Best for documents under 100 pages (larger may hit 200K context limits)
- No editing capabilities (analysis only)
</limitations>

Token cost: ~3,000-5,000 tokens per page depending on content density.
A 10-page PDF costs ~40,000 tokens. Use page ranges to reduce cost.
Prompt caching reduces repeated analysis cost by 90%.""",
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
                "description": ("What to analyze or extract from the PDF. "
                                "Be specific about what information is needed "
                                "(e.g., 'Summarize this document', "
                                "'Extract all tables from this PDF', "
                                "'What are the main conclusions?')")
            },
            "pages": {
                "type":
                    "string",
                "description": (
                    "Page range to analyze. Format: '1-5' for pages 1 through 5, "
                    "'3' for page 3 only, 'all' for entire document. "
                    "Default: 'all'. Using specific pages reduces token cost.")
            }
        },
        "required": ["claude_file_id", "question"]
    }
}
