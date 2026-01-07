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
| [phase-1.4-multimodal-tools.md](phase-1.4-multimodal-tools.md) | Multimodal support (images, voice, files) and tools framework (code execution, image generation) | **planned** |

### Phase 2: Features Expansion

| File | Description | Status |
|------|-------------|--------|
| [phase-2.1-payment-system.md](phase-2.1-payment-system.md) | Payment system: user balance, Telegram Stars integration, admin tools, cost tracking | **planned** |

### Phase 3: Infrastructure

| File | Description | Status |
|------|-------------|--------|
| infrastructure.md | Docker, cache (Redis), monitoring (Grafana, Loki), database admin (CloudBeaver) | **planned** |

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
- Comprehensive test coverage (201 tests)

### Phase 1.3: Claude Integration (Core) ✅
- Claude Sonnet 4.5 (claude-sonnet-4-5-20250929)
- Real-time streaming (no buffering)
- Token-based context management (200K window)
- Thread-based conversation history
- Cost tracking (input/output tokens)
- Comprehensive error handling
- Regression tests (4 tests)

### Phase 1.4: Multimodal + Tools 📋
- Vision (image analysis with Claude)
- Voice messages (transcription + processing)
- File handling (PDF, code, data files)
- Tools framework (code execution, image generation)
- Prompt caching optimization
- Extended thinking for complex tasks

### Phase 2.1: Payment System 📋
- User balance in USD
- Pre-request cost validation
- Telegram Stars integration (deposits, refunds)
- Admin commands (balance management)
- Cost reporting and analytics
- Transaction audit trail

### Phase 3: Infrastructure 📋
- Redis caching
- Grafana + Prometheus monitoring
- Loki log aggregation
- CloudBeaver database UI
- Performance optimizations

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
