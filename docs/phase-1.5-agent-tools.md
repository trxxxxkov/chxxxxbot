# Phase 1.5: LLM Agent Tools

**Status:** ✅ **COMPLETE** (2026-01-10)

**Purpose:** Add multimodal support (images, PDFs, documents) and tools framework (web search, web fetch, code execution) with Files API integration.

**Reference:** See [phase-1.4-claude-advanced-api.md](phase-1.4-claude-advanced-api.md) for all best practices and API patterns.

---

## Table of Contents

- [Overview](#overview)
- [Files API Integration](#files-api-integration)
- [Tools Architecture](#tools-architecture)
- [Multimodal Tools](#multimodal-tools)
- [Web Tools](#web-tools)
- [Code Execution](#code-execution)
- [Self-Critique Verification Subagent](#self-critique-verification-subagent)
- [System Prompt](#system-prompt)
- [Implementation Details](#implementation-details)
- [Related Documents](#related-documents)

---

## Overview

Phase 1.5 adds multimodal file handling and tools framework using Files API + Tool Runner pattern from Phase 1.4.

### Prerequisites

- ✅ Phase 1.3: Text conversations with streaming
- ✅ Phase 1.4: Best practices documented
- ✅ Database: `user_files` table (will be added)

### Key Decisions (from Phase 1.4)

1. **Always Files API** - all files uploaded to Claude Files API
2. **Tool Runner** - use SDK beta for all tools
3. **Selective processing** - files uploaded but NOT sent to Claude immediately
4. **Tools choose files** - Claude decides which files to process via tools

### Architecture Summary

```
User uploads file → Telegram → Bot
                              ↓
                   Download from Telegram
                              ↓
                   Upload to Files API → get claude_file_id
                              ↓
                   Save to user_files table
                              ↓
        Add metadata to system prompt: "Available files: photo.jpg, doc.pdf"

User asks question → Claude sees available files in system prompt
                              ↓
                   Claude calls tool: analyze_image(file_id, question)
                              ↓
                   Bot executes tool → sends file to Claude API
                              ↓
                   Claude analyzes → returns result
```

---

## Files API Integration

### user_files Table

```python
# bot/db/models/user_file.py

from sqlalchemy import Column, Integer, String, DateTime, BigInteger, Enum, JSON
from sqlalchemy.sql import func
from bot.db.models.base import Base
import enum

class FileType(enum.Enum):
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"
    GENERATED = "generated"

class FileSource(enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"

class UserFile(Base):
    """User-uploaded files stored in Files API."""

    __tablename__ = "user_files"

    id = Column(Integer, primary_key=True)
    message_id = Column(BigInteger, nullable=False)  # FK to messages

    # Telegram data
    telegram_file_id = Column(String, nullable=True)  # If from user upload
    telegram_file_unique_id = Column(String, nullable=True)

    # Claude Files API data
    claude_file_id = Column(String, nullable=False, unique=True)

    # Metadata
    filename = Column(String, nullable=False)
    file_type = Column(Enum(FileType), nullable=False)
    mime_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)  # bytes

    # Lifecycle
    uploaded_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False)  # uploaded_at + FILES_API_TTL_HOURS

    # Source
    source = Column(Enum(FileSource), nullable=False)  # 'user' or 'assistant'

    # Optional metadata (JSONB)
    metadata = Column(JSON, nullable=True)  # {width, height, page_count, generated_by_tool, ...}
```

### File Upload Handler

```python
# bot/telegram/handlers/files.py

from aiogram import Router, F
from aiogram.types import Message, PhotoSize, Document
from bot.core.files_api import upload_to_files_api
from bot.db.repositories.user_file_repository import UserFileRepository
from bot.config import FILES_API_TTL_HOURS
from datetime import datetime, timedelta
import structlog

router = Router()
logger = structlog.get_logger()

@router.message(F.photo)
async def handle_photo(
    message: Message,
    user_file_repo: UserFileRepository
):
    """Handle photo uploads with Files API integration."""

    # Get largest photo
    photo: PhotoSize = message.photo[-1]

    logger.info(
        "photo_received",
        user_id=message.from_user.id,
        file_id=photo.file_id,
        file_size=photo.file_size
    )

    # Check file size (Files API limit: 500MB, but Telegram photos < 10MB usually)
    if photo.file_size and photo.file_size > 500 * 1024 * 1024:
        await message.answer("File too large (max 500MB)")
        return

    try:
        # 1. Download from Telegram
        file = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file.file_path)

        # 2. Upload to Files API (BLOCKING - critical!)
        claude_file_id = await upload_to_files_api(
            file_bytes=file_bytes.read(),
            filename=f"photo_{photo.file_id[:8]}.jpg",
            mime_type="image/jpeg"
        )

        logger.info(
            "file_uploaded_to_claude",
            telegram_file_id=photo.file_id,
            claude_file_id=claude_file_id
        )

        # 3. Save to database
        await user_file_repo.create(
            message_id=message.message_id,
            telegram_file_id=photo.file_id,
            telegram_file_unique_id=photo.file_unique_id,
            claude_file_id=claude_file_id,
            filename=f"photo_{photo.file_id[:8]}.jpg",
            file_type=FileType.IMAGE,
            mime_type="image/jpeg",
            file_size=photo.file_size,
            source=FileSource.USER,
            expires_at=datetime.utcnow() + timedelta(hours=FILES_API_TTL_HOURS),
            metadata={"width": photo.width, "height": photo.height}
        )

        # 4. Create message with file mention
        await message_repo.create_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            role="user",
            content=f"User uploaded: photo_{photo.file_id[:8]}.jpg (image/jpeg, {format_size(photo.file_size)})",
            metadata={"file_id": claude_file_id}
        )

        # File ready for processing via tools
        await message.answer("Photo uploaded successfully. You can ask me questions about it!")

    except Exception as e:
        logger.error("file_upload_failed", error=str(e), exc_info=True)
        await message.answer("Failed to upload file. Please try again.")


@router.message(F.document)
async def handle_document(
    message: Message,
    user_file_repo: UserFileRepository
):
    """Handle document uploads (PDFs, Office, code files)."""

    document: Document = message.document

    logger.info(
        "document_received",
        user_id=message.from_user.id,
        filename=document.file_name,
        mime_type=document.mime_type,
        file_size=document.file_size
    )

    # Check file size
    if document.file_size > 500 * 1024 * 1024:
        await message.answer("File too large (max 500MB)")
        return

    # Determine file type
    if document.mime_type == "application/pdf":
        file_type = FileType.PDF
    elif document.mime_type.startswith("image/"):
        file_type = FileType.IMAGE
    else:
        file_type = FileType.DOCUMENT

    try:
        # 1. Download from Telegram
        file = await message.bot.get_file(document.file_id)
        file_bytes = await message.bot.download_file(file.file_path)

        # 2. Upload to Files API
        claude_file_id = await upload_to_files_api(
            file_bytes=file_bytes.read(),
            filename=document.file_name,
            mime_type=document.mime_type
        )

        # 3. Save to database
        await user_file_repo.create(
            message_id=message.message_id,
            telegram_file_id=document.file_id,
            telegram_file_unique_id=document.file_unique_id,
            claude_file_id=claude_file_id,
            filename=document.file_name,
            file_type=file_type,
            mime_type=document.mime_type,
            file_size=document.file_size,
            source=FileSource.USER,
            expires_at=datetime.utcnow() + timedelta(hours=FILES_API_TTL_HOURS),
            metadata={}
        )

        # 4. Create message mention
        await message_repo.create_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            role="user",
            content=f"User uploaded: {document.file_name} ({document.mime_type}, {format_size(document.file_size)})",
            metadata={"file_id": claude_file_id}
        )

        await message.answer(f"File '{document.file_name}' uploaded successfully!")

    except Exception as e:
        logger.error("document_upload_failed", error=str(e), exc_info=True)
        await message.answer("Failed to upload document. Please try again.")
```

### Files API Client

```python
# bot/core/files_api.py

import anthropic
from bot.config import ANTHROPIC_API_KEY
import structlog

logger = structlog.get_logger()
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

async def upload_to_files_api(
    file_bytes: bytes,
    filename: str,
    mime_type: str
) -> str:
    """Upload file to Claude Files API, return claude_file_id."""

    try:
        # Upload to Files API
        file_response = client.beta.files.upload(
            file=file_bytes,
            filename=filename
        )

        logger.info(
            "files_api_upload_success",
            claude_file_id=file_response.id,
            filename=filename,
            size=len(file_bytes)
        )

        return file_response.id

    except anthropic.APIError as e:
        logger.error(
            "files_api_upload_failed",
            error=str(e),
            status_code=getattr(e, 'status_code', None)
        )
        raise


async def delete_from_files_api(claude_file_id: str):
    """Delete file from Files API."""

    try:
        client.beta.files.delete(file_id=claude_file_id)
        logger.info("files_api_delete_success", claude_file_id=claude_file_id)
    except anthropic.APIError as e:
        logger.error("files_api_delete_failed", claude_file_id=claude_file_id, error=str(e))


async def cleanup_expired_files(user_file_repo):
    """Cron job: delete expired files from Files API and database."""

    expired_files = await user_file_repo.get_expired_files()

    for file in expired_files:
        try:
            # Delete from Files API
            await delete_from_files_api(file.claude_file_id)

            # Delete from database
            await user_file_repo.delete(file.id)

            logger.info(
                "expired_file_cleaned",
                file_id=file.id,
                claude_file_id=file.claude_file_id,
                filename=file.filename
            )
        except Exception as e:
            logger.error(
                "file_cleanup_failed",
                file_id=file.id,
                error=str(e)
            )
```

---

## Tools Architecture

### Tool Runner Pattern (from Phase 1.4)

All tools use SDK's `@beta_tool` decorator with Tool Runner:

```python
# bot/core/tools/__init__.py

from anthropic import beta_tool
from bot.core.tools.analyze_image import analyze_image
from bot.core.tools.analyze_pdf import analyze_pdf
from bot.core.tools.execute_python import execute_python

# Server-side tools (managed by Anthropic, no implementation needed)
SERVER_TOOLS = [
    {
        "type": "web_search_20250305",
        "name": "web_search"
        # Minimal config: no max_uses, no user_location, no domain filtering
        # Claude decides how many searches needed
        # Cost: $0.01 per search (tracked in usage.server_tool_use.web_search_requests)
    },
    {
        "type": "web_fetch_20250910",
        "name": "web_fetch"
        # No max_uses limit (users have token budget)
        # No citations (not showing to users)
        # No domain filtering (allow all public URLs)
        # Cost: FREE (only tokens)
    }
]

# Client-side tools (implemented by us)
CLIENT_TOOLS = [
    analyze_image,    # Analyze user-uploaded images
    analyze_pdf,      # Analyze user-uploaded PDFs
    execute_python    # Execute code via E2B/Modal
]

ALL_TOOLS = SERVER_TOOLS + CLIENT_TOOLS

# Total: 5 tools (2 server-side, 3 client-side)
```

### Tool Descriptions Template (from Phase 1.4)

Each tool must have detailed description (3-4+ sentences):

```python
"""<Tool purpose and capabilities>

Use this tool when <specific use cases>. The tool <how it works>.
It <what parameters do> and returns <output format>.

When to use: <specific scenarios>
When NOT to use: <limitations>

Limitations: <important caveats>
Token cost: <if applicable>

Args:
    param1: <detailed description>
    param2: <detailed description>

Returns:
    <format and structure of return value>
"""
```

---

## Multimodal Tools

### analyze_image Tool

```python
# bot/core/tools/analyze_image.py

from anthropic import beta_tool
import anthropic
import json
from bot.config import ANTHROPIC_API_KEY
import structlog

logger = structlog.get_logger()
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

@beta_tool
def analyze_image(claude_file_id: str, question: str) -> str:
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
    consume proportionally more tokens.

    Args:
        claude_file_id: File ID from available files list in conversation.
            This is the claude_file_id stored in database after Files API upload.
        question: What to analyze or extract from the image. Be specific about
            what information is needed (e.g., "What objects are visible?",
            "Extract all text from this screenshot", "What does this chart show?").

    Returns:
        JSON string with analysis results containing 'analysis' key with
        Claude's response about the image.
    """

    try:
        logger.info(
            "analyze_image_called",
            claude_file_id=claude_file_id,
            question=question
        )

        # Call Claude Vision API (Opus for best quality)
        response = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=8192,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "file",
                            "file_id": claude_file_id
                        }
                    },
                    {
                        "type": "text",
                        "text": question
                    }
                ]
            }]
        )

        analysis = response.content[0].text

        logger.info(
            "analyze_image_success",
            claude_file_id=claude_file_id,
            tokens_used=response.usage.input_tokens + response.usage.output_tokens
        )

        return json.dumps({
            "analysis": analysis,
            "tokens_used": response.usage.input_tokens + response.usage.output_tokens
        })

    except Exception as e:
        logger.error(
            "analyze_image_failed",
            claude_file_id=claude_file_id,
            error=str(e),
            exc_info=True
        )
        # Let Tool Runner handle error with is_error: true
        raise
```

**Note about analyze_image:** This tool is for user-uploaded images (Telegram → Files API). For images from URLs, Claude can use `web_fetch` if the image is embedded in a webpage.

---

### analyze_pdf Tool

**Important:** This tool is for **user-uploaded PDFs** (Telegram files → Files API). For PDFs from URLs (e.g., "Analyze https://arxiv.org/paper.pdf"), Claude uses the `web_fetch` server-side tool instead (no custom implementation needed).

```python
# bot/core/tools/analyze_pdf.py

from anthropic import beta_tool
import anthropic
import json
from bot.config import ANTHROPIC_API_KEY
import structlog

logger = structlog.get_logger()
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

@beta_tool
def analyze_pdf(claude_file_id: str, question: str, pages: str = "all") -> str:
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
    density. A 10-page PDF costs ~40,000 tokens. Use page ranges to reduce cost.

    Args:
        claude_file_id: File ID from available files list in conversation.
        question: What to analyze or extract from the PDF. Be specific.
        pages: Page range to analyze. Format: '1-5' for pages 1 through 5,
            '3' for page 3 only, 'all' for entire document (default).
            Using specific pages dramatically reduces token cost for large PDFs.

    Returns:
        JSON string with analysis results containing 'analysis' key with
        Claude's response and 'tokens_used' key with cost information.
    """

    try:
        logger.info(
            "analyze_pdf_called",
            claude_file_id=claude_file_id,
            question=question,
            pages=pages
        )

        # Call Claude PDF API with prompt caching (Opus for best quality)
        response = client.messages.create(
            model="claude-opus-4-5-20251101",
            max_tokens=16384,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "file",
                            "file_id": claude_file_id
                        },
                        "cache_control": {"type": "ephemeral"}  # Cache PDF content!
                    },
                    {
                        "type": "text",
                        "text": f"Question: {question}\nAnalyze pages: {pages}"
                    }
                ]
            }]
        )

        analysis = response.content[0].text

        logger.info(
            "analyze_pdf_success",
            claude_file_id=claude_file_id,
            tokens_used=response.usage.input_tokens + response.usage.output_tokens,
            cache_hit=response.usage.cache_read_input_tokens > 0
        )

        return json.dumps({
            "analysis": analysis,
            "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
            "cached_tokens": response.usage.cache_read_input_tokens
        })

    except Exception as e:
        logger.error(
            "analyze_pdf_failed",
            claude_file_id=claude_file_id,
            error=str(e),
            exc_info=True
        )
        raise
```

---

## Web Tools

### Web Search (Official Server-Side Tool)

**Decision: Use official `web_search_20250305` with minimal configuration**

**What it does:**
- Real-time web search with citations
- Server-side tool managed by Anthropic (no implementation needed)
- Returns search results: URLs, titles, snippets
- Always includes citations (automatically)

**Configuration:**

```python
# Already included in SERVER_TOOLS (see Tools Architecture section)
{
    "type": "web_search_20250305",
    "name": "web_search"
    # Minimal config: no max_uses, no user_location, no domain filtering
}
```

**Pricing:**
- **$0.01 per search** ($10 per 1,000 searches)
- Plus standard token costs for results
- Tracked in `usage.server_tool_use.web_search_requests`
- Must be accounted in user balance (Phase 2.1)

**Use cases:**
- User: "What's the latest news about AI?"
- User: "Find recent research on quantum computing"
- User: "Compare prices of iPhone models"

**Typical costs:**
- Simple search: 1 search ($0.01) + ~2K tokens
- Deep research: 2-3 searches ($0.02-0.03) + ~5-10K tokens
- Multi-topic comparison: 3-5 searches ($0.03-0.05) + ~10K tokens

**Why minimal configuration:**
- No max_uses: Claude decides optimal number
- No user_location: No localization needed
- No domain filtering: Allow all public sources

**Citations:**
- Always enabled (required)
- `cited_text`, `title`, `url` don't count as tokens (free!)
- Must be preserved in multi-turn conversations

**See Phase 1.4 documentation for full details.**

---

### Web Fetch (Official Server-Side Tool)

**Decision: Use official `web_fetch_20250910` instead of custom implementation**

**What it does:**
- Fetches full content from URLs (web pages + PDFs)
- Server-side tool managed by Anthropic (no implementation needed)
- Automatic PDF text extraction
- Built-in caching
- Free (only pay for tokens)

**Configuration:**

```python
# Already included in SERVER_TOOLS (see Tools Architecture section)
{
    "type": "web_fetch_20250910",
    "name": "web_fetch",
    # No max_uses limit (users have token budget)
    # No citations (not showing to users)
    # No domain filtering (allow all public URLs)
}
```

**Why official tool instead of custom:**
- ✅ Zero implementation code
- ✅ Automatic PDF extraction (no PyPDF2 needed)
- ✅ Built-in caching by Anthropic
- ✅ Built-in error handling
- ✅ Same cost (only tokens)
- ✅ Officially maintained

**Use cases:**
- User: "Analyze this article: https://example.com/article"
- User: "What's in this PDF? https://arxiv.org/paper.pdf"
- Combined with web_search: Claude finds URLs → fetches full content

**Typical token costs:**
- Average web page (10KB): ~2,500 tokens
- Large documentation (100KB): ~25,000 tokens
- Research paper PDF (500KB): ~125,000 tokens

**Limitations:**
- ❌ No JavaScript rendering (static HTML only)
- ✅ Can only fetch URLs from conversation context (security feature)

**See Phase 1.4 documentation for full details.**

---

## Code Execution (E2B) — IMPLEMENTED

**Decision:** Use E2B Code Interpreter for code execution.

**Why E2B was chosen:**
- ✅ Full internet access (HTTP requests, API calls)
- ✅ Pip install any package
- ✅ Sandboxed Python environment
- ✅ File system I/O (input files from Files API, output files to users)
- ✅ Reasonable pricing ($0.000036/second)
- ✅ Good SDK and documentation

**Why not Claude's built-in code execution:**
- ❌ No internet access (cannot make API calls, pip install packages)
- ❌ Limited to pre-installed libraries
- ❌ Not suitable for universal bot use cases

### execute_python Tool — IMPLEMENTED

```python
# bot/core/tools/execute_python.py

from anthropic import beta_tool
# from e2b import Sandbox  # To be decided
import json
import structlog

logger = structlog.get_logger()

@beta_tool
def execute_python(
    code: str,
    requirements: list[str] = None,
    timeout: int = 30
) -> str:
    """Execute Python code with internet access and arbitrary packages.

    Use this tool when the user wants to run Python code, analyze data with
    custom libraries, make HTTP requests, call external APIs, or perform
    computational tasks. This tool provides a sandboxed Python environment
    with full internet access and ability to install any pip package.

    Unlike Claude's built-in code execution, this tool can:
    - Install any pip package via requirements
    - Make HTTP requests to external APIs
    - Download data from the internet
    - Use custom libraries not available in Claude's environment

    When to use: User wants to run code with specific libraries, needs to
    access external APIs, wants to download and process data from the internet,
    or needs computational capabilities beyond what's available in other tools.

    When NOT to use: For simple calculations (Claude can do those directly),
    when user just wants to understand code (no execution needed), or when
    the task can be done with other tools (analyze_image, analyze_pdf, etc.).

    Security: Code runs in isolated sandbox with resource limits (CPU, memory, time).
    All executions are logged for security monitoring.

    Args:
        code: Python code to execute. Can be multi-line script.
        requirements: Optional list of pip packages to install before execution.
            Example: ["requests", "beautifulsoup4", "pandas"]
        timeout: Maximum execution time in seconds (default: 30, max: 300)

    Returns:
        JSON string with stdout, stderr, and return_code from execution.
    """

    # Full implementation in bot/core/tools/execute_python.py (800+ lines)
    # Key features:
    # - E2B Code Interpreter sandbox
    # - Pip package installation
    # - File I/O (upload inputs, download outputs)
    # - Timeout handling (default 3 min, max 1 hour)
    # - Sandbox reuse between calls (cached in Redis)
    # - Output file caching with preview generation
```

**Implementation Details (bot/core/tools/execute_python.py):**

- **Sandbox Management:** Lazy initialization with Redis caching for reuse
- **File Input:** Downloads from Files API → uploads to sandbox `/tmp/inputs/`
- **File Output:** Scans `/tmp/` for new files → uploads to Files API → sends to user
- **Cost:** $0.000036/second (~$0.13/hour)
- **Timeout:** Default 180s, max 3600s
- **Packages:** Any pip package can be installed on demand

---

## Self-Critique Verification Subagent

**Status:** ✅ IMPLEMENTED (2026-01-28)

The `self_critique` tool launches an independent verification session using Claude Opus 4.5 with an adversarial mindset to find flaws in responses.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Main Claude Session                             │
│  (User's model: Sonnet/Opus/Haiku)                                      │
├─────────────────────────────────────────────────────────────────────────┤
│  User request → Claude generates response → [Trigger condition?]        │
│                                                                          │
│  Triggers:                                                               │
│  1. User dissatisfaction ("переделай", "wrong", "redo")                 │
│  2. Verification request ("проверь", "verify", "make sure")             │
│  3. Complex task (Claude's judgment: long reasoning, 50+ lines code)    │
│                              ↓                                           │
│                    ┌─────────────────┐                                  │
│                    │  self_critique  │                                  │
│                    └────────┬────────┘                                  │
└─────────────────────────────┼────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     Self-Critique Subagent                               │
│  (ALWAYS Claude Opus 4.5, ADVERSARIAL mindset)                          │
├─────────────────────────────────────────────────────────────────────────┤
│  Available Tools (parallel execution):                                  │
│  ├── execute_python  - Run tests, debug, visualize                     │
│  ├── preview_file    - Examine any file type                           │
│  ├── analyze_image   - Vision analysis                                  │
│  └── analyze_pdf     - PDF analysis                                     │
│                                                                          │
│  Workflow:                                                               │
│  1. Understand user's original request                                  │
│  2. Examine content/files (use tools in parallel)                       │
│  3. Write tests / verification code                                     │
│  4. Compare output vs. user request                                     │
│  5. Return structured verdict                                           │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Output: {"verdict": "PASS|FAIL|NEEDS_IMPROVEMENT",                     │
│           "alignment_score": 0-100, "issues": [...],                    │
│           "recommendations": [...], "cost_usd": 0.05}                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Features

| Feature | Description |
|---------|-------------|
| **Always Opus** | Uses Claude Opus 4.5 regardless of user's model |
| **Adversarial mindset** | Actively searches for flaws, not validation |
| **Full tool access** | execute_python, preview_file, analyze_image, analyze_pdf |
| **Extended thinking** | 10K budget tokens for deep analysis |
| **Parallel execution** | asyncio.gather() for multiple tools |
| **Balance check** | Requires >= $0.50 to start |
| **Dynamic pricing** | User pays actual Opus tokens + tool costs |

### Cost Estimates (Opus: $15/$75 per 1M tokens)

| Complexity | Input | Output | Tools | Total |
|------------|-------|--------|-------|-------|
| Simple (no tools) | ~2K | ~1K | $0 | ~$0.03 |
| With code execution | ~3K | ~2K | ~$0.01 | ~$0.07 |
| Thorough verification | ~5K | ~3K | ~$0.03 | ~$0.12 |

### Usage Triggers

1. **User dissatisfaction**: "переделай", "не то", "wrong", "redo", "try again"
2. **Verification request**: "проверь", "убедись", "verify", "make sure", "carefully"
3. **Complex tasks**: Long reasoning chains, 50+ lines of code, uncertain correctness

### Implementation Files

- `bot/core/tools/self_critique.py` - Main implementation (~1000 lines)
- `bot/prompts/system_prompt.py` - Usage instructions in `<self_critique_usage>` section
- `bot/tests/core/tools/test_self_critique.py` - 46 comprehensive tests

---

## System Prompt

Dynamic system prompt with available files and tool selection guidance:

```python
# bot/core/claude/prompts.py

from bot.db.repositories.user_file_repository import UserFileRepository

GLOBAL_SYSTEM_PROMPT = """You are a helpful AI assistant integrated into a Telegram bot.
You can analyze images, PDFs, search the web, fetch URLs, and execute Python code.
Be concise but thorough. Format responses for Telegram (Markdown supported)."""

TOOL_SELECTION_PROMPT = """
Answer the user's request using relevant tools (if they are available).
Before calling a tool, do some analysis. First, think about which of the
provided tools is the relevant tool to answer the user's request. Second,
go through each of the required parameters of the relevant tool and determine
if the user has directly provided or given enough information to infer a value.
When deciding if the parameter can be inferred, carefully consider all the
context to see if it supports a specific value. If all of the required
parameters are present or can be reasonably inferred, proceed with the tool call.
BUT, if one of the values for a required parameter is missing, DO NOT invoke
the function (not even with fillers for the missing params) and instead,
ask the user to provide the missing parameters. DO NOT ask for more information
on optional parameters if it is not provided.
"""

async def generate_system_prompt(
    thread_id: int,
    user_file_repo: UserFileRepository
) -> str:
    """Generate dynamic system prompt with available files."""

    # Get files for this thread
    files = await user_file_repo.get_by_thread_id(thread_id)

    # Generate files list
    if files:
        files_list = "\n".join([
            f"- {f.filename} ({f.file_type.value}, {format_size(f.file_size)}, "
            f"uploaded {format_time_ago(f.uploaded_at)}, claude_file_id: {f.claude_file_id})"
            for f in files
        ])
        files_section = f"\nAvailable files in this conversation:\n{files_list}\n"
    else:
        files_section = ""

    return f"""{GLOBAL_SYSTEM_PROMPT}
{files_section}
{TOOL_SELECTION_PROMPT}"""

def format_size(bytes: int) -> str:
    """Format file size."""
    for unit in ['B', 'KB', 'MB']:
        if bytes < 1024:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024
    return f"{bytes:.1f} GB"

def format_time_ago(dt: datetime) -> str:
    """Format time ago."""
    delta = datetime.utcnow() - dt
    if delta.seconds < 60:
        return "just now"
    elif delta.seconds < 3600:
        return f"{delta.seconds // 60} min ago"
    elif delta.seconds < 86400:
        return f"{delta.seconds // 3600} hours ago"
    else:
        return f"{delta.days} days ago"
```

---

## Implementation Details

### Claude Handler with Tool Runner

```python
# bot/telegram/handlers/claude.py

from aiogram import Router, F
from aiogram.types import Message
from anthropic import Anthropic, beta_tool
from bot.core.tools import ALL_TOOLS
from bot.core.claude.prompts import generate_system_prompt
from bot.db.repositories import MessageRepository, UserFileRepository
import structlog

router = Router()
logger = structlog.get_logger()
client = Anthropic()

@router.message(F.text)
async def handle_message(
    message: Message,
    message_repo: MessageRepository,
    user_file_repo: UserFileRepository
):
    """Handle user messages with tool runner."""

    try:
        # Get thread for this chat
        thread = await get_or_create_thread(message.chat.id)

        # Generate system prompt with available files
        system_prompt = await generate_system_prompt(thread.id, user_file_repo)

        # Get conversation history
        history = await get_conversation_history(thread.id, message_repo)

        # Add current message
        history.append({
            "role": "user",
            "content": message.text
        })

        # Save user message
        await message_repo.create_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            role="user",
            content=message.text
        )

        # Use tool runner with streaming
        runner = client.beta.messages.tool_runner(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=system_prompt,
            tools=ALL_TOOLS,
            messages=history,
            stream=True
        )

        # Stream responses to Telegram
        telegram_message = None
        accumulated_text = ""

        for message_stream in runner:
            for event in message_stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        accumulated_text += event.delta.text

                        # Update Telegram message every 20 chars
                        if len(accumulated_text) % 20 == 0:
                            if telegram_message:
                                telegram_message = await telegram_message.edit_text(accumulated_text)
                            else:
                                telegram_message = await message.answer(accumulated_text)

            # Final message update
            final_message = message_stream.get_final_message()
            if telegram_message:
                await telegram_message.edit_text(final_message.content[0].text)
            else:
                telegram_message = await message.answer(final_message.content[0].text)

        # Save assistant response
        final_response = runner.until_done()
        await message_repo.create_message(
            chat_id=message.chat.id,
            message_id=telegram_message.message_id,
            role="assistant",
            content=final_response.content[0].text,
            tokens_input=final_response.usage.input_tokens,
            tokens_output=final_response.usage.output_tokens
        )

    except Exception as e:
        logger.error("message_handler_failed", error=str(e), exc_info=True)
        await message.answer("Sorry, I encountered an error. Please try again.")
```

### Configuration

```python
# bot/config.py

# Files API settings
FILES_API_TTL_HOURS = get_env("FILES_API_TTL_HOURS", 24)

# Tool settings
TOOL_RUNNER_BETA = "advanced-tool-use-2025-11-20"

# Model settings
DEFAULT_MODEL = "claude-sonnet-4-5"
MAX_TOKENS_DEFAULT = 4096

# Rate limits (Phase 2.1)
# MAX_FILES_PER_THREAD = 20
```

---

## Implementation Plan

**Status:** 🚧 **IN PROGRESS** (started 2026-01-09)

**Decisions:**
- ✅ E2B for code execution (internet access, pip install support)
- ✅ Extended Thinking ENABLED (requires thinking_blocks in DB)
- ✅ Interleaved Thinking ENABLED (already done in Phase 1.4)
- ✅ Testing strategy: parallel with development
- ✅ Implementation order: Variant C (tools individually, independent first)

**Order of implementation:**
1. Files API → 2. analyze_image → 3. analyze_pdf → 4. Web tools → 5. Code execution → 6. Integration

---

### ✅ Stage 1: Database & Files API (Foundation) - COMPLETE
**Goal:** Enable file uploads and storage in Files API

- [x] Database migration (Alembic)
  - [x] Create `user_files` table
  - [x] Add `thinking_blocks` column to `messages` (for Extended Thinking)
  - [x] Add cache tracking columns (`cache_creation_input_tokens`, `cache_read_input_tokens`, `thinking_tokens`)
- [x] Files API client (`bot/core/files_api.py`)
  - [x] upload_to_files_api() function
  - [x] delete_from_files_api() function
  - [x] cleanup_expired_files() cron job
  - [x] Beta header: `files-api-2025-04-14`
  - [x] Lazy client initialization with secret reading
- [x] UserFileRepository (`bot/db/repositories/user_file_repository.py`)
  - [x] CRUD operations
  - [x] get_by_thread_id() for system prompt
  - [x] get_expired_files() for cleanup
  - [x] Additional queries (by_file_type, recent_files, total_size)
- [x] File upload handlers (`bot/telegram/handlers/files.py`)
  - [x] Photos handler (F.photo)
  - [x] Documents handler (F.document)
  - [x] File type detection (IMAGE, PDF, DOCUMENT)
  - [x] Save to DB + create message mention
  - [x] User confirmation messages
- [x] Configuration
  - [x] FILES_API_TTL_HOURS in config.py
  - [x] Router registration in loader.py
- [ ] Tests for Stage 1 (deferred to later)

**Result:** Users can upload files, they're saved to Files API and DB. ✅

**Note:** Fixed SQLAlchemy reserved name conflict (`metadata` → `file_metadata` in model, `metadata` in DB column).

---

### Stage 2: analyze_image Tool
**Goal:** Claude can analyze uploaded images

- [ ] Tool implementation (`bot/core/tools/analyze_image.py`)
  - [ ] @beta_tool decorator
  - [ ] Detailed description (3-4+ sentences, limitations!)
  - [ ] Vision API call with file_id
  - [ ] Error handling
- [ ] Tools registry (`bot/core/tools/__init__.py`)
  - [ ] Import analyze_image
  - [ ] CLIENT_TOOLS list
- [ ] Tests for Stage 2
  - [ ] Unit test: analyze_image tool
  - [ ] Integration test: upload image + analyze

**Result:** Claude can analyze uploaded images via tool.

---

### Stage 3: analyze_pdf Tool
**Goal:** Claude can analyze uploaded PDFs

- [ ] Tool implementation (`bot/core/tools/analyze_pdf.py`)
  - [ ] @beta_tool decorator
  - [ ] Detailed description
  - [ ] PDF API call with cache_control
  - [ ] Page range support (optional parameter)
  - [ ] Error handling
- [ ] Update tools registry
  - [ ] Add analyze_pdf to CLIENT_TOOLS
- [ ] Tests for Stage 3
  - [ ] Unit test: analyze_pdf tool
  - [ ] Integration test: upload PDF + analyze
  - [ ] Test cache hit rate

**Result:** Claude can analyze uploaded PDFs with prompt caching.

---

### Stage 4: Web Tools (Server-side)
**Goal:** Claude can search web and fetch URLs

- [ ] Update tools registry
  - [ ] Add web_search to SERVER_TOOLS
  - [ ] Add web_fetch to SERVER_TOOLS
  - [ ] Beta headers: `web-search-2025-03-05`, `web-fetch-2025-09-10`
- [ ] Cost tracking preparation
  - [ ] Track `usage.server_tool_use.web_search_requests` (for Phase 2.1)
- [ ] Tests for Stage 4
  - [ ] Integration test: web_search
  - [ ] Integration test: web_fetch
  - [ ] Test web_search + web_fetch combination

**Result:** Claude can search internet and fetch content from URLs.

---

### Stage 5: execute_python Tool (E2B) ✅ COMPLETE
**Status:** Complete (2026-01-09)
**Goal:** Claude can execute Python code with internet access

- [x] E2B integration
  - [x] Research E2B SDK and API
  - [x] Add e2b_api_key.txt to secrets/
  - [x] Install e2b-code-interpreter>=1.0.0 in Dockerfile
- [x] Tool implementation (`bot/core/tools/execute_python.py`)
  - [x] execute_python(code, requirements, timeout=180.0)
  - [x] E2B Sandbox integration (lazy API key loading)
  - [x] Pip install requirements support
  - [x] Timeout parameter (default 180s, max 3600s)
  - [x] Stdout/stderr capture via callbacks
  - [x] Error handling and logging
  - [x] Results serialization (matplotlib plots)
- [x] Update tools registry
  - [x] Add EXECUTE_PYTHON_TOOL to TOOL_DEFINITIONS
  - [x] Add execute_python to TOOL_EXECUTORS
- [x] Tests for Stage 5
  - [x] 10 unit tests (test_execute_python.py)
  - [x] Tool definition validation
  - [x] Integration via registry (test_registry.py)

**Result:** Claude can execute Python code with full internet access and pip.

---

### Stage 6: File Generation & Download (execute_python File I/O) ✅ COMPLETE
**Status:** Complete (2026-01-09)
**Goal:** Universal file I/O for execute_python tool - Claude can generate and return files to users

- [x] Files API enhancements
  - [x] Add download_from_files_api(file_id) function
  - [x] Uses client.beta.files.retrieve_content()
- [x] execute_python tool enhancements
  - [x] Add file_inputs parameter: `[{file_id, name}]`
  - [x] Download from Files API → upload to /tmp/inputs/ in sandbox
  - [x] Scan /tmp/ for output files (excluding /tmp/inputs/)
  - [x] Download output files from sandbox
  - [x] Return `_file_contents` with raw bytes + metadata
  - [x] Comprehensive tool description (ENVIRONMENT, INPUT FILES, OUTPUT FILES, WORKFLOW EXAMPLE)
- [x] System prompt updates (config.py)
  - [x] Add "Working with Files" section in GLOBAL_SYSTEM_PROMPT
  - [x] Explain input/output file workflow
  - [x] Emphasize execute_python as ONLY way to return files to users
- [x] Claude handler updates (claude.py)
  - [x] Extend _handle_with_tools() signature (session, user_file_repo, chat_id, user_id)
  - [x] Process _file_contents after tool execution
  - [x] For each generated file:
    - [x] Upload to Files API
    - [x] Save to DB (source=ASSISTANT, message_id, expires_at)
    - [x] Send to Telegram user (send_photo for images, send_document otherwise)
    - [x] Add delivery confirmation to tool result feedback
  - [x] Generated files appear in "Available files" for future operations
- [x] Tests for Stage 6
  - [x] All 74 Phase 1.5 tests passing
  - [x] files_api, execute_python, tools, helpers, user_file_repository

**Workflow:**
1. User: "Convert data.csv to PDF report with chart"
2. Claude calls execute_python with file_inputs=[{file_id, name="data.csv"}]
3. Bot downloads data.csv from Files API → uploads to /tmp/inputs/
4. Code executes: reads /tmp/inputs/data.csv, generates /tmp/report.pdf and /tmp/chart.png
5. Bot scans /tmp/, downloads new files
6. Bot uploads to Files API → saves to DB → sends to Telegram → confirms delivery
7. Files appear in "Available files", Claude can reference: "I created report.pdf..."

**Result:** Claude can generate and return arbitrary files to users (PDF, PNG, CSV, XLSX, etc.) via execute_python.

---

### Stage 7: Testing & Documentation
**Goal:** Ensure everything works and is documented

- [ ] Comprehensive testing
  - [ ] All unit tests passing
  - [ ] All integration tests passing
  - [ ] Manual testing of each tool
  - [ ] Manual testing of tool combinations
  - [ ] Error scenarios
- [ ] Documentation
  - [ ] Update CLAUDE.md (Phase 1.5 complete)
  - [ ] Update phase-1.5-multimodal-tools.md (status)
  - [ ] Usage examples for each tool
  - [ ] Troubleshooting guide
  - [ ] E2B integration notes
- [ ] Performance review
  - [ ] Latency measurements
  - [ ] Token usage analysis
  - [ ] Cost calculations

**Result:** Phase 1.5 complete, tested, and documented.

---

## Related Documents

- **[phase-1.4-claude-advanced-api.md](phase-1.4-claude-advanced-api.md)** - ⚠️ **REQUIRED READING** - All best practices and API patterns
- **[phase-1.3-claude-core.md](phase-1.3-claude-core.md)** - Core implementation foundation
- **[phase-1.6-rag.md](phase-1.6-rag.md)** - Next phase: Vector search and search_user_files tool
- **[phase-1.2-database.md](phase-1.2-database.md)** - Database architecture
- **[CLAUDE.md](../CLAUDE.md)** - Project overview

---

## Summary

Phase 1.5 implements multimodal support and tools using:

**Files API** - Universal file storage:
- All files → Files API (images, PDFs, documents)
- Eager upload, selective processing
- 24-hour lifecycle, automatic cleanup

**Unified Tool Architecture** - ToolConfig pattern:
- Each tool module exports TOOL_CONFIG with metadata
- Registry consolidates all tools in single TOOLS dict
- Streaming support with tool execution loop

**Tools** - 11 total:
- `analyze_image` (custom, vision) - Paid (tokens)
- `analyze_pdf` (custom, PDF support) - Paid (tokens)
- `transcribe_audio` (custom, Whisper API) - Paid ($0.006/min)
- `generate_image` (custom, Gemini) - Paid ($0.134-0.240/image)
- `render_latex` (custom, local pdflatex) - Free
- `execute_python` (custom, E2B) - Paid ($0.000036/sec)
- `preview_file` (custom, vision for images/PDF) - Free/Paid
- `deliver_file` (custom, file delivery) - Free
- `web_search` (server-side, Anthropic) - Paid ($0.01/search)
- `web_fetch` (server-side, Anthropic) - Free (tokens only)
- `self_critique` (custom, verification subagent) - Paid (Opus tokens + tools)

**Best Practices** (from Phase 1.4):
- Detailed tool descriptions (3-4+ sentences)
- input_examples for complex tools
- Chain of thought prompting
- Default parallel tool behavior
- Pass errors to Claude

**Status:** ✅ COMPLETE (2026-01-10)
