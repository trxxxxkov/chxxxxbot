# Project Documentation

This folder contains architectural documentation optimized for LLM-agents.

---

## Documentation Guidelines

### Purpose

Documentation in `docs/` is designed to **improve LLM-agent efficiency** when working with code. It should give agents quick understanding of:
- What is located where
- What each component relates to
- What decisions were made and why
- What dependencies exist between modules

### What Documents Should Contain

**Required:**
- Specific file and folder paths
- Relationships between components (what depends on what)
- Architectural decisions with justification
- Interfaces for interaction between modules

**Recommended:**
- Code examples for typical operations
- Common mistakes and how to avoid them
- Links to related documents

**Avoid:**
- Generic phrases without specifics
- Duplicating information from code (which can be easily read)
- Outdated information

### Document Format

Each document should start with a brief description (1-2 sentences) so agents can quickly determine if they need this file.

```markdown
# Component Name

Brief description: what it is and why it's needed.

## Status
[implemented / planned / outdated]

## Content
...
```

### Keeping Documentation Current

**Rule:** Any code change affecting architecture must update the corresponding document in the same commit.

---

## Documentation Map

Documents are organized by development phase for easy navigation.

### Phase 1: Working Prototype

| File | Description | Status |
|------|-------------|--------|
| [phase-1.1-bot-structure.md](phase-1.1-bot-structure.md) | Bot file structure, module purposes, dependency rules | **implemented** |
| [phase-1.2-database.md](phase-1.2-database.md) | PostgreSQL architecture: models, repositories, migrations, patterns | **implemented** |
| [phase-1.2-telegram-api-mapping.md](phase-1.2-telegram-api-mapping.md) | Field-by-field mapping between Telegram Bot API 9.3 and database | **implemented** |
| [phase-1.3-claude-core.md](phase-1.3-claude-core.md) | Claude integration (core): streaming, context management, error handling | **implemented** |
| [phase-1.4-claude-advanced-api.md](phase-1.4-claude-advanced-api.md) | Advanced API features: documentation review, best practices, optimizations | **implemented** |
| [phase-1.5-agent-tools.md](phase-1.5-agent-tools.md) | Tools framework: analyze_image, analyze_pdf, execute_python, web_search, web_fetch | **implemented** |
| [phase-1.6-multimodal-support.md](phase-1.6-multimodal-support.md) | Universal media architecture: voice, audio, video handlers, Whisper transcription | **implemented** |
| [phase-1.7-image-generation.md](phase-1.7-image-generation.md) | Image generation: Google Nano Banana Pro, generate_image tool | **implemented** |

### Phase 2: Features Expansion

| File | Description | Status |
|------|-------------|--------|
| [phase-2.1-payment-system.md](phase-2.1-payment-system.md) | Payment system: user balance, Telegram Stars integration, admin tools, cost tracking | **implemented** |
| [phase-2.2-devops-agent.md](phase-2.2-devops-agent.md) | DevOps Agent: self-healing bot with Agent SDK, auto-fix errors, feature development via Telegram, GitHub PRs | **planned** |

### Phase 3: Infrastructure

| File | Description | Status |
|------|-------------|--------|
| [phase-3-infrastructure.md](phase-3-infrastructure.md) | Monitoring (Grafana, Loki, Prometheus), database admin (CloudBeaver) | **implemented** |

---

## Quick Start for LLM-agents

1. **Understand overall structure** → read `phase-1.1-bot-structure.md`
2. **Find specific implementation** → check phase documents for completed features
3. **Plan new feature** → read corresponding planned phase document
4. **Modify code** → update corresponding document in same commit
5. **Add new component** → create or update relevant phase document

---

## Phase Overview

### Phase 1.1: Minimal Bot ✅
- Aiogram 3.24 framework
- Telegram polling
- Basic handlers (start, echo)
- Structured logging
- Docker containerization

### Phase 1.2: PostgreSQL ✅
- SQLAlchemy 2.0 async ORM
- 4 models: User, Chat, Thread, Message
- Repository pattern with base class
- Alembic migrations
- DatabaseMiddleware for session management

### Phase 1.3: Claude Integration (Core) ✅
- Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)
- Real-time streaming (no buffering)
- Token-based context management (200K window)
- Thread-based conversation history
- Cost tracking (input/output tokens)

### Phase 1.4: Advanced API Features ✅
- Model registry (Haiku, Sonnet, Opus)
- Prompt caching (5-minute ephemeral cache)
- Extended thinking (budget_tokens: 10000)
- Effort parameter for Opus
- Token Counting API

### Phase 1.5: Tools Framework ✅
- analyze_image (Claude Vision + Files API)
- analyze_pdf (Claude PDF API)
- execute_python (E2B Code Interpreter)
- web_search, web_fetch (server-side tools)
- user_files table for file tracking

### Phase 1.6: Multimodal Support ✅
- Universal media architecture (MediaProcessor)
- Voice messages with Whisper transcription
- Audio/video file handling
- transcribe_audio tool

### Phase 1.7: Image Generation ✅
- Google Nano Banana Pro integration
- generate_image tool
- Flexible parameters (aspect ratio, resolution)
- Automatic file delivery

### Phase 2.1: Payment System ✅
- User balance in USD ($0.10 starter)
- Telegram Stars integration
- Admin commands (/topup, /set_margin)
- Cost tracking for all APIs
- Refund support (30-day window)

### Phase 2.2: DevOps Agent 📋
- Agent SDK integration (autonomous code editing)
- Self-healing (auto-fix errors from logs)
- Feature development via Telegram (/agent add feature)
- GitHub integration (create PRs, merge, deploy)

### Phase 3.1: Monitoring ✅
- Grafana + Prometheus metrics
- Loki log aggregation
- CloudBeaver database UI
- Pre-configured dashboards

### Phase 3.2: Cache 📋
- Redis caching (planned)

---

## Related Files

- **[../CLAUDE.md](../CLAUDE.md)** - Main project overview, current status, all phases
- **[../README.md](../README.md)** - Quick start, maintenance commands

---

## Documentation Principles

### For LLM Agents

1. **Start with phase number** - Easy sorting and finding
2. **Specific paths** - Always include full file paths
3. **Implementation examples** - Show real code snippets
4. **Link related docs** - Help agents navigate between topics
5. **Status tags** - Clear indication of what's implemented vs planned

### For Humans

1. **Phase-based organization** - Understand development timeline
2. **Concise summaries** - Quick overview before diving deep
3. **Visual structure** - Tables, lists, code blocks for readability
4. **Search-friendly** - Descriptive headings and filenames

---

## Contributing to Documentation

When adding or updating documentation:

1. **Choose correct phase** - Place in appropriate phase file
2. **Update status** - Mark as implemented/planned/outdated
3. **Add to this README** - Update documentation map table
4. **Link related docs** - Add cross-references where relevant
5. **Follow format** - Use standard sections (Status, Overview, Components, etc.)
6. **Commit together** - Documentation changes go in same commit as code

---

## Notes

- **NO `__init__.py` files** - Python 3.12+ namespace packages used throughout
- **Direct imports** - Always import from full paths (e.g., `from db.models.user import User`)
- **Google Python Style** - All code follows Google Python Style Guide
- **Structured logging** - All operations logged with `structlog` in JSON format
- **Test-first** - Every bug fix must include regression test
