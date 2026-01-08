# Claude Integration: Phase 1.4 (Advanced API Features)

Review Claude API documentation, extract best practices and advanced features, implement improvements to Phase 1.3.

**Status:** 📋 **IN PROGRESS** (Documentation review)

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

**Key insights:**
- Claude 4.5 family has 3 models: Sonnet, Haiku, Opus
- Each model has different characteristics:
  - **Sonnet 4.5** (`claude-sonnet-4-5-20250929`): Balance of intelligence/speed/cost, best for coding and agents
    - Context: 200K tokens, Max output: 64K tokens
    - Pricing: $3/MTok input, $15/MTok output
    - Latency: Fast
  - **Haiku 4.5** (`claude-haiku-4-5-20251001`): Fastest, cheapest (3x cheaper than Sonnet)
    - Context: 200K tokens, Max output: 64K tokens
    - Pricing: $1/MTok input, $5/MTok output
    - Latency: Fastest
  - **Opus 4.5** (`claude-opus-4-5-20251101`): Premium intelligence, highest quality
    - Context: 200K tokens, Max output: 64K tokens
    - Pricing: $5/MTok input, $25/MTok output
    - Latency: Moderate
- Documentation recommends using explicit model IDs (with snapshot dates) instead of aliases in production
- All 4.5 models support Extended Thinking (separate feature to review later)
- 1M token context window available via beta header (not needed for our use case)

**What we'll implement:**
- **Multi-model support with `/model` command**
  - Implementation: New `/model` handler in `bot/telegram/handlers/`
  - User can select between Sonnet 4.5, Haiku 4.5, Opus 4.5
  - Selection stored per-user (User model or Thread model)
  - Architecture must support adding models from other providers later (OpenAI, Google)
  - Why: Cost optimization (Haiku for simple tasks) + quality scaling (Opus for complex tasks)

- **Model characteristics storage and application**
  - Implementation: Model registry/config in `bot/core/models.py` or separate file
  - Store for each model:
    - `model_id` (e.g., "claude-sonnet-4-5-20250929")
    - `display_name` (e.g., "Claude Sonnet 4.5")
    - `provider` (e.g., "claude", later "openai", "google")
    - `context_window` (200K for all Claude 4.5)
    - `max_output` (64K for Sonnet/Haiku/Opus 4.5)
    - `pricing_input` (per MTok)
    - `pricing_output` (per MTok)
    - `latency_tier` ("fast", "fastest", "moderate")
  - When user selects model via `/model`, apply these characteristics automatically
  - Why: Different models have different limits and costs - must respect them

- **Use explicit model IDs (not aliases)**
  - Implementation: Already done in Phase 1.3 ✅
  - We use `claude-sonnet-4-5-20250929`, not `claude-sonnet-4-5`
  - Why: Production stability, predictable behavior

**What we'll skip:**
- **1M token context window (beta)**: Not needed, 200K is sufficient
- **Extended Thinking**: Will review separately (likely has dedicated documentation page)
- **AWS Bedrock / GCP Vertex AI**: Only using Anthropic API directly
- **Legacy models** (Claude 3.x, Claude 4.0/4.1): Starting with latest 4.5 family only

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

*This section will be updated as we review more pages.*

### From Models Overview page:
- [ ] Create model registry with characteristics (model_id, display_name, provider, context_window, max_output, pricing_input, pricing_output, latency_tier)
- [ ] Add model selection field to User or Thread model in database
- [ ] Implement `/model` command handler with inline keyboard for model selection
- [ ] Update ClaudeClient to use selected model characteristics (max_tokens, max_output)
- [ ] Update cost tracking to use model-specific pricing
- [ ] Ensure architecture supports adding non-Claude providers later

---

## Related Documents

- **[phase-1.3-claude-core.md](phase-1.3-claude-core.md)** - Current implementation
- **[phase-1.5-multimodal-tools.md](phase-1.5-multimodal-tools.md)** - Next phase
- **[CLAUDE.md](../CLAUDE.md)** - Project overview

---

## Summary

Phase 1.4 is documentation-driven optimization. We read official docs, discuss each page, and document decisions. Implementation happens after review is complete.

**Current status:** Reviewing documentation (1 page completed).

**Next step:** Continue reviewing documentation pages.
