# File Context Architecture

## Implemented: Upload Context

Instead of auto-including file contents (which wastes tokens), we store
the text message that accompanied each file upload. This helps the model
understand which file the user is asking about without analyzing all files.

### Current Flow

```
User sends image + text → File uploaded to Files API → Metadata + context stored
"Here's my math homework"  → claude_file_id saved    → upload_context saved

Model sees in system prompt:
  - photo.jpg (1.2 MB, 5 min ago) [user]
    file_id: file-xxx
    context: "Here's my math homework"

When user asks "check the homework" → Model identifies correct file by context
```

### Implementation

1. **Database**: `upload_context` column in `user_files` table (migration 012)
2. **Model**: `UserFile.upload_context` field (nullable string)
3. **Repository**: `UserFileRepository.create()` accepts `upload_context` parameter
4. **Pipeline**: `processor.py` passes `processed.text` as `upload_context`
5. **Caching**: `helpers.py` includes `upload_context` in cache serialization
6. **Display**: `format_unified_files_section()` shows context for each file

### Architecture Universality

The file system is universal and works with any files from any sources:

| Source | How upload_context is set |
|--------|--------------------------|
| User upload | Text message sent with file |
| Assistant generated | Tool can set context (e.g., "Generated plot") |
| Pending files | Preview text from exec_cache |

### File Types Supported

All file types work uniformly through the same architecture:
- IMAGE (jpg, png, gif, webp)
- PDF
- DOCUMENT (txt, csv, etc.)
- AUDIO (mp3, flac, wav)
- VOICE (ogg/opus from Telegram)
- VIDEO (mp4, mov)
- GENERATED (tool outputs)

### Tools for File Analysis

Model uses these tools to read file contents when needed:
- `analyze_image(file_id)` - Vision analysis
- `analyze_pdf(file_id)` - PDF text + visual
- `transcribe_audio(file_id)` - Speech-to-text
- `execute_python` with `file_inputs` - Process any file

---

## Alternative: Auto-Include (NOT implemented)

Auto-including file contents like ChatGPT was rejected because:
- Wastes tokens on files user may not ask about
- Large files quickly fill context window (200K tokens)
- Files API has 24h TTL - content may expire
- Current approach gives model control over when to read files
