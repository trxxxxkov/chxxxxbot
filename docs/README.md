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
[discussing / agreed / implemented / outdated]

## Content
...
```

### Keeping Documentation Current

**Rule:** Any code change affecting architecture must update the corresponding document in the same commit.

---

## Documentation Map

| File | Description | Status |
|------|-------------|--------|
| [bot-structure.md](bot-structure.md) | Bot file structure, module purposes | agreed |
| telegram-api.md | Handlers, middlewares, keyboards, Telegram features | planned |
| llm-providers.md | Provider interface, Claude implementation | planned |
| database.md | Models, repositories, migrations | planned |
| infrastructure.md | Docker, Grafana, Loki, monitoring | planned |

---

## Quick Start for LLM-agents

1. **Understand structure** → read `bot-structure.md`
2. **Find needed module** → check map above or `CLAUDE.md`
3. **Modify code** → update corresponding document
4. **Add new component** → create document using template above
