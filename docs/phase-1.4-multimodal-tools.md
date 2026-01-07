# Claude Integration: Phase 1.4 (Multimodal + Tools)

Multimodal support (images, voice, files) and tools framework (code execution, image generation) with prompt caching and extended thinking optimizations.

**Status:** 📋 **PLANNED**

---

## Table of Contents

- [Overview](#overview)
- [Multimodal Support](#multimodal-support)
- [Tools Framework](#tools-framework)
- [Optimizations](#optimizations)
- [API Documentation Process](#api-documentation-process)
- [Implementation Plan](#implementation-plan)
- [Related Documents](#related-documents)

---

## Overview

Phase 1.4 extends Phase 1.3's text-only capabilities with multimodal inputs and a flexible tools framework.

### Goals

1. **Multimodal inputs** - Handle images, voice messages, and arbitrary files
2. **Tools framework** - Modular system for adding new capabilities
3. **Performance optimizations** - Prompt caching and extended thinking
4. **Production-ready** - Error handling, logging, testing for all new features

### Prerequisites

- ✅ Phase 1.3 complete (text conversations working)
- ✅ Database schema supports attachments (JSONB)
- ✅ Telegram file download infrastructure
- ⏳ Review Claude API documentation for all features

---

## Multimodal Support

### Vision (Image Processing)

**Capability:** User sends photo, Claude analyzes it and responds.

#### Flow

1. User sends photo to Telegram (with optional text caption)
2. Bot downloads photo from Telegram servers
3. Encode image to base64 (or use URL if Claude supports it)
4. Add image content block to Claude API request
5. Claude analyzes image and streams response
6. Save image metadata in `Message.attachments` (JSONB)

#### Telegram → Claude API Format

**Telegram input:**
```python
message.photo  # Array of PhotoSize (different resolutions)
message.caption  # Optional text caption
```

**Claude API request:**
```python
{
    "role": "user",
    "content": [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",  # or "image/png", "image/gif", "image/webp"
                "data": "<base64_encoded_image>"
            }
        },
        {
            "type": "text",
            "text": "What's in this image?"  # User's caption or default prompt
        }
    ]
}
```

#### Implementation

**File:** `bot/telegram/handlers/vision.py` (new)

```python
from aiogram import Router, F, types
from sqlalchemy.ext.asyncio import AsyncSession
import base64
from io import BytesIO

router = Router(name="vision_handler")

@router.message(F.photo)
async def handle_photo_message(message: types.Message, session: AsyncSession):
    """Handle photo message with Claude vision."""

    # Get largest photo
    photo = message.photo[-1]

    # Download photo from Telegram
    file = await message.bot.get_file(photo.file_id)
    photo_bytes = BytesIO()
    await message.bot.download_file(file.file_path, photo_bytes)

    # Encode to base64
    photo_base64 = base64.b64encode(photo_bytes.getvalue()).decode('utf-8')

    # Determine media type
    media_type = "image/jpeg"  # Most photos are JPEG

    # Build multi-part message
    llm_message = Message(
        role="user",
        content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": photo_base64
                }
            },
            {
                "type": "text",
                "text": message.caption or "Describe this image in detail."
            }
        ]
    )

    # Save to database with attachment metadata
    await msg_repo.create_message(
        chat_id=message.chat.id,
        message_id=message.message_id,
        thread_id=thread.id,
        from_user_id=message.from_user.id,
        date=int(message.date.timestamp()),
        role=MessageRole.USER,
        text_content=message.caption,
        attachments=[{
            "type": "photo",
            "file_id": photo.file_id,
            "file_unique_id": photo.file_unique_id,
            "width": photo.width,
            "height": photo.height,
            "file_size": photo.file_size,
        }]
    )

    # Continue with normal Claude streaming flow...
```

**Considerations:**
- Large images increase token usage significantly
- Need to handle image size limits (check Claude API docs)
- Store original file_id for future retrieval
- Log image dimensions and file size for monitoring

---

### Voice Messages (Audio Transcription)

**Capability:** User sends voice message, bot transcribes it and processes with Claude.

#### Flow

1. User sends voice message to Telegram
2. Bot downloads audio file (OGG/Opus format)
3. Transcribe using external API (options below)
4. Send transcribed text to Claude as regular message
5. Save audio metadata in `Message.attachments`

#### Transcription Options

**Option A: OpenAI Whisper API**
- Pros: High accuracy, supports many languages, official API
- Cons: Additional cost, external dependency
- Implementation: Use `openai` Python SDK

**Option B: Local Whisper**
- Pros: No external API cost, privacy
- Cons: Requires GPU, container complexity, slower
- Implementation: Run Whisper model in separate container

**Option C: Claude Audio (if available)**
- Pros: Single vendor, no external dependency
- Cons: Check Claude API docs for availability
- Implementation: Send audio directly to Claude

#### Implementation (Option A: Whisper API)

**File:** `bot/telegram/handlers/voice.py` (new)

```python
from aiogram import Router, F, types
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI
from io import BytesIO

router = Router(name="voice_handler")
whisper_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

@router.message(F.voice)
async def handle_voice_message(message: types.Message, session: AsyncSession):
    """Handle voice message with transcription."""

    # Download voice file
    file = await message.bot.get_file(message.voice.file_id)
    audio_bytes = BytesIO()
    await message.bot.download_file(file.file_path, audio_bytes)
    audio_bytes.seek(0)

    # Transcribe using Whisper API
    transcription = await whisper_client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_bytes,
        language=message.from_user.language_code  # Hint for better accuracy
    )

    transcribed_text = transcription.text

    logger.info("voice.transcribed",
                user_id=message.from_user.id,
                duration=message.voice.duration,
                text_length=len(transcribed_text))

    # Save to database
    await msg_repo.create_message(
        chat_id=message.chat.id,
        message_id=message.message_id,
        thread_id=thread.id,
        from_user_id=message.from_user.id,
        date=int(message.date.timestamp()),
        role=MessageRole.USER,
        text_content=transcribed_text,  # Transcribed text as content
        attachments=[{
            "type": "voice",
            "file_id": message.voice.file_id,
            "file_unique_id": message.voice.file_unique_id,
            "duration": message.voice.duration,
            "mime_type": message.voice.mime_type,
            "file_size": message.voice.file_size,
        }]
    )

    # Continue with normal Claude streaming flow...
    # Use transcribed_text as user message content
```

**Considerations:**
- Add transcription cost to total cost tracking (Phase 2.1)
- Handle transcription errors gracefully
- Support multiple languages (use user's language_code as hint)
- Consider showing transcription to user for verification

---

### Arbitrary Files (Document Processing)

**Capability:** User sends file (PDF, code, data), bot processes it and discusses with Claude.

#### Flow

1. User sends document to Telegram
2. Bot downloads file
3. Determine file type and select appropriate tool:
   - **Text files** (.txt, .md, .py, .js, etc.) → Extract text directly
   - **PDFs** → Extract text using PyPDF2 or similar
   - **Office docs** (.docx, .xlsx) → Extract with python-docx/openpyxl
   - **Data files** (.csv, .json) → Parse and summarize
   - **Code files** → Analyze with code execution tool
4. Include extracted content in Claude request
5. Save file metadata in attachments

#### Implementation

**File:** `bot/telegram/handlers/document.py` (new)

```python
from aiogram import Router, F, types
from sqlalchemy.ext.asyncio import AsyncSession
import mimetypes
from io import BytesIO

router = Router(name="document_handler")

# File processors registry
FILE_PROCESSORS = {
    "text/plain": process_text_file,
    "application/pdf": process_pdf_file,
    "text/x-python": process_code_file,
    "application/json": process_json_file,
    # ... more processors
}

@router.message(F.document)
async def handle_document_message(message: types.Message, session: AsyncSession):
    """Handle document with appropriate processor."""

    doc = message.document

    # Determine MIME type
    mime_type = doc.mime_type or mimetypes.guess_type(doc.file_name)[0]

    # Download file
    file = await message.bot.get_file(doc.file_id)
    file_bytes = BytesIO()
    await message.bot.download_file(file.file_path, file_bytes)
    file_bytes.seek(0)

    # Process file
    processor = FILE_PROCESSORS.get(mime_type, process_generic_file)
    extracted_content = await processor(file_bytes, doc.file_name)

    logger.info("document.processed",
                file_name=doc.file_name,
                mime_type=mime_type,
                file_size=doc.file_size,
                content_length=len(extracted_content))

    # Build message with file content
    user_message = f"File: {doc.file_name}\n\n{extracted_content}"
    if message.caption:
        user_message = f"{message.caption}\n\n{user_message}"

    # Save to database
    await msg_repo.create_message(
        chat_id=message.chat.id,
        message_id=message.message_id,
        thread_id=thread.id,
        from_user_id=message.from_user.id,
        date=int(message.date.timestamp()),
        role=MessageRole.USER,
        text_content=user_message,
        attachments=[{
            "type": "document",
            "file_id": doc.file_id,
            "file_unique_id": doc.file_unique_id,
            "file_name": doc.file_name,
            "mime_type": mime_type,
            "file_size": doc.file_size,
        }]
    )

    # Continue with normal Claude streaming flow...


async def process_text_file(file_bytes: BytesIO, filename: str) -> str:
    """Extract text from plain text file."""
    return file_bytes.read().decode('utf-8', errors='ignore')


async def process_pdf_file(file_bytes: BytesIO, filename: str) -> str:
    """Extract text from PDF."""
    import PyPDF2
    reader = PyPDF2.PdfReader(file_bytes)
    text = "\n\n".join(page.extract_text() for page in reader.pages)
    return text


async def process_code_file(file_bytes: BytesIO, filename: str) -> str:
    """Extract code with syntax highlighting markers."""
    code = file_bytes.read().decode('utf-8', errors='ignore')
    extension = filename.split('.')[-1]
    return f"```{extension}\n{code}\n```"
```

**Considerations:**
- Limit file size (e.g., 10MB max)
- Handle encoding errors gracefully
- Large files may exceed token limits - truncate with warning
- Security: sandbox file processing to prevent malicious files

---

## Tools Framework

### Architecture

Modular system allowing Claude to use external tools during conversation.

#### Abstract Tool Interface

**File:** `bot/core/tools/base.py` (new)

```python
from abc import ABC, abstractmethod
from typing import Any, Dict

class Tool(ABC):
    """Abstract interface for Claude tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name for Claude API."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for Claude (how and when to use it)."""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> Dict[str, Any]:
        """JSON schema for tool input (OpenAPI format)."""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute tool and return result as string.

        Args:
            **kwargs: Tool input parameters (validated against input_schema).

        Returns:
            Tool execution result (human-readable text).

        Raises:
            ToolExecutionError: If tool execution fails.
        """
        pass
```

#### Tool Registry

**File:** `bot/core/tools/registry.py` (new)

```python
from typing import Dict, List
from core.tools.base import Tool

class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.info("tool.registered", tool_name=tool.name)

    def unregister(self, tool_name: str) -> None:
        """Unregister a tool."""
        if tool_name in self._tools:
            del self._tools[tool_name]
            logger.info("tool.unregistered", tool_name=tool_name)

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions for Claude API.

        Returns:
            List of tool definitions in Claude API format.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema
            }
            for tool in self._tools.values()
        ]

    async def execute_tool(self, name: str, tool_input: Dict[str, Any]) -> str:
        """Execute a tool by name.

        Args:
            name: Tool name.
            tool_input: Tool input parameters.

        Returns:
            Tool execution result.

        Raises:
            ValueError: If tool not found.
            ToolExecutionError: If execution fails.
        """
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        logger.info("tool.execute.start", tool_name=name, input=tool_input)

        try:
            result = await tool.execute(**tool_input)
            logger.info("tool.execute.success", tool_name=name, result_length=len(result))
            return result
        except Exception as e:
            logger.error("tool.execute.failed", tool_name=name, error=str(e))
            raise ToolExecutionError(f"Tool {name} failed: {str(e)}")

# Global registry instance
tool_registry = ToolRegistry()
```

---

### Example Tool: Code Execution

**File:** `bot/core/tools/code_execution.py` (new)

```python
import asyncio
import docker
from core.tools.base import Tool

class CodeExecutionTool(Tool):
    """Execute Python code in isolated Docker container."""

    def __init__(self):
        self.docker_client = docker.from_env()
        self.timeout = 30  # seconds
        self.memory_limit = "256m"

    @property
    def name(self) -> str:
        return "execute_python"

    @property
    def description(self) -> str:
        return (
            "Execute Python code in an isolated sandbox environment. "
            "Use this to run calculations, data analysis, or test code snippets. "
            "The environment has common libraries: numpy, pandas, matplotlib. "
            "No network access. 30 second timeout."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute"
                }
            },
            "required": ["code"]
        }

    async def execute(self, code: str) -> str:
        """Execute Python code in Docker container.

        Args:
            code: Python code to execute.

        Returns:
            Combined stdout and stderr from execution.
        """
        logger.info("code_execution.start", code_length=len(code))

        try:
            # Run code in Docker container
            container = self.docker_client.containers.run(
                image="python:3.12-slim",  # Base image
                command=["python", "-c", code],
                mem_limit=self.memory_limit,
                network_disabled=True,  # No network access
                remove=True,  # Auto-remove after execution
                detach=False,
                stdout=True,
                stderr=True,
                timeout=self.timeout
            )

            output = container.decode('utf-8')
            logger.info("code_execution.success", output_length=len(output))
            return output

        except docker.errors.ContainerError as e:
            # Code executed but raised error
            error_output = e.stderr.decode('utf-8')
            logger.warning("code_execution.error", error=error_output)
            return f"Error:\n{error_output}"

        except asyncio.TimeoutError:
            logger.error("code_execution.timeout")
            return f"Error: Execution timed out after {self.timeout} seconds"

        except Exception as e:
            logger.error("code_execution.failed", error=str(e))
            raise ToolExecutionError(f"Failed to execute code: {str(e)}")
```

**Security considerations:**
- No network access (network_disabled=True)
- Memory limits to prevent DoS
- Timeout to prevent infinite loops
- Container auto-removed after execution
- No filesystem persistence between runs
- Consider using gVisor or similar for additional sandboxing

---

### Example Tool: Image Generation

**File:** `bot/core/tools/image_generation.py` (new)

```python
from core.tools.base import Tool
from openai import AsyncOpenAI
import base64

class ImageGenerationTool(Tool):
    """Generate images using DALL-E API."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    @property
    def name(self) -> str:
        return "generate_image"

    @property
    def description(self) -> str:
        return (
            "Generate an image based on a text description using DALL-E. "
            "Use this when the user asks to create, draw, or visualize something. "
            "Provide detailed descriptions for better results."
        )

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate"
                },
                "size": {
                    "type": "string",
                    "enum": ["1024x1024", "1792x1024", "1024x1792"],
                    "description": "Image size (default: 1024x1024)"
                }
            },
            "required": ["prompt"]
        }

    async def execute(self, prompt: str, size: str = "1024x1024") -> str:
        """Generate image using DALL-E.

        Args:
            prompt: Image description.
            size: Image dimensions.

        Returns:
            Base64-encoded image data with metadata.
        """
        logger.info("image_generation.start", prompt_length=len(prompt), size=size)

        try:
            response = await self.client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality="standard",
                n=1,
                response_format="b64_json"
            )

            image_b64 = response.data[0].b64_json
            revised_prompt = response.data[0].revised_prompt

            logger.info("image_generation.success",
                        image_size=len(image_b64),
                        revised_prompt=revised_prompt)

            # Return special marker for handler to send as photo
            return f"IMAGE_GENERATED:{image_b64}"

        except Exception as e:
            logger.error("image_generation.failed", error=str(e))
            raise ToolExecutionError(f"Failed to generate image: {str(e)}")
```

---

### Tool Execution Flow

When Claude requests a tool during conversation:

1. **Claude streams response** and requests tool use
2. **Handler detects tool request** in stream
3. **Pause streaming**, extract tool name and input
4. **Execute tool** via ToolRegistry
5. **Send tool result** back to Claude in new API call
6. **Claude continues streaming** with tool result incorporated

**Updated handler pseudocode:**

```python
async def handle_with_tools(message, session):
    # ... build context ...

    request = LLMRequest(
        messages=context,
        system_prompt=GLOBAL_SYSTEM_PROMPT,
        model=model_config.name,
        tools=tool_registry.get_tool_definitions()  # Add tools to request
    )

    max_iterations = 5  # Prevent infinite tool loops
    iteration = 0

    while iteration < max_iterations:
        tool_uses = []
        response_text = ""

        # Stream response
        async for event in claude_provider.stream_message_with_tools(request):
            if event.type == "text":
                response_text += event.text
                # Update Telegram message...

            elif event.type == "tool_use":
                # Claude wants to use a tool
                tool_uses.append({
                    "id": event.id,
                    "name": event.name,
                    "input": event.input
                })

        # If no tools used, we're done
        if not tool_uses:
            break

        # Execute all requested tools
        tool_results = []
        for tool_use in tool_uses:
            result = await tool_registry.execute_tool(
                tool_use["name"],
                tool_use["input"]
            )
            tool_results.append({
                "tool_use_id": tool_use["id"],
                "content": result
            })

        # Add tool results to conversation and continue
        request.messages.append({
            "role": "assistant",
            "content": [
                {"type": "text", "text": response_text},
                *[{"type": "tool_use", **tu} for tu in tool_uses]
            ]
        })
        request.messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", **tr} for tr in tool_results
            ]
        })

        iteration += 1

    # Save final response...
```

---

## Optimizations

### Prompt Caching

**Goal:** Cache system prompt to reduce costs and latency on repeated requests.

**How it works:**
- Mark system prompt with `cache_control` directive
- Claude caches the prompt for ~5 minutes (check API docs)
- Subsequent requests read from cache (much cheaper)
- Cache is user-specific and expires after inactivity

**Implementation:**

```python
request = {
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 4096,
    "system": [
        {
            "type": "text",
            "text": GLOBAL_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}  # Enable caching
        }
    ],
    "messages": [...]
}
```

**Cost savings:**
- Cached prompt tokens: ~90% cheaper than input tokens
- Significantly faster response times
- Especially beneficial for long system prompts

**Logging:**
```python
logger.info("claude.stream.complete",
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
            cache_read_tokens=usage.cache_read_tokens)
```

---

### Extended Thinking

**Goal:** Improve reasoning quality for complex tasks by giving Claude more "thinking time."

**How it works:**
- Enable thinking budget in API request
- Claude uses additional tokens for internal reasoning (not shown to user)
- Better results for complex problems (math, coding, analysis)
- Thinking tokens counted separately for billing

**Implementation:**

```python
request = {
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 4096,
    "thinking": {
        "type": "enabled",
        "budget_tokens": 2000  # Allow 2000 tokens for thinking
    },
    "messages": [...]
}
```

**Use cases:**
- Complex code generation
- Multi-step mathematical reasoning
- Detailed technical analysis
- Strategic planning tasks

**When to enable:**
- User explicitly requests detailed reasoning
- Complex queries detected (code, math, multi-step)
- Optional: Add `/think` command to toggle extended thinking

---

## API Documentation Process

Before implementation, thoroughly review Claude API documentation.

### Process

For each API page:
1. **Read full page** using WebFetch or WebSearch
2. **Discuss with user** - what to adopt, what to skip
3. **Document decisions** in this file under "API Pages Reviewed"
4. **Link to page** with summary of adopted patterns
5. **Update code examples** to reflect official best practices

### Pages to Review

Must read before Phase 1.4 implementation:

- [ ] **Messages API** - Request/response format, streaming
- [ ] **Vision** - Image input formats, sizing, token usage
- [ ] **Tool Use** - Tool definition, execution flow, multi-turn
- [ ] **Prompt Caching** - Cache control, pricing, lifetime
- [ ] **Extended Thinking** - When to use, token budget, billing
- [ ] **Error Handling** - Error codes, retry strategies, rate limits
- [ ] **Best Practices** - Prompt engineering, context management, performance

### Documentation Format

```markdown
### [Page Title]

**Link:** https://docs.anthropic.com/...

**Date reviewed:** YYYY-MM-DD

**What we adopted:**
- Feature 1: Implementation details, file location
- Feature 2: Implementation details, file location

**What we skipped:**
- Feature X: Reason (e.g., not needed for our use case)

**Key insights:**
- Important best practice or gotcha
```

---

## Implementation Plan

### Phase 1.4 Checklist

#### 1. API Documentation Review
- [ ] Read all required API pages (list above)
- [ ] Document decisions for each page
- [ ] Update code examples with official patterns
- [ ] Verify pricing for all new features

#### 2. Multimodal Support
- [ ] Vision handler (`bot/telegram/handlers/vision.py`)
- [ ] Voice handler with Whisper API (`bot/telegram/handlers/voice.py`)
- [ ] Document handler (`bot/telegram/handlers/document.py`)
- [ ] File processors for common formats
- [ ] Update Message model if needed (should be compatible)
- [ ] Tests for each handler

#### 3. Tools Framework
- [ ] Abstract Tool interface (`bot/core/tools/base.py`)
- [ ] Tool registry (`bot/core/tools/registry.py`)
- [ ] Code execution tool (`bot/core/tools/code_execution.py`)
- [ ] Image generation tool (`bot/core/tools/image_generation.py`)
- [ ] Update Claude client to support tools
- [ ] Handler update for tool execution flow
- [ ] Tests for tool execution

#### 4. Optimizations
- [ ] Implement prompt caching in Claude client
- [ ] Add extended thinking support
- [ ] Update token usage tracking for cache/thinking tokens
- [ ] Add configuration for when to use extended thinking

#### 5. Configuration & Secrets
- [ ] Add Whisper API key to secrets (if using OpenAI)
- [ ] Add DALL-E API key to secrets (if using image generation)
- [ ] Add tool enable/disable flags to config
- [ ] Update docker-compose.yaml with new secrets

#### 6. Testing
- [ ] Unit tests for each tool
- [ ] Integration tests with real APIs
- [ ] Manual testing for multimodal inputs
- [ ] Load testing for tool execution
- [ ] Security testing for code execution sandbox

#### 7. Documentation
- [ ] Update CLAUDE.md with Phase 1.4 status
- [ ] Complete API documentation review section
- [ ] Add usage examples for each feature
- [ ] Update bot-structure.md with new files

---

## Related Documents

- **[phase-1.3-claude-core.md](phase-1.3-claude-core.md)** - Previous phase (implemented)
- **[phase-2.1-payment-system.md](phase-2.1-payment-system.md)** - Next phase: Payment system
- **[phase-1.2-database.md](phase-1.2-database.md)** - Database schema (attachments support)
- **[phase-1.1-bot-structure.md](phase-1.1-bot-structure.md)** - File structure and dependencies
- **[CLAUDE.md](../CLAUDE.md)** - Project status and roadmap

---

## Summary

Phase 1.4 transforms the bot from text-only to a full multimodal assistant with tools. Key additions:

- **Vision** - Analyze images sent by users
- **Voice** - Transcribe and process voice messages
- **Files** - Handle documents and code files
- **Tools** - Extensible framework for code execution, image generation, etc.
- **Optimizations** - Prompt caching and extended thinking for better performance

The modular architecture allows easy addition of new tools without rewriting existing code. Each component has clear responsibilities and comprehensive error handling.
