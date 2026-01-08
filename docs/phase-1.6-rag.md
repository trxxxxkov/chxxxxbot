# Phase 1.6: RAG (Retrieval-Augmented Generation)

**Status:** 📋 Planned

**Purpose:** Add vector search capability for user's uploaded files, enabling intelligent search across documents, PDFs, and images.

---

## Overview

Phase 1.6 focuses on building RAG infrastructure for searching through user-uploaded files using vector embeddings and semantic search.

**Key Components:**
- Vector database (Qdrant)
- Embeddings service
- File indexing pipeline
- `search_user_files` tool

**Prerequisites:**
- Phase 1.5 completed (Files API, multimodal support, tools architecture)
- `user_files` table exists with file metadata

---

## Architecture

```
User uploads file → Telegram → Bot → Files API (storage)
                                  ↓
                            Extract text/content
                                  ↓
                         Generate embeddings
                                  ↓
                            Qdrant (vector DB)

User asks question → Claude decides to use search_user_files
                              ↓
                    Bot queries Qdrant (vector search)
                              ↓
                   Returns top-K relevant files as search_result blocks
                              ↓
                    Claude analyzes results + answers with citations
```

---

## Components

### 1. Qdrant Container

**Why Qdrant:**
- Open-source
- Docker-ready
- Fast (Rust implementation)
- Simple REST API
- Supports filtering (by user_id, thread_id, file_type)

**Docker setup:**
```yaml
# compose.yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    ports:
      - "6333:6333"  # REST API
      - "6334:6334"  # gRPC API
    volumes:
      - ./qdrant_storage:/qdrant/storage
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334
    restart: unless-stopped
```

**Collection structure:**
```python
# Collection: user_files_vectors
{
  "vectors": {
    "size": 1536,  # OpenAI embeddings dimension
    "distance": "Cosine"
  },
  "payload_schema": {
    "user_id": "integer",
    "thread_id": "integer",
    "file_id": "integer",  # FK to user_files table
    "claude_file_id": "string",
    "filename": "string",
    "file_type": "string",  # 'pdf', 'image', 'document'
    "chunk_index": "integer",  # For multi-chunk files
    "chunk_text": "text",  # Actual text content
    "uploaded_at": "datetime"
  }
}
```

---

### 2. Embeddings Service

**Option A: OpenAI Embeddings API** (Recommended)
```python
import openai

def generate_embedding(text: str) -> list[float]:
    response = openai.embeddings.create(
        model="text-embedding-3-small",  # 1536 dimensions, $0.02/1M tokens
        input=text
    )
    return response.data[0].embedding
```
- **Pros:** High quality, simple API, reliable
- **Cons:** External dependency, costs per token
- **Cost:** ~$0.02 per 1M tokens (~750K words)

**Option B: sentence-transformers (Local)**
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

def generate_embedding(text: str) -> list[float]:
    return model.encode(text).tolist()
```
- **Pros:** Free, no external API, privacy
- **Cons:** Requires GPU for speed, lower quality than OpenAI
- **Dimension:** 384 (smaller than OpenAI)

**Decision:** Start with OpenAI (simple), add local option later.

---

### 3. File Indexing Pipeline

**Flow:**
```python
# bot/core/indexing.py

async def index_file(file_id: int):
    """Index a file after upload to Files API"""

    # 1. Get file from DB
    file = await get_file_by_id(file_id)

    # 2. Extract text content
    text_chunks = await extract_text(file)

    # 3. Generate embeddings
    embeddings = [generate_embedding(chunk) for chunk in text_chunks]

    # 4. Store in Qdrant
    await qdrant_client.upsert(
        collection_name="user_files_vectors",
        points=[
            {
                "id": f"{file_id}_{i}",
                "vector": embedding,
                "payload": {
                    "user_id": file.user_id,
                    "thread_id": file.thread_id,
                    "file_id": file_id,
                    "claude_file_id": file.claude_file_id,
                    "filename": file.filename,
                    "file_type": file.file_type,
                    "chunk_index": i,
                    "chunk_text": text_chunks[i],
                    "uploaded_at": file.uploaded_at
                }
            }
            for i, embedding in enumerate(embeddings)
        ]
    )
```

**Text Extraction by file type:**

**PDFs:**
```python
from pypdf import PdfReader

def extract_text_from_pdf(file_path: str) -> list[str]:
    reader = PdfReader(file_path)
    chunks = []
    for page in reader.pages:
        text = page.extract_text()
        # Split into chunks (~1000 tokens each)
        chunks.extend(split_into_chunks(text, max_tokens=1000))
    return chunks
```

**Images (OCR):**
```python
# Use Claude vision API directly - no OCR needed
# Just store image metadata in Qdrant for search
def extract_text_from_image(file_path: str) -> list[str]:
    # Metadata only (filename, upload time)
    # Actual analysis via analyze_image tool when found
    return [f"Image: {filename}"]
```

**Text files:**
```python
def extract_text_from_text_file(file_path: str) -> list[str]:
    with open(file_path, 'r') as f:
        text = f.read()
    return split_into_chunks(text, max_tokens=1000)
```

**Chunking strategy:**
```python
def split_into_chunks(text: str, max_tokens: int = 1000) -> list[str]:
    """Split text into overlapping chunks"""
    # Use tiktoken for accurate token counting
    # Overlap: 100 tokens between chunks
    # Strategy: Split by paragraphs, then by sentences if needed
    pass
```

---

### 4. search_user_files Tool

**Tool definition:**
```python
{
    "name": "search_user_files",
    "description": """Search through user's uploaded files and documents using semantic search.
    Use this when the user asks about their files, documents, or previously uploaded content.
    Returns relevant excerpts with source information.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query (semantic search, not keyword)"
            },
            "thread_id": {
                "type": "integer",
                "description": "Optional: limit search to specific thread/conversation"
            },
            "file_types": {
                "type": "array",
                "items": {"type": "string", "enum": ["pdf", "image", "document"]},
                "description": "Optional: filter by file types"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default: 5)",
                "default": 5
            }
        },
        "required": ["query"]
    }
}
```

**Implementation:**
```python
# bot/core/tools/search_user_files.py

from anthropic.types import SearchResultBlockParam, TextBlockParam

async def search_user_files(
    query: str,
    user_id: int,
    thread_id: int | None = None,
    file_types: list[str] | None = None,
    top_k: int = 5
) -> list[SearchResultBlockParam]:
    """Execute vector search and return search_result blocks"""

    # 1. Generate query embedding
    query_embedding = generate_embedding(query)

    # 2. Build Qdrant filter
    must_conditions = [{"key": "user_id", "match": {"value": user_id}}]
    if thread_id:
        must_conditions.append({"key": "thread_id", "match": {"value": thread_id}})
    if file_types:
        must_conditions.append({"key": "file_type", "match": {"any": file_types}})

    # 3. Search in Qdrant
    search_results = await qdrant_client.search(
        collection_name="user_files_vectors",
        query_vector=query_embedding,
        query_filter={
            "must": must_conditions
        },
        limit=top_k,
        score_threshold=0.7  # Minimum similarity score
    )

    # 4. Convert to search_result blocks
    result_blocks = []
    for hit in search_results:
        payload = hit.payload
        result_blocks.append(
            SearchResultBlockParam(
                type="search_result",
                source=f"file://{payload['claude_file_id']}",  # Internal file reference
                title=f"{payload['filename']} (page {payload['chunk_index'] + 1})",
                content=[
                    TextBlockParam(
                        type="text",
                        text=payload['chunk_text']
                    )
                ],
                citations={"enabled": True}
            )
        )

    return result_blocks
```

**Tool result format:**
```python
# When Claude calls search_user_files
tool_result = ToolResultBlockParam(
    type="tool_result",
    tool_use_id=tool_use_id,
    content=search_user_files(query="quantum computing", user_id=123)
)

# Returns:
[
    {
        "type": "search_result",
        "source": "file://file_abc123",
        "title": "research_paper.pdf (page 3)",
        "content": [{"type": "text", "text": "Quantum computing enables..."}],
        "citations": {"enabled": true}
    },
    {
        "type": "search_result",
        "source": "file://file_xyz789",
        "title": "notes.txt (page 1)",
        "content": [{"type": "text", "text": "Key findings from quantum research..."}],
        "citations": {"enabled": true}
    }
]
```

---

## Database Changes

### user_files Table Updates

Add vector tracking fields:
```python
# Migration: add vector tracking to user_files
class UserFile(Base):
    # ... existing fields ...

    # New fields for Phase 1.6
    indexed_at: datetime | None  # When indexed to Qdrant
    vector_ids: list[str]  # List of Qdrant point IDs for this file
    chunk_count: int  # Number of chunks/vectors
    indexing_status: str  # 'pending', 'indexed', 'failed'
    indexing_error: str | None  # Error message if failed
```

---

## Configuration

**bot/config.py additions:**
```python
# Qdrant settings
QDRANT_HOST = get_env("QDRANT_HOST", "qdrant")
QDRANT_PORT = get_env("QDRANT_PORT", 6333)
QDRANT_COLLECTION_NAME = "user_files_vectors"

# Embeddings settings
EMBEDDINGS_PROVIDER = get_env("EMBEDDINGS_PROVIDER", "openai")  # 'openai' or 'local'
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

# Indexing settings
CHUNK_SIZE_TOKENS = 1000
CHUNK_OVERLAP_TOKENS = 100
SIMILARITY_THRESHOLD = 0.7  # Minimum score for search results
DEFAULT_TOP_K = 5
MAX_TOP_K = 20
```

---

## Workflow

### File Upload Flow

```
1. User uploads file to Telegram
2. Bot handler (F.photo | F.document)
3. Download from Telegram
4. Upload to Files API → get claude_file_id
5. Save to user_files table (indexing_status='pending')
6. Background task: index_file(file_id)
   - Extract text
   - Generate embeddings
   - Upload to Qdrant
   - Update user_files (indexing_status='indexed', indexed_at=now())
7. File ready for search
```

### Search Flow

```
1. User: "What did I write about quantum computing?"
2. Claude analyzes query
3. Claude calls search_user_files(query="quantum computing")
4. Bot executes:
   - Generate query embedding
   - Search Qdrant (vector similarity)
   - Return top-K results as search_result blocks
5. Claude receives results with citations
6. Claude formulates answer (doesn't show citations to user)
```

---

## Implementation Tasks

### Infrastructure Setup
- [ ] Add Qdrant container to compose.yaml
- [ ] Create Qdrant collection with schema
- [ ] Set up embeddings service (OpenAI API)
- [ ] Add configuration to bot/config.py

### Database
- [ ] Migration: add vector tracking fields to user_files
- [ ] Create indexing status tracking

### Indexing Pipeline
- [ ] Implement text extraction (PDF, images, text files)
- [ ] Implement chunking strategy
- [ ] Implement embeddings generation
- [ ] Implement Qdrant upload
- [ ] Background task for async indexing
- [ ] Re-indexing mechanism (when file updated)

### Search Tool
- [ ] Implement search_user_files tool
- [ ] Add to tools registry
- [ ] Query embedding generation
- [ ] Qdrant search with filters
- [ ] Convert results to search_result blocks

### Integration
- [ ] Update file upload handler (trigger indexing)
- [ ] Update Claude handler (add search_user_files tool)
- [ ] Error handling for indexing failures
- [ ] Logging for search queries

### Testing
- [ ] Unit tests: text extraction
- [ ] Unit tests: chunking
- [ ] Unit tests: embeddings generation
- [ ] Integration tests: Qdrant operations
- [ ] End-to-end tests: upload → index → search

### Monitoring
- [ ] Indexing queue size
- [ ] Indexing failures
- [ ] Search query latency
- [ ] Qdrant storage size

---

## Cost Estimation

**OpenAI Embeddings:**
- $0.02 per 1M tokens
- Average file: ~5K tokens → $0.0001 per file
- 1000 files indexed: ~$0.10

**Qdrant:**
- Open-source, self-hosted (free)
- Storage: minimal (vectors + metadata)

**Total monthly cost (1000 active users, 10 files each):**
- Embeddings: ~$1-2
- Storage: negligible

**Very affordable!**

---

## Performance Considerations

**Indexing:**
- Async background task (don't block user)
- Batch processing for multiple files
- Rate limiting for embeddings API

**Search:**
- Fast (<100ms typical for Qdrant)
- Cache frequent queries (optional)
- Limit top_k to prevent context overflow

**Storage:**
- Qdrant can handle millions of vectors
- Monitor disk space (vectors + file storage)
- Cleanup expired files (align with FILES_API_TTL_HOURS)

---

## Related Documents

- **Phase 1.4:** Advanced API Features documentation (includes Search Results overview)
- **Phase 1.5:** Multimodal + Tools (Files API, tool architecture)
- **Search Results:** https://platform.claude.com/docs/en/build-with-claude/search-results

---

## Future Enhancements (Phase 2+)

- **Hybrid search:** Combine vector search with keyword search
- **Multi-language support:** Multilingual embeddings
- **Image search:** Visual similarity search (CLIP embeddings)
- **Knowledge graphs:** Entity extraction and relationship mapping
- **Conversation memory:** Index entire conversation history for context
- **Semantic caching:** Cache similar queries to reduce embeddings API calls
