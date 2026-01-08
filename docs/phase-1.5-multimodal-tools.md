# Claude Integration: Phase 1.5 (Multimodal + Tools)

Multimodal support (images, voice, files) and tools framework (code execution, image generation) with prompt caching and extended thinking.

**Status:** 📋 **PLANNED**

---

## Table of Contents

- [Overview](#overview)
- [Multimodal Support](#multimodal-support)
- [Tools Framework](#tools-framework)
- [Optimizations](#optimizations)
- [Implementation Plan](#implementation-plan)
- [Related Documents](#related-documents)

---

## Overview

Phase 1.5 adds multimodal inputs and tools framework to the bot.

### Prerequisites

- ✅ Phase 1.3 complete (text conversations)
- ✅ Phase 1.4 complete (advanced API features, best practices)
- ✅ Database supports attachments (JSONB)
- ✅ Telegram file download working

### Scope

**Multimodal:**
- Images (vision) - user sends photo, Claude analyzes
- Voice messages - transcribe and process
- Files (PDF, code, data) - extract content and discuss

**Tools:**
- Abstract tool interface
- Tool registry (easy to add/remove tools)
- Code execution tool (sandboxed)
- Image generation tool (DALL-E or similar)

**Optimizations:**
- Prompt caching (cache system prompt)
- Extended thinking (for complex tasks)

---

## Multimodal Support

### Vision (Images)

**Flow:**
1. User sends photo to Telegram
2. Download and encode to base64
3. Add image block to Claude request
4. Stream response
5. Save metadata in database

**Claude API format:**
```python
{
    "role": "user",
    "content": [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": "<base64_image>"
            }
        },
        {
            "type": "text",
            "text": "What's in this image?"
        }
    ]
}
```

**Implementation:**
- Handler: `bot/telegram/handlers/vision.py`
- Download largest photo from Telegram
- Encode to base64
- Add to conversation context
- Track in `Message.attachments` JSONB

---

### Voice Messages

**Flow:**
1. User sends voice message
2. Download audio file
3. Transcribe (Whisper API or similar)
4. Send transcribed text to Claude
5. Save audio metadata

**Options:**
- **Option A:** OpenAI Whisper API (accurate, external)
- **Option B:** Local Whisper (privacy, requires GPU)
- **Option C:** Claude audio if available (check docs)

**Implementation:**
- Handler: `bot/telegram/handlers/voice.py`
- Transcription service wrapper
- Send transcribed text as regular message
- Track in `Message.attachments`

---

### Files (Documents)

**Flow:**
1. User sends file (PDF, code, CSV, etc.)
2. Download file
3. Extract content based on type:
   - Text files → read directly
   - PDFs → extract text (PyPDF2)
   - Office → extract (python-docx, openpyxl)
   - Code → include with syntax highlighting
4. Add to message context
5. Save metadata

**Implementation:**
- Handler: `bot/telegram/handlers/document.py`
- File processors registry by MIME type
- Security: size limits, sandboxing
- Track in `Message.attachments`

---

## Tools Framework

### Architecture

**Components:**
1. **Abstract Tool interface** - base class for all tools
2. **Tool registry** - central registry, easy to add/remove
3. **Execution flow** - Claude requests tool → execute → continue

**Base interface:**
```python
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name for Claude."""

    @property
    @abstractmethod
    def description(self) -> str:
        """When and how to use this tool."""

    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        """JSON schema for input validation."""

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute tool, return result."""
```

---

### Tool Registry

**Purpose:** Central place to register/unregister tools.

**Key methods:**
- `register(tool)` - add tool
- `unregister(name)` - remove tool
- `get_tool_definitions()` - for Claude API
- `execute_tool(name, input)` - run tool

**Usage:**
```python
# Global registry
tool_registry = ToolRegistry()

# Register tools
tool_registry.register(CodeExecutionTool())
tool_registry.register(ImageGenerationTool())

# Pass to Claude
tools = tool_registry.get_tool_definitions()
```

---

### Code Execution Tool

**Purpose:** Run Python code in isolated Docker container.

**Features:**
- Sandboxed execution (no network, memory limits)
- Common libraries available (numpy, pandas)
- 30 second timeout
- Return stdout/stderr

**Implementation:**
- Use Docker API
- Pre-built image with dependencies
- Auto-cleanup after execution
- Security: no persistence, no network

---

### Image Generation Tool

**Purpose:** Generate images from text descriptions.

**Options:**
- DALL-E 3 via OpenAI API
- Stable Diffusion (local or API)
- Other image generation services

**Flow:**
1. Claude calls tool with prompt
2. Generate image via API
3. Return base64 or URL
4. Handler sends image to Telegram

---

### Tool Execution Flow

**Multi-turn conversation:**
1. Claude streams response and requests tool
2. Pause stream, extract tool request
3. Execute tool via registry
4. Add tool result to conversation
5. Claude continues with result

**Handler updates:**
- Detect tool use in stream
- Execute tools
- Continue conversation with results
- Max iterations to prevent loops

---

## Optimizations

### Prompt Caching

**Goal:** Cache system prompt to reduce cost and latency.

**How it works:**
- Mark system prompt with `cache_control`
- Claude caches for ~5 minutes
- Subsequent requests read from cache (~90% cheaper)

**Implementation:**
```python
{
    "system": [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        }
    ],
    "messages": [...]
}
```

**Benefits:**
- 90% cost reduction on cached tokens
- Faster responses
- Especially useful for long system prompts

---

### Extended Thinking

**Goal:** Better reasoning for complex tasks.

**How it works:**
- Enable thinking budget in request
- Claude uses tokens for internal reasoning
- Not shown to user
- Better results for complex problems

**Implementation:**
```python
{
    "model": "claude-sonnet-4-5-20250929",
    "thinking": {
        "type": "enabled",
        "budget_tokens": 2000
    },
    "messages": [...]
}
```

**Use cases:**
- Complex code generation
- Multi-step reasoning
- Mathematical problems
- Technical analysis

---

## Implementation Plan

### Phase 1.5 Checklist

#### Multimodal Support
- [ ] Vision handler for photos
- [ ] Voice transcription (choose service)
- [ ] Document handlers (PDF, Office, code)
- [ ] File size limits and validation
- [ ] Update database for multimodal messages

#### Tools Framework
- [ ] Abstract Tool interface
- [ ] Tool registry
- [ ] Code execution tool (Docker sandbox)
- [ ] Image generation tool (choose service)
- [ ] Tool execution flow in handler
- [ ] Max iterations protection

#### Optimizations
- [ ] Implement prompt caching
- [ ] Add extended thinking support
- [ ] Update token usage tracking
- [ ] Configuration for when to use features

#### Testing & Documentation
- [ ] Tests for each tool
- [ ] Tests for multimodal handlers
- [ ] Security testing for code execution
- [ ] Update CLAUDE.md with status
- [ ] Document usage examples

---

## Related Documents

- **[phase-1.3-claude-core.md](phase-1.3-claude-core.md)** - Phase 1.3: Core implementation
- **[phase-1.4-claude-advanced-api.md](phase-1.4-claude-advanced-api.md)** - Previous phase: Advanced API
- **[phase-2.1-payment-system.md](phase-2.1-payment-system.md)** - Next phase: Payment system
- **[phase-1.2-database.md](phase-1.2-database.md)** - Database schema
- **[CLAUDE.md](../CLAUDE.md)** - Project overview

---

## Summary

Phase 1.5 extends the bot from text-only to full multimodal with tools:

- **Multimodal** - Images, voice, files
- **Tools** - Code execution, image generation, extensible framework
- **Optimizations** - Caching and extended thinking

This phase builds on optimized Phase 1.4 implementation.
