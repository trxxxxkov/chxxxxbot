# Claude Integration: Phase 1.4 (Advanced API Features)

Review Claude API documentation, extract best practices and advanced features, implement improvements to Phase 1.3.

**Status:** ✅ **COMPLETE** (2026-01-09)

---

## Overview

Phase 1.4 focuses on studying official Claude API documentation and implementing advanced features and best practices discovered during the review.

### Process

1. **User provides documentation link** (e.g., https://docs.anthropic.com/en/docs/...)
2. **Read and analyze the page** together
3. **Discuss what to adopt** for our project
4. **Document decision** in this file with link to page
5. **Note implementation details** - what specifically to implement
6. **Later: implement** - during implementation, revisit each page and write code

### Documentation Structure

For each reviewed page, we'll add:
- Link to documentation page
- Date reviewed
- Key insights from the page
- What we decided to adopt (specific techniques, patterns)
- Implementation notes (which files to change, what to add)
- What we decided to skip (and why)

---

## Documentation Pages Reviewed

### Models Overview

**Link:** https://platform.claude.com/docs/en/about-claude/models/overview
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Support 3 Claude 4.5 models**: Sonnet, Haiku, Opus (via `/model` command)
- **Create model registry** with characteristics: model_id, display_name, provider, context_window, max_output, pricing, capabilities
- **Use explicit model IDs** with snapshot dates (already done in 1.3: `claude-sonnet-4-5-20250929`)
- **Architecture for multi-provider**: Registry must support adding OpenAI, Google models later

**Skip:**
- 1M context window - 200K sufficient
- AWS Bedrock/GCP Vertex - Anthropic API only
- Legacy models - 4.5 family only

---

### What's new in Claude 4.5

**Link:** https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-5
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Extended Thinking**: Always enable for ALL models (details in separate Extended Thinking page)
- **Interleaved Thinking**: Enable beta header `interleaved-thinking-2025-05-14`
- **Effort parameter**: Always `"high"` for Opus 4.5 (beta header: `effort-2025-11-24`)
- **Stop reasons**: Add handling for `model_context_window_exceeded` and `refusal`
- **Model registry capabilities**: Add flags `supports_extended_thinking`, `supports_interleaved_thinking`, `supports_effort_parameter`, `supports_context_awareness`
- **System prompt**: Update for Claude 4 communication style (explicit instructions, concise responses)

**Relationship to other features:**
- Context Awareness (automatic) → see Context Windows page
- Extended Thinking details → see Extended Thinking page
- Prompt caching affected by thinking parameters → see Prompt Caching page

**Skip:**
- Computer use - not for Telegram bot
- Tool-related features - Phase 1.5
- Thinking block preservation - automatic

---

### Pricing

**Link:** https://platform.claude.com/docs/en/about-claude/pricing
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Prompt Caching** (CRITICAL): 10x cost reduction on cache reads (0.1x multiplier)
  - Use 5-minute cache (1.25x write, 0.1x read) for system prompt
  - Add cache pricing to model registry: `pricing_cache_write_5m`, `pricing_cache_write_1h`, `pricing_cache_read`
  - Track cache tokens separately in Message model: `cache_creation_input_tokens`, `cache_read_input_tokens`
  - Details → see Prompt Caching page

**Relationship to other features:**
- Model registry (from Models Overview) extended with cache pricing
- Cost tracking affects payment system (Phase 2.1)

**Skip:**
- Batch API - not for real-time bot
- Long context pricing - using 200K only
- Tool-specific pricing - Phase 1.5

---

### Features Overview

**Link:** https://platform.claude.com/docs/en/build-with-claude/overview
**Date reviewed:** 2026-01-08

**Note:** Roadmap page with links to all features. Topics marked for detailed review:

**High priority for Phase 1.4:**
- Token counting, Structured outputs, Citations, Search results, PDF support, Files API

**Phase 1.5 (Tools):**
- Tool use overview, Bash, Code execution, Memory, Web fetch/search, MCP connector

**Already covered or skipped:**
- ✅ Prompt caching, Extended thinking, Context editing, Effort
- ❌ 1M context, Batch processing, Computer use

---

### Context Windows

**Link:** https://platform.claude.com/docs/en/build-with-claude/context-windows
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Context Awareness**: Automatic (no implementation) - model receives token budget updates
  - Optionally display remaining context in UI
- **Extended Thinking**: Pass full conversation history with thinking blocks - API auto-strips previous thinking
  - Thinking tokens not billed twice, not counted in subsequent turns
- **Token Counting API**: Use before sending large messages to avoid overflow

**CRITICAL for Phase 1.5 (Tool Use + Extended Thinking):**
- Thinking block MUST be included with tool_result (cryptographic signature!)
- Never modify thinking blocks → API error
- After tool cycle: can drop or let API auto-strip

**Relationship to other features:**
- Extended Thinking details → see Extended Thinking page
- Prompt caching affected by thinking blocks → see Prompt Caching page

**Skip:**
- 1M context window - using 200K
- Manual thinking block stripping - automatic

---

### Claude 4 Best Practices

**Link:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-4-best-practices
**Date reviewed:** 2026-01-08

**Our decisions:**
- **System prompt for Claude 4**: Rewrite with explicit instructions, context/motivation, model identity, communication style
- **Thinking vocabulary**: Avoid "think" when extended thinking disabled (Opus 4.5 sensitive) - use "consider", "evaluate"
- **Model identity**: Include in system prompt (model name + exact string)
- **Tool patterns (Phase 1.5)**: Proactive vs conservative steering, parallel tool calling, avoid aggressive "MUST" language

**Key prompt engineering patterns:**
- Be explicit and direct ("Make changes" not "Can you suggest")
- Add context/motivation (explain WHY)
- Claude 4.5 more concise - expect less verbose summaries

**Skip:**
- Agentic coding/frontend/research patterns - not for Telegram bot

---

### Prompt Caching (Detailed)

**Link:** https://platform.claude.com/docs/en/build-with-claude/prompt-caching
**Date reviewed:** 2026-01-08

**Our decisions:**
- **System prompt caching**: 5-minute TTL with syntax `{"type": "ephemeral"}`
  - Minimum 1024 tokens for Sonnet 4.5 (ensure system prompt ≥ this)
  - Single breakpoint at end of system prompt (simplest strategy)
  - 10x cost reduction on reads ($0.30 vs $3 for Sonnet 4.5)
- **Usage tracking**: Log `cache_creation_input_tokens`, `cache_read_input_tokens`
  - IMPORTANT: `input_tokens` = only tokens AFTER breakpoint, not total
  - Total = cache_read + cache_creation + input_tokens
  - Display cache hit rate in monitoring
- **Cache-aware pricing**: Use 0.1x for reads, 1.25x for 5m writes in cost calc

**Technical details (for implementation):**
- Cache hierarchy: `tools` → `system` → `messages`
- 20-block automatic lookback (multiple breakpoints only if >20 blocks)
- Breakpoints are FREE (only pay for actual cache operations)

**Cache invalidation triggers:**
- Thinking parameters change → invalidates messages cache
- Model change → invalidates entire cache
- Tool definitions, web search, citations changes → see docs for details

**Relationship to other features:**
- Thinking blocks automatically cached (not explicitly marked) → see Context Windows
- Thinking parameter changes affect cache → see What's New in 4.5
- Pricing multipliers defined in Pricing page

**Skip:**
- 1-hour cache, multiple breakpoints, conversation caching, tool caching - defer to later

---

### Context Editing

**Link:** https://platform.claude.com/docs/en/build-with-claude/context-editing
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Thinking block clearing**: Use `clear_thinking_20251015` with `keep: "all"` for max cache hits
  - Beta header: `context-management-2025-06-27`
  - Default behavior (when not configured): keeps only last turn thinking
  - We want all thinking → better cache performance
- **Tool result clearing** (Phase 1.5): Consider `clear_tool_uses_20250919` for long tool sessions
  - Trigger at reasonable threshold (e.g., 50K tokens)
  - Keep recent N tool uses, exclude important tools
  - Note: Breaks prompt cache when clearing occurs

**Technical details (for implementation):**
- Server-side (API): Two strategies can be combined
  - `clear_thinking_20251015` MUST be first in edits array
  - Applied server-side before prompt reaches Claude
  - Client keeps full unmodified history
- Token counting API supports context_management parameter (preview token savings)
- Response includes `context_management.applied_edits` with cleared counts

**Relationship to other features:**
- Thinking block clearing + prompt caching → keep "all" for cache hits (see Prompt Caching)
- Extended thinking required for thinking block clearing (see Extended Thinking)
- Tool result clearing for Phase 1.5 (see phase-1.5-multimodal-tools.md)
- Works with Memory tool (Phase 1.5) - Claude saves to memory before clearing

**Skip:**
- Client-side compaction (SDK feature, we have custom client)
- Advanced tool clearing configuration (defer to Phase 1.5)

---

### Extended Thinking

**Link:** https://platform.claude.com/docs/en/build-with-claude/extended-thinking
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Always enable**: `thinking: {"type": "enabled", "budget_tokens": 10000}` for all requests
  - Start with 10K budget, adjust based on task complexity
  - Models: Sonnet 4.5, Haiku 4.5, Opus 4.5 all support
- **Interleaved thinking**: Enable with beta header `interleaved-thinking-2025-05-14` (already decided)
- **Streaming**: Handle `thinking_delta` events when streaming responses
- **Tool use**: Preserve complete unmodified thinking blocks when posting tool_result (CRITICAL)
  - Include thinking block from last assistant turn with tool results
  - Never modify thinking blocks (cryptographic signature!)

**Technical details (for implementation):**
- **API syntax**: Add `thinking` object to request
- **Summarized thinking**: Claude 4 returns summary (billed for full tokens, not summary)
- **Budget_tokens**: Can exceed max_tokens with interleaved thinking (up to context window 200K)
- **Minimum budget**: 1024 tokens (start higher for complex tasks: 10K-16K)
- **Streaming**: `thinking_delta` events before text_delta

**Key constraints:**
- Cannot use with temperature, top_k, forced tool use, pre-fill
- Cannot toggle thinking mid-turn (entire assistant turn must use same mode)
- Tool use only supports `tool_choice: "auto"` or `"none"` (not "any" or specific tool)

**Pricing:**
- Billed for full thinking tokens (not summary)
- Output tokens include thinking + text
- Thinking blocks from previous turns count as input tokens when passed back

**Relationship to other features:**
- Prompt caching: Thinking parameter changes invalidate messages cache (see Prompt Caching)
- Context editing: Use `clear_thinking_20251015` with `keep: "all"` (see Context Editing)
- Context windows: Previous thinking auto-stripped, not counted in context (see Context Windows)
- Tool use: Must preserve thinking blocks (see What's New, Context Windows)
- Opus 4.5: Thinking blocks preserved by default (optimization for caching)

**Skip:**
- Full thinking output (only for enterprise, we use summarized)
- Thinking redaction handling (UI concern, not critical)
- Custom thinking budgets per user (use default 10K)

---

### Effort

**Link:** https://platform.claude.com/docs/en/build-with-claude/effort
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Always use high effort for Opus 4.5**: `output_config: {"effort": "high"}`
  - Beta header: `effort-2025-11-24`
  - High = default behavior (can omit parameter, but better to be explicit)
  - Only supported in Opus 4.5, not Sonnet/Haiku

**Technical details (for implementation):**
- Affects ALL tokens: text responses, tool calls, extended thinking
- Three levels: low (most efficient), medium (balanced), high (maximum capability/default)
- Works independently from extended thinking budget
- Lower effort = fewer tokens = faster responses + lower cost

**Relationship to other features:**
- Extended thinking: Effort affects thinking tokens too (see Extended Thinking)
- Tool use (Phase 1.5): Lower effort = fewer tool calls, less explanation
- Model registry: Add `supports_effort_parameter` flag (only Opus 4.5: True)

**Skip:**
- Dynamic effort adjustment per request (always use high)
- Low/medium effort levels (we want maximum quality)

---

### Streaming

**Link:** https://platform.claude.com/docs/en/build-with-claude/streaming
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Always streaming**: Already implemented in Phase 1.3 ✅
- **Add thinking_delta/signature_delta handling**: For Extended Thinking streaming
  - signature_delta comes before content_block_stop (cryptographic signature)
- **Error recovery**: Implement retry with partial response preservation
  - Note: Tool use and thinking blocks cannot be partially recovered
- **(Phase 1.5) input_json_delta**: For tool use streaming (partial JSON)

**Important for implementation:**
- **Usage counts are cumulative** in message_delta, not incremental!
- Use SDK helpers (text_stream, message accumulation) instead of manual SSE parsing
- Streaming can have delays and "chunky" delivery with extended thinking (expected)

**Relationship to other features:**
- Extended Thinking: thinking_delta and signature_delta events (see Extended Thinking)
- Tool Use (Phase 1.5): input_json_delta for partial JSON (see phase-1.5-multimodal-tools.md)
- Prompt caching: Works transparently with streaming
- Context editing: Applied server-side before streaming begins

---

### Citations

**Link:** https://platform.claude.com/docs/en/build-with-claude/citations
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Defer to Phase 1.5 or later** - not critical for Phase 1.4
- **Use case for future**: When users send documents (PDF, text files) and want answers with source references
  - Example: User sends PDF document, asks questions, Claude responds with exact citations (page numbers, character ranges)
- **Enable when needed**: Set `citations: {"enabled": true}` on document blocks

**Key features (for future reference):**
- Three document types: Plain text (sentence chunks), PDF (page numbers), Custom content (custom chunks)
- `cited_text` field doesn't count towards output tokens (cost optimization!)
- Works with prompt caching (cache document content)
- Streaming: `citations_delta` events

**Important constraints:**
- **Incompatible with Structured Outputs** - cannot use together
- Only text citations supported (no image citations from PDFs yet)
- All documents in request must have citations enabled or disabled (not mixed)

**Relationship to other features:**
- PDF support (Phase 1.5): Citations work with PDF documents (see PDF Support page)
- Files API (Phase 1.5): Can reference uploaded files by file_id
- Prompt caching: Apply cache_control to document blocks for efficiency
- Streaming: citations_delta events for real-time citation delivery
- Structured outputs: Incompatible (cannot use together)

**Skip for now:**
- Document processing implementation (Phase 1.5)
- Citation UI/UX design
- Files API integration

---

### Token Counting

**Link:** https://platform.claude.com/docs/en/build-with-claude/token-counting
**Date reviewed:** 2026-01-08

**Our decisions:**
- **Use before large requests**: Call token counting API before sending conversations with long history
  - Avoid context overflow errors (200K limit)
  - Proactive management instead of reactive error handling
- **Cost estimation**: Preview cost before actual API call
- **Use case**: When thread history grows large (e.g., >150K tokens estimated)

**Important characteristics:**
- **Free to use** but has rate limits (100-8000 RPM based on tier)
- **Estimate only** - actual tokens may differ slightly, not charged for system-added tokens
- Supports all features: system prompts, tools, images, PDFs, extended thinking, citations
- **Does NOT use prompt caching** - just estimation, caching happens during actual message creation

**Extended thinking note:**
- Previous assistant turn thinking blocks **do not count** (API auto-strips them)
- Current turn thinking **does count** if included in conversation history

**Relationship to other features:**
- Context Windows: Use token counting to avoid overflow (mentioned in Context Windows page)
- Extended thinking: Previous thinking ignored, current thinking counted
- Prompt caching: Token counting doesn't trigger caching (happens at message creation)
- PDF/Citations/Tools: All supported for counting

**Skip:**
- Automatic token counting on every request (only when needed - large history)
- Client-side token estimation (use official API for accuracy)

---

### Vision (Images)

**Link:** https://platform.claude.com/docs/en/build-with-claude/vision
**Date reviewed:** 2026-01-08

**Our decisions (Phase 1.5):**
- **Always use Files API** for all images (Telegram photos, user uploads)
  - User sends photo → Telegram file_id → download → upload to Files API → get claude_file_id
  - Store claude_file_id in `user_files` table
  - Eager upload: блокирующий (процесс приостанавливается до завершения)
- **Selective processing via tools**:
  - Files uploaded but NOT sent to Claude immediately
  - System prompt shows available files list
  - Claude uses `analyze_image(claude_file_id, question)` tool when needed
  - Only relevant images processed per request (cost optimization)
- **File lifecycle**:
  - Cleanup: 24 hours after upload (`FILES_API_TTL_HOURS` in config)
  - Reject files >500MB (Files API limit)
- **Cost estimation**:
  - ~1600 tokens per 1092x1092 px image
  - Check user balance before large uploads

**Why Files API for images:**
- Telegram Bot API: 20MB download limit (insufficient for some photos)
- Files API: 500MB limit + persistent storage
- Upload once, use multiple times (tools can reference by file_id)
- Ready for code execution tool integration

**Model support:**
- All Claude 4.5 models: Sonnet, Haiku, Opus ✅

**Technical constraints (Files API):**
- Max 500MB per file
- 100GB total storage per organization
- Files persist until deleted (manual or auto-cleanup)
- Supported formats: JPEG, PNG, GIF, WebP

**Important limitations (Claude Vision):**
- **Cannot identify people by name** (AUP violation)
- Limited spatial reasoning (analog clocks, chess positions)
- Approximate counting only (not precise for many small objects)
- Cannot detect AI-generated images
- No healthcare diagnostics (CTs, MRIs)

**Tools architecture:**
```python
# Specialized tool for vision
{
  "name": "analyze_image",
  "description": "Analyze an image using Claude's vision capabilities. Use for photos, screenshots, diagrams, charts.",
  "input_schema": {
    "claude_file_id": "File ID from available files list",
    "question": "What to analyze or extract from the image"
  }
}

# Universal fallback via code execution
{
  "type": "code_execution_20250825",
  "name": "code_execution"
}
```

**Relationship to other features:**
- **Files API**: Core storage mechanism (see Files API page)
- **Prompt caching**: Cache image content for repeated analysis
- **Token counting**: Images count towards input tokens
- **Tool use**: Selective processing via analyze_image tool
- **Code execution**: Universal file processing fallback
- **Extended thinking**: Can analyze images with extended thinking

**DB structure (user_files table):**
```python
class UserFile(Base):
    id: int
    message_id: int  # FK to messages
    telegram_file_id: str | None  # If from user
    claude_file_id: str  # After Files API upload
    filename: str
    file_type: str  # 'image', 'pdf', 'document', 'generated'
    mime_type: str
    file_size: int
    uploaded_at: datetime
    expires_at: datetime  # uploaded_at + 24h
    source: str  # 'user' or 'assistant'
    metadata: dict  # JSONB: {width, height, ...}
```

**Context representation:**
```python
# System prompt (dynamically generated):
"Available files in this conversation:
- winter_photo.jpg (image, 2.3 MB, uploaded 5 min ago, claude_file_id: file_abc123)
- chart.png (image, 1.1 MB, uploaded 2 min ago, claude_file_id: file_xyz789)"

# User message (after file upload):
"User uploaded: winter_photo.jpg (image/jpeg, 2.3 MB)"

# Assistant message (after generation):
"Assistant generated: chart.png (image/png, 1.1 MB)"
```

**Skip:**
- URL-based or base64 encoding (always Files API)
- Image generation/editing (Claude can't do this - use external APIs in Phase 1.5)
- Perfect precision tasks (counting, spatial reasoning)

---

### PDF Support

**Link:** https://platform.claude.com/docs/en/build-with-claude/pdf-support
**Date reviewed:** 2026-01-08

**Our decisions (Phase 1.5):**
- **Always use Files API** for all PDFs (same as images)
  - User sends PDF → Telegram file_id → download → upload to Files API → get claude_file_id
  - Store in `user_files` table with `file_type='pdf'`
  - Eager upload: блокирующий
- **Selective processing via tools**:
  - PDFs uploaded but NOT sent to Claude immediately
  - System prompt shows available files
  - Claude uses `analyze_pdf(claude_file_id, question, pages)` tool when needed
  - Only requested pages/sections processed (cost optimization)
- **Prompt caching: always enabled** for PDFs
  - Massive cost savings for repeated queries
  - `cache_control: {"type": "ephemeral"}` on document blocks
- **No citations** (simpler, faster)
  - Skip citations feature for Phase 1.5
  - May add in later phases if needed
- **Large PDFs handling**:
  - Process fully (no artificial page limits)
  - Check user balance before processing (~4K tokens/page average)
  - Token Counting API for precise estimation before large PDFs
- **File lifecycle**: Same as images (24h, FILES_API_TTL_HOURS)

**How PDFs work in Claude:**
- Each page → text extraction + image conversion
- Claude analyzes both text and visual content (charts, diagrams, tables)
- Combines vision capabilities with text processing
- ~3,000-5,000 tokens per page on average (content dependent)

**Model support:**
- All Claude 4.5 models: Sonnet, Haiku, Opus ✅

**Technical constraints:**
- Max 500MB per file (Files API limit, much better than 32MB direct)
- Max 100 pages per single Claude request (split large PDFs via tools)
- No password-protected or encrypted PDFs
- Subject to same vision limitations (see Vision page)

**Tools architecture:**
```python
# Specialized tool for PDFs
{
  "name": "analyze_pdf",
  "description": "Analyze a PDF document using Claude's PDF support. Use for text extraction, document analysis, finding specific information.",
  "input_schema": {
    "claude_file_id": "File ID from available files list",
    "question": "What to analyze or extract",
    "pages": "Page range like '1-5' or 'all' (optional)"
  }
}

# Universal fallback via code execution
{
  "type": "code_execution_20250825",
  "name": "code_execution"
}
```

**Multimodal scenarios:**
User sends PDF + 3 photos → all uploaded to Files API → all shown in system prompt → Claude selects relevant files via tools when answering user question.

**Relationship to other features:**
- **Files API**: Core storage mechanism (see Files API page)
- **Vision**: Each PDF page converted to image internally
- **Prompt caching**: Always enabled for PDFs (cache_control)
- **Token counting**: Use before large PDFs (>50 pages)
- **Tool use**: Selective page processing via analyze_pdf tool
- **Code execution**: Alternative processing (extract text, convert formats, etc.)

**Cost optimization example:**
```
User uploads 200-page PDF
→ Stored in Files API (free)
→ User asks "What's on page 5?"
→ Claude calls analyze_pdf(file_id, "summarize", pages="5")
→ Only page 5 processed (~4K tokens) instead of full 800K tokens
→ 200x cost savings!
```

**DB structure:** Same `user_files` table as images, `file_type='pdf'`, `metadata={'page_count': 200, ...}`

**Skip:**
- Citations feature (not implementing in Phase 1.5)
- Batch API (not for real-time Telegram)
- Healthcare/diagnostic use (not designed for this)
- Base64 encoding (always Files API)

---

### Files API

**Link:** https://platform.claude.com/docs/en/build-with-claude/files
**Date reviewed:** 2026-01-08

**Our decisions (Phase 1.5):**
- **Core storage mechanism** for all files in the bot
  - All images, PDFs, documents → uploaded to Files API
  - Store claude_file_id in `user_files` table
  - No direct base64/URL passing to Claude
- **Beta feature**: `anthropic-beta: files-api-2025-04-14`
- **Lifecycle management**:
  - Auto-delete after 24 hours (`FILES_API_TTL_HOURS` in config)
  - Manual delete for generated files when no longer needed
  - Cron job for cleanup

**How Files API works:**
1. Upload file → receive `file_id`
2. Reference `file_id` in Messages API requests
3. Download files generated by code execution tool
4. List/retrieve/delete files via management endpoints

**Content block types by file:**
- **Images**: `{"type": "image", "source": {"type": "file", "file_id": "..."}}`
- **PDFs**: `{"type": "document", "source": {"type": "file", "file_id": "..."}, "citations": {"enabled": false}}`
- **Text files**: `{"type": "document", "source": {"type": "file", "file_id": "..."}}`
- **Code execution inputs**: `{"type": "container_upload", "file_id": "..."}`

**Storage limits:**
- **Max file size**: 500MB per file
- **Total storage**: 100GB per organization
- **Files persist**: Until manually deleted (no automatic expiration by Anthropic)
- **Operations are FREE**: upload, download, list, delete
- **File content in Messages**: Priced as input tokens

**Supported file types:**
- **Images**: JPEG, PNG, GIF, WebP
- **Documents**: PDF, plain text
- **Code execution**: CSV, Excel, JSON, XML, images, text, and more

**Important characteristics:**
- Files scoped to workspace (all API keys in org can access)
- Cannot download files you uploaded (only files created by code execution/skills)
- Files persist in active Messages API calls even after deletion
- Rate limit: ~100 requests/minute during beta

**Management operations:**
```python
# Upload
file = client.beta.files.upload(file=open("data.csv", "rb"))

# List all files
files = client.beta.files.list()

# Get metadata
metadata = client.beta.files.retrieve_metadata(file_id)

# Download (only code execution outputs)
content = client.beta.files.download(file_id)

# Delete
client.beta.files.delete(file_id)
```

**Our implementation:**
```python
# bot/core/files_api.py - wrapper around Files API
async def upload_file(file_path: str) -> str:
    """Upload file to Files API, return claude_file_id"""

async def delete_file(claude_file_id: str):
    """Delete file from Files API"""

async def cleanup_expired_files():
    """Cron job: delete files older than FILES_API_TTL_HOURS"""
    files = await get_expired_files()
    for file in files:
        await delete_file(file.claude_file_id)
        await db.delete(file)

# bot/telegram/handlers/files.py
@router.message(F.photo | F.document)
async def handle_file_upload(message: Message):
    # 1. Download from Telegram
    file_bytes = await download_telegram_file(message)

    # 2. Upload to Files API (blocking!)
    claude_file_id = await upload_file(file_bytes)

    # 3. Save to DB
    await create_file_record(
        message_id=message.message_id,
        telegram_file_id=message.photo.file_id,
        claude_file_id=claude_file_id,
        expires_at=now() + timedelta(hours=FILES_API_TTL_HOURS)
    )

    # 4. Add text mention to context
    await create_message(
        content=f"User uploaded: {filename} ({mime_type}, {size})",
        metadata={"file_id": claude_file_id}
    )
```

**Relationship to other features:**
- **Vision**: All images stored via Files API
- **PDF Support**: All PDFs stored via Files API
- **Code execution**: Input files via `container_upload`, output files downloadable
- **Tool use**: Tools reference files by claude_file_id
- **Prompt caching**: Can cache file content with `cache_control`

**Error handling:**
- `404`: File not found or no access
- `400`: Invalid file type for content block type
- `400`: File exceeds context window (e.g., 500MB text file)
- `400`: Invalid filename (forbidden chars, length 1-255)
- `413`: File exceeds 500MB limit
- `403`: Storage limit exceeded (100GB)

**Why Files API for everything:**
1. **Unified architecture**: One path for all file types
2. **No Telegram limitations**: 20MB download limit bypassed
3. **Tools integration**: Essential for selective processing
4. **Code execution ready**: Native support for code execution tool
5. **Cost optimization**: Upload once, reference many times
6. **Generated files**: Can download code execution outputs

**Skip:**
- Downloading uploaded files (API doesn't support, only code execution outputs)
- Amazon Bedrock / Vertex AI (not supported)
- Mixing Files API with direct base64/URL (choose one approach)

---

### Search Results

**Link:** https://platform.claude.com/docs/en/build-with-claude/search-results
**Date reviewed:** 2026-01-08

**What is it:**
Content block type `search_result` for RAG (Retrieval-Augmented Generation) applications with automatic citations. Enables web search-quality citations for custom knowledge bases.

**Two methods:**
1. **From tool calls**: Tools return `search_result` blocks (dynamic RAG)
2. **Top-level content**: Pass search results directly in user messages

**Schema:**
```json
{
  "type": "search_result",
  "source": "https://example.com/article",
  "title": "Article Title",
  "content": [{"type": "text", "text": "..."}],
  "citations": {"enabled": true}
}
```

Claude automatically adds citations when using info from search results.

**Our decisions:**

**Phase 1.5: web_search and url_fetch tools**
- ✅ `web_search` - server-side tool (official Claude API)
  - Beta: `web-search-2025-03-05`
  - Returns search_result blocks with citations
  - Use for general internet search
- ✅ `url_fetch` - custom client-side tool
  - Fetches specific URL, parses HTML, returns as search_result block
  - Use libraries: requests, beautifulsoup4, trafilatura
  - Returns search_result format for consistency

**Phase 1.6: RAG with vector search**
- ✅ `search_user_files` - custom tool + vector DB
  - Search through user's uploaded files
  - Qdrant container for vector search
  - Embeddings service (OpenAI embeddings or sentence-transformers)
  - Returns search_result blocks with source=file_id
- ✅ Full RAG infrastructure (see Phase 1.6 documentation)

**Why split across phases:**
- Phase 1.5: Simple tools (no new infrastructure)
- Phase 1.6: Complex infrastructure (vector DB, embeddings, indexing)

**Hybrid approach:**
Claude chooses which tools to use based on query:
- "Search the internet" → web_search
- "Read this URL" → url_fetch
- "Search my files" → search_user_files (Phase 1.6)
- "Find info about X" → any combination

**Citations handling:**
- ✅ Enable citations internally (`citations: {"enabled": true}`)
- ✅ Don't show citations to user in Telegram
- ✅ Use citations for internal tracking/debugging

**Model support:**
- All Claude 4.5 models: Sonnet, Haiku, Opus ✅

**Relationship to other features:**
- **Tool use**: Primary mechanism for RAG (tools return search_result blocks)
- **Files API**: search_user_files references files via claude_file_id
- **Prompt caching**: Can cache search results with cache_control
- **Code execution**: Can process search results data

**Skip for Phase 1.5:**
- Vector DB infrastructure (Phase 1.6)
- User files indexing (Phase 1.6)
- Full RAG system (Phase 1.6)

**Skip entirely:**
- Showing citations to user (internal use only)
- Top-level search results method (tools method is cleaner)

---

### Tool Use Implementation

**Link:** https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use
**Date reviewed:** 2026-01-08

**Our decisions (Phase 1.5 implementation):**

**1. Tool Runner (SDK Beta) - use everywhere**
- Use SDK's `@beta_tool` decorator (Python) for all custom tools
- Automatic tool loop, error handling, streaming support
- Simpler than manual implementation for our use cases
- All our tools are straightforward (API calls, HTTP requests, DB queries)

**Why Tool Runner:**
```python
# Simple tools:
- analyze_image → Claude Vision API call
- analyze_pdf → Claude PDF API call
- web_search → server-side tool (no implementation)
- url_fetch → HTTP request + HTML parsing
- search_user_files → Qdrant vector search + format results
- code_execution → server-side tool (no implementation)

# No complex state management or custom logic needed
# Tool runner handles all boilerplate
```

**Implementation pattern:**
```python
from anthropic import beta_tool
import json

@beta_tool
def analyze_image(claude_file_id: str, question: str) -> str:
    """Analyze an image using Claude's vision capabilities.

    Use this tool for photos, screenshots, diagrams, charts when you need
    visual understanding. The tool uses Claude's vision API to analyze the
    image and answer questions about its content. It can identify objects,
    read text (OCR), describe scenes, and analyze visual data.

    When to use: User asks about image content, wants to extract text from
    images, needs description of visual elements, or wants to analyze charts/diagrams.

    Limitations: Cannot identify people by name, limited spatial reasoning,
    approximate counting only.

    Args:
        claude_file_id: File ID from available files list in conversation
        question: What to analyze or extract from the image

    Returns:
        JSON string with analysis results
    """
    # Implementation
    response = claude_client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2048,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "file", "file_id": claude_file_id}
                },
                {"type": "text", "text": question}
            ]
        }]
    )
    return json.dumps({"analysis": response.content[0].text})

# Use with tool runner
runner = client.beta.messages.tool_runner(
    model="claude-sonnet-4-5",
    max_tokens=4096,
    tools=[analyze_image, analyze_pdf, url_fetch, search_user_files],
    messages=[...]
)
for message in runner:
    # Stream to Telegram
    await send_to_telegram(message.content[0].text)
```

**2. Detailed tool descriptions (3-4+ sentences minimum)**
Each tool description must include:
- What the tool does
- When it should be used (and when it shouldn't)
- What each parameter means and how it affects behavior
- Important caveats or limitations
- What information the tool does/doesn't return

**Example good description:**
```python
"""Analyzes a PDF document using Claude's vision and text extraction capabilities.
Use this when the user asks about PDF content, wants to extract information,
or needs to understand document structure. The tool processes both text and
visual elements (charts, diagrams, tables) using Claude's multimodal capabilities.
It accepts page ranges to analyze specific sections ('1-5' or 'all').
Returns extracted text and analysis. Does NOT support password-protected PDFs.
Best for documents under 100 pages (larger documents may hit context limits).
Token cost: approximately 3,000-5,000 tokens per page."""
```

**Example poor description:**
```python
"""Analyze PDF documents."""  # Too brief, missing context
```

**3. input_examples for complex tools (Beta)**
- Beta header: `advanced-tool-use-2025-11-20`
- Use for tools with complex schemas, nested objects, optional parameters
- Particularly useful for `search_user_files` (Phase 1.6)
- Token cost: ~20-50 tokens per simple example, ~100-200 for complex

**Example:**
```python
{
    "name": "search_user_files",
    "description": "...",
    "input_schema": {...},
    "input_examples": [
        {
            "query": "quantum computing research",
            "thread_id": 123,
            "file_types": ["pdf", "document"],
            "top_k": 5
        },
        {
            "query": "financial data Q4 2025"
            # No optional params - shows they're optional
        }
    ]
}
```

**4. Chain of thought prompt in system prompt**
Add to system prompt for better tool selection:
```python
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
```

**5. Default parallel tool behavior**
- Sonnet 4.5 excellent at parallel tools by default
- No special prompting needed
- Tool runner handles parallel execution automatically
- Ensure tool results formatted correctly (all in single user message!)

**Critical formatting for parallel tools:**
```python
# ✅ Correct: all tool results in one message
{
    "role": "user",
    "content": [
        {"type": "tool_result", "tool_use_id": "id1", "content": "result1"},
        {"type": "tool_result", "tool_use_id": "id2", "content": "result2"}
    ]
}

# ❌ Wrong: separate messages (teaches Claude to avoid parallel)
# Message 1: {"role": "user", "content": [tool_result_1]}
# Message 2: {"role": "user", "content": [tool_result_2]}
```

**6. Error handling: pass errors to Claude**
Tool runner automatically handles errors:
```python
@beta_tool
def analyze_image(claude_file_id: str, question: str) -> str:
    """..."""
    try:
        # Tool implementation
        return result
    except Exception as e:
        # Tool runner catches exception, returns to Claude with is_error: true
        # Claude then explains error to user naturally
        raise  # Let tool runner handle it
```

Claude receives:
```json
{
    "type": "tool_result",
    "tool_use_id": "...",
    "content": "ConnectionError: Claude API unavailable (HTTP 500)",
    "is_error": true
}
```

Claude responds: "I encountered an error accessing the image analysis API. Please try again in a moment."

**7. tool_choice: auto (default)**
- Claude decides when to use tools
- No forcing specific tools (unless special commands like `/search`)
- Natural conversation flow

**8. Tool use system prompt**
Automatically added by Claude API (~346 tokens for Sonnet 4.5):
```
In this environment you have access to a set of tools you can use to answer the user's question.
{{ FORMATTING INSTRUCTIONS }}
{{ TOOL DEFINITIONS IN JSON SCHEMA }}
{{ USER SYSTEM PROMPT }}
{{ TOOL CONFIGURATION }}
```

**Model selection:**
- **Claude Sonnet 4.5**: Recommended for all tool use (balance of speed + quality)
- **Claude Opus 4.5**: For complex multi-tool scenarios, better reasoning
- **Claude Haiku 4.5**: Simple tools only, may infer missing parameters

**Relationship to other features:**
- **Streaming**: Tool runner supports streaming with `stream=True`
- **Prompt caching**: Cache tool results with `cache_control: {"type": "ephemeral"}`
- **Extended thinking**: Compatible with tool use, helps with complex decisions
- **Files API**: Tools reference files by claude_file_id
- **Search results**: Tools return search_result blocks for RAG

**Skip:**
- Manual tool implementation (tool runner handles everything)
- Strict tool use / structured outputs (not needed for our tools)
- Custom tool_choice settings (auto is sufficient)
- Parallel tool prompting (default behavior good enough)

---

### Code Execution Tool

**Link:** https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool
**Date reviewed:** 2026-01-08

**What is it:**
Server-side tool for executing Python code and Bash commands in sandboxed containers.

**Key features:**
- Beta: `code-execution-2025-08-25`
- Isolated environment: 5GB RAM, 5GB disk, Python 3.11
- Pre-installed: pandas, numpy, matplotlib, seaborn, scikit-learn, PIL, pypdf, ~30 libraries
- Two sub-tools: `bash_code_execution` (shell), `text_editor_code_execution` (files)
- Files API integration: `container_upload` content type
- Container reuse: 30 days lifetime
- Pricing: 1,550 free hours/month, then $0.05/hour, **minimum 5 minutes billing**

**Critical limitation:**
- **NO INTERNET ACCESS** - cannot make HTTP requests, pip install new packages, call external APIs

**Our decision: DO NOT USE for Phase 1.5**

**Why not:**

❌ **No internet** - Cannot:
- Make API calls (`requests.get()`)
- Install packages beyond pre-installed
- Scraping web pages
- Access external services
- Get real-time data

❌ **Limited use cases** - Only offline data processing:
- Analyze uploaded CSV/Excel
- Build charts from static data
- Math/statistics on provided data
- Image/PDF processing

❌ **Not suitable for universal Telegram bot** - Most user requests require:
- "Download stock prices and analyze"
- "Install library X and do Y"
- "Make request to API Z"
- "Search and process web data"

❌ **Billing constraints:**
- Minimum 5 minutes per call ($0.00416)
- Not cost-effective for quick operations

**Alternative: External code execution service (Phase 1.5)**

Use third-party service with internet access:

**Option A: E2B (e2b.dev)**
- Code interpreter API (like Claude's but with internet)
- Sandboxed Python/Node.js
- File system access
- Pip install any packages
- Pay-as-you-go pricing

**Option B: Modal (modal.com)**
- Serverless containers
- GPU support (for ML)
- Custom Docker images
- Internet access
- Free tier + pay per second

**Option C: Self-hosted Docker**
- Full control
- Any configuration
- More complex to maintain

**Implementation plan (Phase 1.5):**
```python
# bot/core/tools/execute_code.py

from e2b import Sandbox  # or Modal, or custom Docker

@beta_tool
async def execute_python(
    code: str,
    requirements: list[str] = None,
    timeout: int = 30
) -> str:
    """Execute Python code with internet access and arbitrary packages.

    Can install any pip package, make HTTP requests, call external APIs,
    and perform any Python operations. Much more flexible than Claude's
    built-in code execution.

    Args:
        code: Python code to execute
        requirements: Pip packages to install (e.g., ["requests", "beautifulsoup4"])
        timeout: Maximum execution time in seconds

    Returns:
        JSON with stdout, stderr, return_code
    """

    # E2B example
    sandbox = Sandbox()

    if requirements:
        sandbox.run_code(f"pip install {' '.join(requirements)}")

    result = sandbox.run_code(code, timeout=timeout)

    return json.dumps({
        "stdout": result.stdout,
        "stderr": result.stderr,
        "return_code": result.exit_code
    })
```

**Use cases enabled by external service:**
✅ "Download Bitcoin prices and plot trends"
✅ "Install library X and process data Y"
✅ "Make API call to Z and analyze results"
✅ "Scrape website and extract information"
✅ "Run ML model from HuggingFace"
✅ "Process images with custom CV library"

**Decision rationale:**
- Claude code execution too limited (no internet)
- External service provides full flexibility
- Cost is similar or better (E2B/Modal competitive pricing)
- Better UX (can handle arbitrary user requests)

**Phase 1.5 will evaluate and choose:** E2B vs Modal vs self-hosted Docker

**Skip:**
- Claude's built-in code execution tool (server-side)
- Bash tool (similar limitations, see previous page)
- Any offline-only code execution approach

---

### Web Fetch Tool

**Link:** https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool

**Our decision: ✅ USE official web_fetch (server-side)**

**What it is:**

Official server-side tool that retrieves full content from URLs:
- ✅ Web pages (HTML)
- ✅ PDF documents (automatic text extraction)
- ❌ No JavaScript rendering

**Key features:**

**1. Security:**
- Can ONLY fetch URLs from conversation context:
  - URLs in user messages
  - URLs from web_search results
  - URLs from previous web_fetch results
- ❌ Cannot generate/construct URLs dynamically

**2. Pricing:**
- **FREE** (no additional charges)
- Pay only standard token costs for fetched content
- Typical sizes:
  - Average web page (10KB): ~2,500 tokens
  - Large documentation (100KB): ~25,000 tokens
  - Research paper PDF (500KB): ~125,000 tokens

**3. Parameters:**
- `max_uses`: Limit fetches per request
- `max_content_tokens`: Limit content size (protects from huge pages)
- `allowed_domains` / `blocked_domains`: Domain filtering
- `citations`: Optional citations (like web_search)

**4. Built-in features:**
- ✅ Automatic caching (managed by Anthropic)
- ✅ PDF text extraction (no need for PyPDF2)
- ✅ Optional citations
- ✅ Error handling (url_not_accessible, unsupported_content_type, etc.)

**5. Beta status:**
- Requires header: `anthropic-beta: web-fetch-2025-09-10`
- Available on: Sonnet 4.5, Sonnet 4, Opus 4.5, Opus 4.1, Opus 4, Haiku 4.5

**Our configuration (Phase 1.5):**

```python
# Server-side tools
{
    "type": "web_fetch_20250910",
    "name": "web_fetch",
    # No max_uses limit (users have token budget anyway)
    # max_content_tokens - inherit from model's max_output
    # No citations (not showing to users)
    # No domain filtering (users should access any public URL)
}
```

**Why official web_fetch instead of custom implementation:**

**Previous plan (custom url_fetch):**
- Custom implementation with requests + BeautifulSoup
- Manual PDF handling (PyPDF2)
- Manual caching
- Manual error handling
- ~200 lines of code

**With official web_fetch:**
- ✅ Zero implementation
- ✅ Automatic PDF extraction
- ✅ Automatic caching
- ✅ Built-in error handling
- ✅ Citations support
- ✅ Same cost (only tokens)

**Decision: Use official web_fetch, skip custom implementation entirely.**

**Relationship with other tools:**

**web_search + web_fetch workflow:**
```
User: "Find recent articles about quantum computing and analyze the most relevant one"
↓
1. Claude calls web_search → gets URLs + snippets
2. Claude selects promising URL
3. Claude calls web_fetch → gets full content
4. Claude analyzes full content → detailed answer
```

**web_fetch vs analyze_pdf:**
- `web_fetch`: PDF from URL (internet)
  - Example: "Analyze https://arxiv.org/paper.pdf"
- `analyze_pdf`: User-uploaded PDF (Telegram → Files API)
  - Example: User attaches file → "What's in this PDF?"
- **Both needed** (different use cases)

**Limitations:**

❌ **No JavaScript rendering:**
- Can't fetch content from SPAs (React, Vue, Angular apps)
- Can't interact with dynamic content
- Workaround: For JS-heavy sites, consider computer use tool (but we're not using it)

⚠️ **Data exfiltration risk:**
- Claude can't construct URLs dynamically (mitigates this)
- But can fetch user-provided URLs (residual risk)
- Our approach: Allow all public URLs (users control what they share)

---

### Web Search Tool

**Link:** https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool

**Our decision: ✅ USE with minimal configuration**

**What it is:**

Official server-side tool for web search with real-time internet access:
- Returns search results with URLs, titles, snippets
- Always includes citations (automatically)
- Typically used with web_fetch for deep analysis

**Key features:**

**1. Pricing:**
- **$10 per 1,000 searches** ($0.01 per search)
- Plus standard token costs for search results
- Each search = 1 use (regardless of number of results)
- Failed searches are NOT billed

**2. Citations:**
- Always enabled (unlike web_fetch where optional)
- `cited_text`, `title`, `url` do NOT count towards token usage (free!)
- Encrypted content for multi-turn conversations
- Must be displayed to end users (per TOS)

**3. Parameters:**
```python
{
    "type": "web_search_20250305",
    "name": "web_search",

    # Optional parameters we're NOT using:
    # - max_uses: omitted (Claude decides how many searches needed)
    # - user_location: omitted (no localization)
    # - allowed_domains/blocked_domains: omitted (no filtering)
}
```

**4. Requirements:**
- Must be enabled by admin in Console → Settings → Privacy
- Organization-level domain restrictions (if any) apply automatically

**Our configuration (Phase 1.5):**

```python
# Minimal configuration
{
    "type": "web_search_20250305",
    "name": "web_search"
}
```

**Why minimal configuration:**

**No max_uses limit:**
- Claude knows when searches are useful
- Users have token budget limiting abuse
- Cost is reasonable ($0.01 per search)
- Flexible for various use cases

**No user_location:**
- Simplifies implementation (no location tracking)
- Works globally without configuration
- Users get general web results (not localized)

**No domain filtering:**
- Allow access to all public information
- Users control what they ask about
- No maintenance of domain lists

**Cost tracking (Phase 2.1 Payment System):**

```python
# Usage tracking
"usage": {
    "input_tokens": 6039,
    "output_tokens": 931,
    "server_tool_use": {
        "web_search_requests": 1  # Track for billing
    }
}

# Calculate cost
web_search_cost = web_search_requests * 0.01  # $0.01 per search
total_cost = token_cost + web_search_cost
```

**Typical usage patterns:**

**Pattern 1: Search only**
```
User: "What's the latest news about SpaceX?"
Claude: web_search("SpaceX latest news 2026")
Claude: Summarizes results with citations
Cost: ~1 search ($0.01) + ~2K tokens
```

**Pattern 2: Search + Fetch (deep analysis)**
```
User: "Find recent AI research papers and analyze the best one"
Claude: web_search("AI research papers 2026")
Claude: web_fetch(best_paper_url)
Claude: Detailed analysis with citations
Cost: 1 search ($0.01) + 1 fetch (tokens only) + ~25K tokens
```

**Pattern 3: Multiple searches**
```
User: "Compare weather in NYC, London, Tokyo"
Claude: web_search("weather NYC")
Claude: web_search("weather London")
Claude: web_search("weather Tokyo")
Claude: Comparison table with citations
Cost: 3 searches ($0.03) + ~5K tokens
```

**Workflow with web_fetch:**

```
web_search: Find relevant URLs + snippets
     ↓
Claude evaluates which URLs are most relevant
     ↓
web_fetch: Get full content from selected URLs
     ↓
Claude provides detailed analysis with citations
```

**Features we're using:**
- ✅ Automatic citations (always on)
- ✅ Multi-turn conversations (encrypted content preserved)
- ✅ Streaming support
- ✅ Prompt caching support
- ✅ Batch API support

**Features we're NOT using:**
- ❌ max_uses (no artificial limit)
- ❌ user_location (no localization)
- ❌ Domain filtering (allow all)

**Error handling:**

Errors returned in tool_result (not HTTP errors):
- `too_many_requests` - rate limit
- `max_uses_exceeded` - only if we add max_uses
- `query_too_long` - query too long
- `unavailable` - internal error

All handled by Tool Runner automatically.

**Special features:**

**pause_turn stop reason:**
- For long-running searches
- Can continue or interrupt turn
- Tool Runner handles automatically

**Relationship with web_fetch:**
- web_search: "Find information about X"
- web_fetch: "Read this specific URL"
- Often used together in same turn
- Both server-side (no implementation needed)

---

<!-- Template for each page:

### [Page Title]

**Link:** https://docs.anthropic.com/...
**Date reviewed:** YYYY-MM-DD

**Key insights:**
- Important insight 1
- Important insight 2

**What we'll implement:**
- Technique/feature 1
  - Implementation: `file_path:line` or description
  - Why: rationale
- Technique/feature 2
  - Implementation: description
  - Why: rationale

**What we'll skip:**
- Feature X: reason why not needed for our use case

---

-->

---

## Implementation Plan

### ✅ Phase 1.4.1: Model Registry (Completed)
- ✅ Create model registry with characteristics (model_id, display_name, provider, context_window, max_output, pricing_input, pricing_output, latency_tier)
- ✅ Add model selection field to User model in database
- ✅ Implement `/model` command handler with inline keyboard for model selection
- ✅ Update ClaudeClient to use selected model characteristics (max_tokens, max_output)
- ✅ Update cost tracking to use model-specific pricing
- ✅ Ensure architecture supports adding non-Claude providers later
- ✅ Extend model registry with capability flags: `extended_thinking`, `interleaved_thinking`, `effort`, `context_awareness`, `vision`, `streaming`, `prompt_caching`
- ✅ Extend model registry with cache pricing: `pricing_cache_write_5m`, `pricing_cache_write_1h`, `pricing_cache_read`

### ✅ Phase 1.4.2: Prompt Caching (Completed)
- ✅ Add cache_control to system prompt: `{"type": "ephemeral"}` (5-minute, 10x cost reduction)
- ✅ Conditional caching: only when system prompt ≥ 1024 tokens (Sonnet 4.5 minimum)
- ✅ Update Message model: `cache_creation_input_tokens`, `cache_read_input_tokens` fields
- ✅ Update cost calculation: cache-aware pricing (0.1x reads, 1.25x writes)
- ✅ Display cache hit rate in monitoring logs
- ✅ 3-level system prompt composition: GLOBAL + User.custom_prompt + Thread.files_context
- ✅ `/personality` command for User.custom_prompt management (see below)

#### /personality Command

The `/personality` command allows users to customize their assistant's behavior.

**Location:** `bot/telegram/handlers/personality.py`

**Features:**
- View current custom prompt
- Edit custom prompt (FSM state: `PersonalityStates.waiting_for_text`)
- Clear custom prompt
- Inline keyboard for all actions

**Inline Keyboard Actions:**
- `personality:view` - Show full custom prompt text
- `personality:edit` - Enter edit mode
- `personality:clear` - Remove custom prompt
- `personality:cancel` - Close menu

**FSM States:**
```python
class PersonalityStates(StatesGroup):
    waiting_for_text = State()  # Waiting for new personality text
```

**System Prompt Composition:**
```
1. GLOBAL_SYSTEM_PROMPT (from config.py, cached)
2. User.custom_prompt (from /personality, cached)
3. Thread.files_context (auto-generated, NOT cached)
```

**Usage Example:**
```
User: /personality
Bot: 🎭 Personality Settings
     Current personality: (not set)
     [View] [Edit] [Clear] [Cancel]

User: [Edit]
Bot: ✏️ Enter your new personality instructions...

User: Always respond in formal English.
Bot: ✅ Personality updated successfully!
```

### ✅ Phase 1.4.3: Extended Thinking & Message Batching (Completed)
- ✅ Add Interleaved Thinking beta header: `interleaved-thinking-2025-05-14`
- ✅ Handle `thinking_delta` and `signature_delta` events in streaming
- ✅ Track thinking tokens separately in usage/cost calculations
- ✅ Extended Thinking parameter: **DISABLED** until Phase 1.5 (requires saving thinking blocks to DB)
- ✅ Time-based message batching (200ms accumulation window for split messages)
- ✅ Per-thread message queues with independent processing

### ✅ Phase 1.4.4: Best Practices & Optimization (Completed)
- ✅ **System prompt rewrite**: Claude 4 style (explicit instructions, context/motivation, model identity, concise)
- ✅ **Thinking vocabulary**: use "consider"/"evaluate" instead of "think"
- ✅ **Effort parameter**: `effort: "high"` for Opus 4.5, beta header `effort-2025-11-24`
- ✅ **Token Counting API**: for requests >150K tokens, checks context window overflow
- ✅ **Cache hit rate monitoring**: logged with every request
- ✅ **Stop reason handling**: `model_context_window_exceeded`, `refusal`, `max_tokens`

### ⏸️ Deferred to Phase 1.5
- ⏸️ **Extended Thinking enabled**: Requires saving thinking blocks to DB (currently disabled at line 163-166 in client.py)
- ⏸️ **Context Management parameter**: `clear_thinking_20251015` - SDK doesn't support yet
- ⏸️ **Error recovery in streaming**: Complex partial response reconstruction
- ⏸️ **Tool use + thinking blocks**: Preserve unmodified thinking blocks when posting tool_result
- ⏸️ **Extended thinking prompting**: Reflection after tool use

### 📊 Implementation Stats
- **Files modified**: 5 files (client.py, config.py, claude.py, message_queue.py, base.py)
- **Beta headers**: 3 enabled (interleaved-thinking, context-management, effort)
- **Stop reasons handled**: 3 (model_context_window_exceeded, refusal, max_tokens)
- **Cache types**: 2 (5-minute ephemeral, 1-hour available but unused)
- **Token counting threshold**: 150K tokens

---

## Related Documents

- **[phase-1.3-claude-core.md](phase-1.3-claude-core.md)** - Current implementation
- **[phase-1.5-multimodal-tools.md](phase-1.5-multimodal-tools.md)** - Next phase
- **[CLAUDE.md](../CLAUDE.md)** - Project overview

---

## Summary

**Phase 1.4 is COMPLETE** (2026-01-09)

Phase 1.4 was a documentation-driven optimization phase. We reviewed 15 pages of official Claude API documentation, documented decisions for each feature, and implemented all features that don't require Phase 1.5 infrastructure (tool use, file storage).

### Completed Features

**Phase 1.4.1 - Model Registry:**
- 3 Claude 4.5 models with full characteristics
- Capability flags for feature detection
- Cache pricing and cost tracking
- `/model` command for model selection

**Phase 1.4.2 - Prompt Caching:**
- Conditional system prompt caching (≥1024 tokens)
- 5-minute ephemeral cache (10x cost reduction)
- Cache hit rate monitoring
- 3-level prompt composition

**Phase 1.4.3 - Extended Thinking & Message Batching:**
- Interleaved thinking beta header
- `thinking_delta` streaming support
- Thinking token tracking
- Time-based message batching (200ms window)
- Extended Thinking parameter DISABLED until Phase 1.5

**Phase 1.4.4 - Best Practices & Optimization:**
- System prompt rewritten for Claude 4 style
- Effort parameter for Opus 4.5 (`effort: "high"`)
- Token Counting API (>150K tokens)
- Cache hit rate monitoring
- Stop reason handling (context overflow, refusal, max_tokens)

### Documentation Pages Reviewed (15 total)

1. ✅ Models Overview - model registry architecture
2. ✅ What's New in 4.5 - extended thinking, interleaved thinking, effort
3. ✅ Pricing - prompt caching economics
4. ✅ Features Overview - roadmap
5. ✅ Context Windows - automatic context awareness, token counting
6. ✅ Claude 4 Best Practices - prompt engineering for Claude 4
7. ✅ Prompt Caching (Detailed) - cache invalidation, multipliers
8. ✅ Context Editing - thinking block clearing strategies
9. ✅ Extended Thinking - budget tokens, streaming, tool use
10. ✅ Effort - quality parameter for Opus 4.5
11. ✅ Streaming - thinking_delta, error recovery patterns
12. ✅ Citations - document processing with sources (Phase 1.5)
13. ✅ Token Counting - accurate token estimation API
14. ✅ Vision (Images) - Files API architecture (Phase 1.5)
15. ✅ PDF Support - document processing patterns (Phase 1.5)

### Deferred to Phase 1.5

- Extended Thinking parameter (requires DB schema for thinking blocks)
- Context Management parameter (SDK doesn't support yet)
- Tool use implementation (separate phase)
- Vision, PDF, Files API (require tool framework)
- Web Search, Web Fetch (server-side tools)
- Error recovery in streaming (complex, low priority)

### Key Metrics

- **Files modified**: 5 (client.py, config.py, claude.py, message_queue.py, base.py)
- **Beta headers**: 3 (interleaved-thinking, context-management, effort)
- **Stop reasons**: 3 handled (context overflow, refusal, max_tokens)
- **Cache hit rate**: Monitored in logs
- **Token threshold**: 150K for token counting API

**Next phase:** Phase 1.5 (Multimodal + Tools)
