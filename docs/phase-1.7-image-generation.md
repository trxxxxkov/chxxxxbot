# Phase 1.7: Image Generation (Nano Banana Pro)

**Status:** ✅ **COMPLETE**

**Purpose:** Add high-quality image generation up to 4K resolution using Google's Nano Banana Pro model (Gemini 3 Pro Image).

**Date:** January 10, 2026

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tool Definition](#tool-definition)
- [Implementation](#implementation)
- [Pricing](#pricing)
- [Testing](#testing)
- [Related Documents](#related-documents)

---

## Overview

Phase 1.7 adds image generation capabilities using Google's most advanced image model - Nano Banana Pro (gemini-3-pro-image-preview).

### Key Features

- 🎨 **High-quality generation**: Up to 4K resolution
- 🔍 **Google Search grounding**: Model can search for reference images
- 📐 **Flexible parameters**: Aspect ratios, resolutions, content policies
- 💰 **Transparent pricing**: $0.134 (1K/2K) or $0.24 (4K) per image
- 🇬🇧 **English prompts only**: Max 480 tokens
- 🖼️ **ONE image per call**: Simplicity and cost control

### Model Comparison

| Model | Resolution | Features | Cost |
|-------|-----------|----------|------|
| **Nano Banana Pro** ✅ | Up to 4K | Google Search grounding, 14 reference images | $0.134-0.24 |
| Imagen 4 Ultra | Up to 2K | Fast generation | $0.06 |
| Imagen 4 Fast | Up to 2K | Very fast | $0.02 |

**Why Nano Banana Pro?**
- Best quality for professional asset production
- Advanced reasoning capabilities
- Google Search integration for better accuracy

---

## Architecture

### Workflow

```
┌──────────────────────────────────────────────────────────────┐
│ USER: "Generate an image of a robot with a red skateboard"  │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ▼
            ┌────────────────────┐
            │ Claude calls       │
            │ generate_image     │
            │ tool with params   │
            └────────┬───────────┘
                     │
                     ▼
      ┌──────────────────────────────────┐
      │ 1. Call Google Gemini 3 Pro API  │
      │    model: gemini-3-pro-image-    │
      │           preview                │
      │    prompt: "Robot with red..."   │
      │    aspect_ratio: "1:1"           │
      │    image_size: "2K"              │
      └────────┬──────────────────────────┘
               │
               ▼
      ┌────────────────────────────┐
      │ 2. Extract image bytes     │
      │    from response.parts     │
      │    (inline_data.data)      │
      └────────┬───────────────────┘
               │
               ▼
      ┌────────────────────────────┐
      │ 3. Return _file_contents   │
      │    for automatic delivery  │
      └────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────┐
│ Claude handler processes _file_contents:         │
│  a. Upload to Files API (for analyze_image)      │
│  b. Save to user_files (source=ASSISTANT)        │
│  c. Send photo to Telegram user                  │
│  d. Add to context ("Available files")           │
└──────────────────────┬───────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ USER receives:  │
              │ - Photo message │
              │ - Claude text   │
              └─────────────────┘
```

### File Lifecycle

1. **Generation**: Google API generates image (PNG format)
2. **Upload**: Uploaded to Files API with 24h TTL
3. **Storage**: Record in `user_files` table (source=ASSISTANT, type=GENERATED)
4. **Delivery**: Sent to user as Telegram photo
5. **Availability**: Added to context for future reference (can be analyzed with `analyze_image`)

---

## Tool Definition

### Tool Schema

```python
GENERATE_IMAGE_TOOL = {
    "name": "generate_image",
    "description": (
        "Generate high-quality images up to 4K resolution using Google's "
        "Nano Banana Pro (Gemini 3 Pro Image) model. Supports advanced "
        "features like Google Search grounding for reference images. "
        "Always generates ONE image per call. English prompts only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed image description in English..."
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["1:1", "3:4", "4:3", "9:16", "16:9"],
                "description": "Image aspect ratio. Default: 1:1"
            },
            "image_size": {
                "type": "string",
                "enum": ["1K", "2K", "4K"],
                "description": "Resolution. Default: 2K"
            },
            "person_generation": {
                "type": "string",
                "enum": ["dont_allow", "allow_adult", "allow_all"],
                "description": "Control people generation. Default: allow_adult"
            }
        },
        "required": ["prompt"]
    }
}
```

### Parameters

| Parameter | Type | Options | Default | Description |
|-----------|------|---------|---------|-------------|
| `prompt` | string | - | **required** | English description (max 480 tokens) |
| `aspect_ratio` | string | 1:1, 3:4, 4:3, 9:16, 16:9 | `1:1` | Image aspect ratio |
| `image_size` | string | 1K, 2K, 4K | `2K` | Resolution (~1024px, ~2048px, ~4096px) |
| `person_generation` | string | dont_allow, allow_adult, allow_all | `allow_adult` | People in images |

### Return Format

```python
{
    "success": "true",
    "cost_usd": "0.134",
    "parameters_used": {
        "aspect_ratio": "16:9",
        "image_size": "2K",
        "person_generation": "allow_adult",
        "model": "gemini-3-pro-image-preview"
    },
    "_file_contents": [{
        "filename": "generated_20260110_162045.png",
        "content": b"<image bytes>",
        "mime_type": "image/png"
    }],
    "generated_text": "Optional descriptive text from model"
}
```

**Note:** `_file_contents` triggers automatic processing in `claude_handler.py`:
- Upload to Files API
- Save to database
- Send to Telegram user
- Add delivery confirmation to tool result

---

## Implementation

### Files Modified/Created

#### New Files
- **`bot/core/tools/generate_image.py`**: Tool implementation
  - `get_client()`: Lazy Google GenAI client initialization
  - `generate_image()`: Main generation function
  - `GENERATE_IMAGE_TOOL`: Tool schema

#### Modified Files
- **`bot/core/tools/registry.py`**: Tool registration
  - Added `generate_image` to `TOOL_DEFINITIONS`
  - Added `generate_image` to `TOOL_EXECUTORS`
  - Updated `execute_tool()` docstring

- **`bot/config.py`**: System prompt
  - Added **Image Generation** section with tool description

- **`bot/pyproject.toml`**: Dependencies
  - Added `google-genai>=1.0.0`
  - Added `pillow>=10.0.0`

- **`bot/Dockerfile`**: Build configuration
  - Added `google-genai>=1.0.0` to pip install
  - Added `pillow>=10.0.0` to pip install

- **`compose.yaml`**: Docker secrets
  - Added `google_api_key` secret mapping

### Key Code Snippets

#### Generate Image (Simplified)

```python
async def generate_image(
    prompt: str,
    bot: 'Bot',
    session: 'AsyncSession',
    aspect_ratio: str = "1:1",
    image_size: str = "2K",
    person_generation: str = "allow_adult",
) -> Dict[str, Any]:
    # 1. Call Google API
    client = get_client()
    response = client.models.generate_content(
        model="gemini-3-pro-image-preview",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE'],
            image_config=genai_types.ImageConfig(
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                person_generation=person_generation,
            ),
        ),
    )

    # 2. Extract image bytes
    for part in response.parts:
        if part.inline_data is not None:
            image_bytes = part.inline_data.data
            break

    # 3. Return for automatic delivery
    return {
        "success": "true",
        "cost_usd": f"{cost_usd:.3f}",
        "_file_contents": [{
            "filename": f"generated_{timestamp}.png",
            "content": image_bytes,
            "mime_type": "image/png",
        }],
    }
```

#### System Prompt Addition

```
**Image Generation:**
- `generate_image`: Create high-quality images up to 4K resolution
  - Model: Google Nano Banana Pro (gemini-3-pro-image-preview)
  - Features: Up to 4K resolution, Google Search grounding
  - Parameters: aspect_ratio, image_size, person_generation
  - Cost: $0.134 per image (1K/2K), $0.24 per image (4K)
  - English prompts only (max 480 tokens)
  - Generates ONE image per call
```

---

## Pricing

### Cost Structure

| Resolution | Cost per Image | Use Case |
|-----------|----------------|----------|
| **1K** (~1024px) | **$0.134** | Quick iterations, thumbnails |
| **2K** (~2048px) | **$0.134** | Standard high-quality (recommended) |
| **4K** (~4096px) | **$0.240** | Professional assets, printing |

### Cost Tracking

- Cost calculated immediately after generation
- Included in tool result: `"cost_usd": "0.134"`
- Logged in structured logs: `cost_usd=0.134`
- Can be tracked per user for billing (Phase 2.1: Payment System)

### Example Costs

```python
# Standard generation (2K)
"Generate a sunset over mountains" → $0.134

# High resolution (4K)
"Generate a sunset over mountains", image_size="4K" → $0.240

# Multiple images (user must call tool multiple times)
"Generate 3 different sunsets" → 3 × $0.134 = $0.402
```

---

## Testing

### Manual Testing

#### Test 1: Basic Generation

**Prompt to bot:**
```
Сгенерируй изображение робота с красным скейтбордом в стиле cyberpunk
```

**Expected behavior:**
1. Claude calls `generate_image` tool
2. User receives PNG image (robot with red skateboard)
3. Claude responds with description
4. Image appears in "Available files"

**Logs to check:**
```json
{
  "event": "tools.generate_image.called",
  "prompt_length": 50,
  "aspect_ratio": "1:1",
  "image_size": "2K"
}
{
  "event": "tools.generate_image.complete",
  "cost_usd": 0.134,
  "size_bytes": 245678
}
```

#### Test 2: Custom Parameters

**Prompt to bot:**
```
Generate a wide landscape image in 4K resolution showing a futuristic city at night
```

**Expected behavior:**
1. Claude infers `aspect_ratio: "16:9"`, `image_size: "4K"`
2. User receives 4K widescreen image
3. Cost: $0.240

#### Test 3: Content Policy

**Prompt to bot:**
```
Generate an image of [something that violates content policy]
```

**Expected behavior:**
1. Google API blocks generation
2. Tool returns: `"error": "Content policy violation: ..."`
3. Claude informs user and suggests alternative prompt

### Integration Points

- ✅ **Files API**: Image uploaded successfully
- ✅ **Database**: Record in `user_files` table
- ✅ **Telegram**: Photo delivered to user
- ✅ **Context**: Image available for `analyze_image`

### Unit Tests (Future)

```python
# tests/core/tools/test_generate_image.py
async def test_generate_image_basic():
    """Test basic image generation with default parameters."""
    # Mock Google API response
    # Verify: image_bytes extracted, cost calculated, _file_contents present

async def test_generate_image_4k():
    """Test 4K generation costs $0.240."""

async def test_generate_image_content_policy():
    """Test content policy violation handling."""

async def test_generate_image_custom_aspect():
    """Test custom aspect ratio (16:9)."""
```

---

## Related Documents

- [Phase 1.5: Multimodal + Tools](phase-1.5-multimodal-tools.md) - Files API integration
- [Phase 1.6: Multimodal Support](phase-1.6-multimodal-support.md) - Media handling
- [Google Nano Banana Documentation](https://ai.google.dev/gemini-api/docs/image-generation)
- [Google Gen AI SDK](https://googleapis.github.io/python-genai/)

---

## Future Enhancements

### Phase 2.1: Payment System
- Track generation costs per user
- Pre-request balance validation
- Cost attribution and reporting

### Phase 3.4: Other LLM Providers
- Add DALL-E 3 (OpenAI) as alternative
- Add Stable Diffusion models
- Unified generation interface

### Possible Features
- Image-to-image editing (requires reference image support)
- Style transfer
- Batch generation (multiple calls with different prompts)
- Generation history and favorites
