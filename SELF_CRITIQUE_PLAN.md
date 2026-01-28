# Self-Critique Tool: Detailed Architecture Plan

## Overview

`self_critique` - полноценный **субагент-верификатор** с доступом к tools.
**Всегда использует Claude Opus 4.5** для максимального качества проверки.

**Стоимость:**
- Требует баланс >= $0.50 для запуска
- Стоимость **динамическая** - пользователь платит реальные затраты субагента
- Все расходы (токены Opus + tools) списываются с баланса и учитываются в Grafana

---

## Key Implementation Principles (from Anthropic docs)

### Tool Loop Pattern (официальный)
```
1. User message → Claude
2. Claude responds with tool_use blocks (stop_reason: "tool_use")
3. Execute tools, return tool_result in user message
4. Claude continues (may call more tools or finish with stop_reason: "end_turn")
5. Repeat until done
```

### Parallel Tool Calls
- Все tool_use блоки в **одном** assistant message
- Все tool_result блоки в **одном** user message
- Используем asyncio.gather() для параллельного выполнения

### Extended Thinking для субагента
- Включаем `thinking` для глубокого анализа
- `budget_tokens` 10000-16000 для сложной верификации
- Interleaved thinking позволяет думать между tool calls

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Main Claude Session                             │
│  (User's model: Sonnet/Opus/Haiku)                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  User request → Claude generates response → [Trigger condition?]        │
│                                                                          │
│  Triggers:                                                               │
│  1. User dissatisfaction ("переделай", "не то", "wrong")                │
│  2. User requests verification ("проверь", "убедись", "тщательно")      │
│  3. Complex task / long reasoning (Claude's own judgment)               │
│                                                                          │
│                              ↓                                           │
│                    ┌─────────────────┐                                  │
│                    │  self_critique  │                                  │
│                    │      tool       │                                  │
│                    └────────┬────────┘                                  │
│                             │                                            │
└─────────────────────────────┼────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     Self-Critique Subagent                               │
│  (Same model as user, separate context, CRITICAL system prompt)         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Input:                                                                  │
│  - content: text/code/reasoning to verify                               │
│  - file_ids: files to analyze                                           │
│  - user_request: original request for alignment check                   │
│  - verification_hints: suggested approaches                             │
│                                                                          │
│  Available Tools (parallel execution supported):                        │
│  ├── execute_python  - Run code, write tests, debug, visualize         │
│  ├── preview_file    - Examine any file type                           │
│  ├── analyze_image   - Vision analysis of images                        │
│  ├── analyze_pdf     - PDF content analysis                            │
│  └── render_latex    - Visualize formulas for verification             │
│                                                                          │
│  Workflow:                                                               │
│  1. Understand user's original request                                  │
│  2. Examine provided content/files (use tools in parallel)             │
│  3. Write verification code / tests if applicable                      │
│  4. Visualize data if it helps spot anomalies                          │
│  5. Compare output vs. user request                                     │
│  6. Return structured verdict                                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                        Structured Output                                 │
├─────────────────────────────────────────────────────────────────────────┤
│  {                                                                       │
│    "verdict": "PASS" | "FAIL" | "NEEDS_IMPROVEMENT",                    │
│    "alignment_score": 0-100,                                            │
│    "issues": [                                                          │
│      {                                                                   │
│        "severity": "critical" | "major" | "minor",                      │
│        "category": "logic" | "accuracy" | "completeness" | ...,         │
│        "description": "...",                                            │
│        "location": "line 42" | "file.png" | "paragraph 3"              │
│      }                                                                   │
│    ],                                                                    │
│    "verification_methods": ["code_execution", "visualization", ...],    │
│    "recommendations": ["Fix X by doing Y", ...],                        │
│    "confidence": 0-100                                                  │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Tool Definition

```python
SELF_CRITIQUE_TOOL = {
    "name": "self_critique",
    "description": """Critical self-verification subagent. Launches independent
verification session using the SAME model as user but with ADVERSARIAL mindset.

The subagent has access to tools for thorough verification:
- execute_python: Run tests, debug code, visualize data
- preview_file: Examine any file type
- analyze_image/analyze_pdf: Vision-based analysis

COST: This is a paid tool. Requires user balance >= $0.50.
Typical cost: $0.01-0.10 depending on verification complexity.

USE THIS TOOL IN THESE CASES:

1. AFTER USER DISSATISFACTION
   Triggers: "переделай", "не то", "неправильно", "redo", "wrong", "try again"
   Workflow: Generate new version → self_critique → if FAIL: iterate → deliver when PASS

2. WHEN USER REQUESTS VERIFICATION
   Triggers: "проверь", "убедись", "тщательно", "точно", "verify", "make sure", "double-check"
   Workflow: Complete task → self_critique → fix if needed → deliver

3. DURING COMPLEX TASKS (your judgment)
   When: Long reasoning chains, 50+ lines of code, uncertain correctness
   Workflow: Generate → self_critique → iterate if needed → deliver

The subagent is ADVERSARIAL - it actively searches for flaws, not validation.
A "PASS" means it genuinely tried hard to find issues but couldn't.""",

    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Text, code, or reasoning to verify. Include the full response you're about to send."
            },
            "file_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File IDs to verify (exec_xxx from execute_python, file_xxx from Files API, or telegram file_id). The subagent will analyze these files."
            },
            "user_request": {
                "type": "string",
                "description": "The ORIGINAL user request. Critical for checking alignment - does the response actually answer what was asked?"
            },
            "verification_hints": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "run_tests",           # Write and run tests for code
                        "check_edge_cases",    # Test boundary conditions
                        "visualize_data",      # Create visualizations to spot anomalies
                        "verify_calculations", # Re-compute mathematical results
                        "check_logic_chain",   # Trace reasoning step by step
                        "compare_with_spec",   # Check against specifications
                        "debug_execution",     # Step through code execution
                        "validate_output_format" # Check output matches expected format
                    ]
                },
                "description": "Suggested verification approaches. The subagent will use its judgment but these provide hints."
            },
            "focus_areas": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "accuracy",        # Are facts/calculations correct?
                        "completeness",    # Does it fully answer the request?
                        "logic",           # Is reasoning sound?
                        "user_intent",     # Does it match what user actually wanted?
                        "code_correctness",# Does code work correctly?
                        "formatting",      # Is output properly formatted?
                        "edge_cases"       # Are boundary conditions handled?
                    ]
                },
                "description": "Areas to focus critical analysis on"
            }
        },
        "required": ["user_request"]
    }
}
```

---

## 3. Critical Reviewer System Prompt

Following Claude 4 best practices:
- XML tags for structure
- Context/motivation for instructions
- Explicit behavior guidance
- Parallel tool calling optimization

```python
CRITICAL_REVIEWER_SYSTEM_PROMPT = """<identity>
You are a CRITICAL REVIEWER conducting adversarial verification of another
Claude's output. Your role is to find FLAWS, ERRORS, and GAPS - not to
validate or praise. You operate in a separate context with fresh perspective.
</identity>

<adversarial_mindset>
ASSUME the content you're reviewing MAY BE WRONG. This is crucial because:
- The original Claude may have made reasoning errors
- Code may have bugs that weren't caught
- The response may not actually answer what the user asked
- There may be edge cases or assumptions that were missed

Your job is to DISPROVE correctness, not confirm it.
A "PASS" verdict should only be given when you genuinely couldn't find
significant issues despite actively trying to find them.

DO NOT:
- Praise the work ("great job", "well done")
- Give benefit of the doubt
- Assume things work without verification
- Skip checking because something "looks correct"

DO:
- Actively search for errors
- Test edge cases
- Verify claims through execution
- Question every assumption
- Compare output against user's actual request
</adversarial_mindset>

<verification_tools>
You have access to powerful verification tools. USE THEM ACTIVELY.
Don't just read and assess - VERIFY through execution and testing.

Available tools:
- execute_python: Run code to test claims, reproduce results, check edge cases,
  write unit tests, debug step-by-step, create visualizations
- preview_file: Examine any file - images, PDFs, CSV, text, code
- analyze_image: Deep vision analysis of images
- analyze_pdf: Analyze PDF content and structure
- render_latex: Visualize mathematical formulas

PARALLEL EXECUTION: When multiple verifications are independent, run them
in parallel. For example:
- Checking code AND visualizing output → parallel
- Running tests for multiple functions → parallel
- Analyzing multiple files → parallel
</verification_tools>

<verification_workflow>
Follow this systematic approach:

1. UNDERSTAND THE REQUEST
   - Read the original user request carefully
   - What EXACTLY did they ask for?
   - What would a correct response look like?

2. EXAMINE THE CONTENT
   - Read the provided content/code/reasoning
   - Note any immediate concerns or red flags
   - Identify claims that need verification

3. ACTIVE VERIFICATION (use tools!)
   For CODE:
   - Write and run tests, especially edge cases
   - Step through logic manually
   - Check for off-by-one errors, null handling, type issues
   - Verify output format matches expectations

   For DATA/CALCULATIONS:
   - Re-compute key calculations
   - Create visualizations to spot anomalies
   - Check for statistical errors

   For REASONING:
   - Trace each logical step
   - Look for hidden assumptions
   - Check if conclusions follow from premises

   For FILES:
   - Use preview_file/analyze_image/analyze_pdf
   - Verify content matches what was requested
   - Check formatting, completeness

4. ALIGNMENT CHECK
   - Does the output ACTUALLY answer the user's request?
   - Not "sort of" or "mostly" - EXACTLY?
   - Are there missing parts the user asked for?

5. COMPILE FINDINGS
   - List all issues found with severity
   - Provide specific locations (line numbers, paragraphs)
   - Give actionable recommendations
</verification_workflow>

<output_format>
After verification, respond with a JSON object:

{
  "verdict": "PASS" | "FAIL" | "NEEDS_IMPROVEMENT",
  "alignment_score": <0-100, how well does output match user's request>,
  "confidence": <0-100, how confident are you in this assessment>,
  "issues": [
    {
      "severity": "critical" | "major" | "minor",
      "category": "accuracy" | "completeness" | "logic" | "user_intent" |
                  "code_correctness" | "formatting" | "edge_cases",
      "description": "<specific description of the issue>",
      "location": "<where in the content: line number, paragraph, file name>",
      "evidence": "<what you found that proves this is an issue>"
    }
  ],
  "verification_methods_used": [
    "<list what you actually did: ran_tests, visualized_data, etc.>"
  ],
  "recommendations": [
    "<specific actionable fix for each issue>"
  ],
  "summary": "<2-3 sentence summary of your findings>"
}

IMPORTANT: Your entire response must be valid JSON. No text before or after.
</output_format>

<rating_guidelines>
Be HARSH but FAIR. Users need honest feedback.

FAIL (alignment < 50):
- Critical errors that make the output wrong or unusable
- Fundamentally misunderstands user's request
- Code that doesn't work or produces wrong results
- Major logical flaws in reasoning

NEEDS_IMPROVEMENT (alignment 50-80):
- Partially correct but has notable gaps
- Minor bugs or edge case failures
- Missing some requested features
- Reasoning is sound but incomplete

PASS (alignment > 80):
- You actively tried to find issues but couldn't find significant ones
- Output genuinely answers the user's request
- Code works correctly including edge cases
- Reasoning is sound and complete

Remember: A false "PASS" wastes user's time and money.
A harsh but accurate "FAIL" helps them get better results.
</rating_guidelines>

<context_awareness>
You have a limited context window for this verification task.
Focus on the most important verifications first.
If you run out of context, provide your best assessment based on what you verified.
</context_awareness>"""
```

---

## 3.5 Cost Tracking & Metrics

### CostTracker class

```python
# bot/core/tools/self_critique.py

from core.pricing import calculate_token_cost
from prometheus_client import Counter, Histogram

# Prometheus metrics for Grafana
SELF_CRITIQUE_REQUESTS = Counter(
    'self_critique_requests_total',
    'Total self_critique invocations',
    ['user_id', 'verdict']
)
SELF_CRITIQUE_COST = Histogram(
    'self_critique_cost_usd',
    'Cost of self_critique calls in USD',
    ['user_id'],
    buckets=[0.01, 0.02, 0.05, 0.10, 0.20, 0.50]
)
SELF_CRITIQUE_TOKENS = Counter(
    'self_critique_tokens_total',
    'Tokens used by self_critique',
    ['user_id', 'token_type']  # input, output
)
SELF_CRITIQUE_TOOLS = Counter(
    'self_critique_tools_total',
    'Tool calls made by self_critique subagent',
    ['tool_name']
)


class CostTracker:
    """Track costs for self_critique subagent.

    Accumulates:
    - Opus API token costs (input + output)
    - Tool execution costs (E2B, Vision API for files)

    On finalize: charges user and records metrics.
    """

    def __init__(self, model_config: ModelConfig, user_id: int, tool_name: str):
        self.model_config = model_config
        self.user_id = user_id
        self.tool_name = tool_name

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.tool_costs: list[tuple[str, float]] = []  # (tool_name, cost)

    def add_api_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Track API token usage."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

        # Record metrics
        SELF_CRITIQUE_TOKENS.labels(
            user_id=str(self.user_id),
            token_type='input'
        ).inc(input_tokens)
        SELF_CRITIQUE_TOKENS.labels(
            user_id=str(self.user_id),
            token_type='output'
        ).inc(output_tokens)

    def add_tool_cost(self, tool_name: str, cost: float) -> None:
        """Track tool execution cost."""
        self.tool_costs.append((tool_name, cost))
        SELF_CRITIQUE_TOOLS.labels(tool_name=tool_name).inc()

    def calculate_total_cost(self) -> float:
        """Calculate total cost in USD."""
        # Token costs (Opus pricing)
        token_cost = calculate_token_cost(
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
            model_config=self.model_config
        )

        # Tool costs
        tool_cost = sum(cost for _, cost in self.tool_costs)

        return token_cost + tool_cost

    async def finalize_and_charge(
        self,
        session: 'AsyncSession',
        balance_service: BalanceService,
        verdict: str = "UNKNOWN"
    ) -> float:
        """Finalize tracking, charge user, record metrics.

        Returns:
            Total cost charged in USD.
        """
        total_cost = self.calculate_total_cost()

        # Charge user
        await balance_service.deduct_balance(
            user_id=self.user_id,
            amount=total_cost,
            description=f"self_critique verification (Opus)"
        )

        # Record Prometheus metrics
        SELF_CRITIQUE_REQUESTS.labels(
            user_id=str(self.user_id),
            verdict=verdict
        ).inc()
        SELF_CRITIQUE_COST.labels(
            user_id=str(self.user_id)
        ).observe(total_cost)

        logger.info("self_critique.cost_charged",
                    user_id=self.user_id,
                    total_cost=total_cost,
                    input_tokens=self.total_input_tokens,
                    output_tokens=self.total_output_tokens,
                    tool_costs=self.tool_costs)

        return total_cost
```

### Tool cost tracking

When subagent calls tools, track their costs:

```python
async def _execute_subagent_tool(..., cost_tracker: CostTracker) -> Dict[str, Any]:
    # ... execute tool ...

    # Track tool-specific costs
    if tool_name == "execute_python":
        # E2B cost: $0.00005 per second
        execution_time = result.get("execution_time", 0)
        e2b_cost = execution_time * E2B_COST_PER_SECOND
        cost_tracker.add_tool_cost("execute_python", e2b_cost)

    elif tool_name in ("analyze_image", "analyze_pdf", "preview_file"):
        # Vision API cost - tracked by the tool itself
        if "cost" in result:
            cost_tracker.add_tool_cost(tool_name, result["cost"])
```

### Grafana Dashboard Queries

```promql
# Total self_critique cost per user (24h)
sum by (user_id) (
  increase(self_critique_cost_usd_sum[24h])
)

# Average cost per verification
self_critique_cost_usd_sum / self_critique_cost_usd_count

# Verdict distribution
sum by (verdict) (increase(self_critique_requests_total[24h]))

# Most used tools by subagent
topk(5, sum by (tool_name) (increase(self_critique_tools_total[24h])))
```

---

## 4. Executor Implementation (Full Code)

```python
# bot/core/tools/self_critique.py

"""Self-critique subagent tool for critical verification.

This tool launches an independent verification session using the same model
as the user but with an adversarial system prompt focused on finding flaws.

The subagent has access to tools:
- execute_python: Run tests, debug, visualize
- preview_file: Examine any file type
- analyze_image: Vision analysis
- analyze_pdf: PDF analysis
- render_latex: Formula visualization

Cost: Paid tool, requires balance >= $0.50
"""

import json
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

from config import get_model
from core.tools.base import ToolConfig
from core.tools.execute_python import execute_python
from core.tools.preview_file import preview_file
from core.tools.analyze_image import analyze_image
from core.tools.analyze_pdf import analyze_pdf
from core.tools.render_latex import render_latex
from services.balance_service import BalanceService
from utils.structured_logging import get_logger

logger = get_logger(__name__)

# Minimum balance required to use self_critique
MIN_BALANCE_FOR_CRITIQUE = 0.50

# Maximum iterations for subagent tool loop
MAX_SUBAGENT_ITERATIONS = 20

# Tools available to the subagent
SUBAGENT_TOOLS = [
    # execute_python - for running tests, debugging, visualization
    {
        "name": "execute_python",
        "description": "Execute Python code for testing, debugging, or visualization. "
                       "Use this to: write and run tests, step through code, create plots, "
                       "verify calculations, check edge cases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "pip packages to install"
                }
            },
            "required": ["code"]
        }
    },
    # preview_file - for examining any file
    {
        "name": "preview_file",
        "description": "Preview any file content. Works with exec_xxx (sandbox files), "
                       "file_xxx (Files API), or telegram file_id. "
                       "Use for: checking generated files, examining data, reviewing code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "File ID to preview"},
                "question": {"type": "string", "description": "For images/PDFs: what to analyze"},
                "max_rows": {"type": "integer", "description": "For CSV: max rows to show"},
                "max_chars": {"type": "integer", "description": "For text: max characters"}
            },
            "required": ["file_id"]
        }
    },
    # analyze_image - for deep image analysis
    {
        "name": "analyze_image",
        "description": "Deep vision analysis of images. Use when you need detailed "
                       "examination of image content, not just a quick preview.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claude_file_id": {"type": "string", "description": "File ID of image"},
                "question": {"type": "string", "description": "What to analyze"}
            },
            "required": ["claude_file_id", "question"]
        }
    },
    # analyze_pdf - for PDF analysis
    {
        "name": "analyze_pdf",
        "description": "Analyze PDF document content and structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "claude_file_id": {"type": "string", "description": "File ID of PDF"},
                "question": {"type": "string", "description": "What to analyze"}
            },
            "required": ["claude_file_id", "question"]
        }
    }
]


async def execute_self_critique(
    user_request: str,
    content: Optional[str] = None,
    file_ids: Optional[List[str]] = None,
    verification_hints: Optional[List[str]] = None,
    focus_areas: Optional[List[str]] = None,
    *,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    user_id: int,
) -> Dict[str, Any]:
    """Execute critical self-verification subagent.

    ALWAYS uses Claude Opus 4.5 for maximum verification quality.
    Cost is dynamic - user pays actual Opus token costs + tool costs.

    Args:
        user_request: Original user request for alignment check.
        content: Text/code/reasoning to verify.
        file_ids: List of file IDs to analyze.
        verification_hints: Suggested verification approaches.
        focus_areas: Areas to focus critique on.
        bot: Telegram bot instance.
        session: Database session.
        thread_id: Current thread ID.
        user_id: User ID for balance check and cost tracking.

    Returns:
        Structured verification result with verdict, issues, recommendations.
    """
    # ALWAYS use Opus for verification - best model for finding errors
    VERIFICATION_MODEL = "claude:opus"
    model_config = get_model(VERIFICATION_MODEL)

    logger.info("self_critique.started",
                user_id=user_id,
                model=VERIFICATION_MODEL,
                has_content=bool(content),
                file_count=len(file_ids) if file_ids else 0)

    # 1. Check balance (minimum $0.50 to start)
    balance_service = BalanceService(session)
    balance = await balance_service.get_balance(user_id)

    if balance < MIN_BALANCE_FOR_CRITIQUE:
        logger.info("self_critique.insufficient_balance",
                    user_id=user_id,
                    balance=balance,
                    required=MIN_BALANCE_FOR_CRITIQUE)
        return {
            "error": "insufficient_balance",
            "verdict": "SKIPPED",
            "message": f"self_critique requires balance >= ${MIN_BALANCE_FOR_CRITIQUE:.2f}. "
                       f"Current balance: ${balance:.2f}",
            "required_balance": MIN_BALANCE_FOR_CRITIQUE,
            "current_balance": balance
        }

    # 2. Initialize cost tracking
    cost_tracker = CostTracker(
        model_config=model_config,
        user_id=user_id,
        tool_name="self_critique"
    )

    # 3. Build verification context
    verification_context = _build_verification_context(
        user_request=user_request,
        content=content,
        file_ids=file_ids,
        verification_hints=verification_hints,
        focus_areas=focus_areas
    )

    # 4. Create Anthropic client
    client = AsyncAnthropic()

    # 5. Run subagent tool loop (official Anthropic pattern)
    # Pattern: user → claude → tool_use → tool_result → claude → ... → end_turn
    messages = [{"role": "user", "content": verification_context}]
    total_input_tokens = 0
    total_output_tokens = 0

    for iteration in range(MAX_SUBAGENT_ITERATIONS):
        logger.debug("self_critique.iteration",
                     iteration=iteration,
                     message_count=len(messages))

        # Call Claude API with extended thinking for deep analysis
        response = await client.messages.create(
            model=model_config.model_id,
            max_tokens=16000,  # Enough for thinking + tools + response
            thinking={
                "type": "enabled",
                "budget_tokens": 10000  # Deep reasoning for verification
            },
            system=CRITICAL_REVIEWER_SYSTEM_PROMPT,
            tools=SUBAGENT_TOOLS,
            messages=messages
        )

        # Track token costs
        cost_tracker.add_api_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens
        )
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Check stop reason (official API pattern)
        if response.stop_reason == "end_turn":
            # Done - extract JSON result from text blocks
            result_text = ""
            for block in response.content:
                if block.type == "text":
                    result_text += block.text

            try:
                result = json.loads(result_text)
                # Finalize cost and charge user
                total_cost = await cost_tracker.finalize_and_charge(
                    session=session,
                    balance_service=balance_service
                )

                result["tokens_used"] = {
                    "input": total_input_tokens,
                    "output": total_output_tokens
                }
                result["cost_usd"] = total_cost
                result["iterations"] = iteration + 1

                logger.info("self_critique.completed",
                            verdict=result.get("verdict"),
                            alignment_score=result.get("alignment_score"),
                            issues_count=len(result.get("issues", [])),
                            iterations=iteration + 1,
                            total_cost_usd=total_cost)
                return result
            except json.JSONDecodeError:
                logger.warning("self_critique.invalid_json", response=result_text[:500])
                return {
                    "verdict": "ERROR",
                    "error": "invalid_response_format",
                    "raw_response": result_text[:1000]
                }

        # Handle tool use (stop_reason == "tool_use")
        elif response.stop_reason == "tool_use":
            # Step 1: Add assistant message with ALL content (thinking + tool_use)
            # Must preserve thinking blocks for interleaved thinking!
            messages.append({
                "role": "assistant",
                "content": [block.model_dump() for block in response.content]
            })

            # Step 2: Execute ALL tools in parallel (official pattern)
            tool_use_blocks = [
                block for block in response.content
                if block.type == "tool_use"
            ]

            # Parallel execution using asyncio.gather
            tool_tasks = [
                _execute_subagent_tool(
                    tool_name=block.name,
                    tool_input=block.input,
                    tool_use_id=block.id,
                    bot=bot,
                    session=session,
                    thread_id=thread_id
                )
                for block in tool_use_blocks
            ]
            tool_results = await asyncio.gather(*tool_tasks)

            # Step 3: Add ALL tool results in ONE user message (official pattern)
            messages.append({
                "role": "user",
                "content": list(tool_results)
            })

        else:
            # Unexpected stop reason
            logger.warning("self_critique.unexpected_stop",
                          stop_reason=response.stop_reason)
            break

    # Max iterations reached
    logger.warning("self_critique.max_iterations", iterations=MAX_SUBAGENT_ITERATIONS)
    return {
        "verdict": "ERROR",
        "error": "max_iterations_reached",
        "message": f"Verification did not complete within {MAX_SUBAGENT_ITERATIONS} iterations"
    }


def _build_verification_context(
    user_request: str,
    content: Optional[str],
    file_ids: Optional[List[str]],
    verification_hints: Optional[List[str]],
    focus_areas: Optional[List[str]]
) -> str:
    """Build the verification context message for the subagent."""
    parts = []

    parts.append("<verification_task>")
    parts.append("You are reviewing another Claude's response. Find flaws.")
    parts.append("</verification_task>")

    parts.append("\n<original_user_request>")
    parts.append(user_request)
    parts.append("</original_user_request>")

    if content:
        parts.append("\n<content_to_verify>")
        parts.append(content)
        parts.append("</content_to_verify>")

    if file_ids:
        parts.append("\n<files_to_verify>")
        parts.append("Use preview_file or analyze_image/analyze_pdf to examine these:")
        for file_id in file_ids:
            parts.append(f"- {file_id}")
        parts.append("</files_to_verify>")

    if verification_hints:
        parts.append("\n<suggested_verification_approaches>")
        for hint in verification_hints:
            parts.append(f"- {hint}")
        parts.append("</suggested_verification_approaches>")

    if focus_areas:
        parts.append("\n<focus_areas>")
        parts.append("Pay special attention to:")
        for area in focus_areas:
            parts.append(f"- {area}")
        parts.append("</focus_areas>")

    parts.append("\n<instructions>")
    parts.append("1. Understand what the user actually requested")
    parts.append("2. Examine the content/files using available tools")
    parts.append("3. Write tests or verification code if applicable")
    parts.append("4. Actively search for errors, gaps, misalignments")
    parts.append("5. Return your verdict as JSON")
    parts.append("</instructions>")

    return "\n".join(parts)


async def _execute_subagent_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    tool_use_id: str,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int]
) -> Dict[str, Any]:
    """Execute a tool call from the subagent."""
    logger.debug("self_critique.tool_call",
                 tool_name=tool_name,
                 tool_input_keys=list(tool_input.keys()))

    try:
        if tool_name == "execute_python":
            result = await execute_python(
                code=tool_input["code"],
                requirements=tool_input.get("requirements"),
                bot=bot,
                session=session,
                thread_id=thread_id
            )
        elif tool_name == "preview_file":
            result = await preview_file(
                file_id=tool_input["file_id"],
                question=tool_input.get("question"),
                max_rows=tool_input.get("max_rows"),
                max_chars=tool_input.get("max_chars"),
                bot=bot,
                session=session,
                thread_id=thread_id
            )
        elif tool_name == "analyze_image":
            result = await analyze_image(
                claude_file_id=tool_input["claude_file_id"],
                question=tool_input["question"],
                bot=bot,
                session=session
            )
        elif tool_name == "analyze_pdf":
            result = await analyze_pdf(
                claude_file_id=tool_input["claude_file_id"],
                question=tool_input["question"],
                bot=bot,
                session=session
            )
        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps(result) if isinstance(result, dict) else str(result)
        }

    except Exception as e:
        logger.exception("self_critique.tool_error", tool_name=tool_name, error=str(e))
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps({"error": str(e)}),
            "is_error": True
        }


# Tool configuration for registry
TOOL_CONFIG = ToolConfig(
    name="self_critique",
    definition=SELF_CRITIQUE_TOOL,
    executor=execute_self_critique,
    emoji="🔍",
    needs_bot_session=True,  # Needs bot, session for tool execution
)
```

---

## 5. Changes to Existing Files

### 5.1 registry.py

```python
# Add import
from core.tools.self_critique import TOOL_CONFIG as SELF_CRITIQUE_CONFIG

# Add to TOOLS dict
TOOLS: Dict[str, ToolConfig] = {
    # ... existing tools ...
    "self_critique": SELF_CRITIQUE_CONFIG,
}
```

### 5.2 execute_tool() signature change

Need to pass `user_id` and `model_id` to self_critique:

```python
async def execute_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    user_id: Optional[int] = None,      # NEW
    model_id: Optional[str] = None,     # NEW
) -> Dict[str, str]:
    # ... existing code ...

    # For self_critique, pass additional params
    if tool_name == "self_critique":
        if user_id is None or model_id is None:
            raise ValueError("self_critique requires user_id and model_id")
        result = await executor(
            bot=bot,
            session=session,
            thread_id=thread_id,
            user_id=user_id,
            model_id=model_id,
            **tool_input,
        )
    # ... rest of existing code ...
```

### 5.3 claude.py handler

Pass user_id and model_id when calling execute_tool:

```python
# In _execute_tool_with_timeout or wherever execute_tool is called
result = await execute_tool(
    tool_name=tool_name,
    tool_input=tool_input,
    bot=self.bot,
    session=session,
    thread_id=thread_id,
    user_id=user_id,        # Add this
    model_id=user_model_id, # Add this
)
```

### 5.4 system_prompt.py

Replace `<self_correction>` with `<self_critique_usage>`:

```python
# Remove old <self_correction> section

# Add new section:
<self_critique_usage>
You have access to `self_critique` - a powerful verification subagent that critically
analyzes your work using the same model but with an adversarial mindset.

The subagent can:
- Run Python code to test your solutions
- Visualize data to spot anomalies
- Examine files you generated
- Write unit tests for your code
- Trace reasoning step by step

COST: Requires user balance >= $0.50 (typical cost: $0.01-0.10)

USE self_critique IN THESE CASES:

1. AFTER USER DISSATISFACTION
   Triggers: "переделай", "не то", "неправильно", "redo", "wrong", "try again"

   Workflow:
   - Generate improved version
   - Call self_critique with content + user_request
   - If verdict is FAIL or NEEDS_IMPROVEMENT:
     - Read the issues and recommendations
     - Fix the problems
     - Call self_critique again
   - Iterate until PASS or max 3 attempts
   - Deliver best version with explanation of any remaining issues

2. WHEN USER REQUESTS VERIFICATION
   Triggers: "проверь", "убедись", "тщательно", "точно", "verify", "make sure",
             "double-check", "carefully"

   Workflow:
   - Complete the task
   - Call self_critique before delivering
   - Fix issues if verdict != PASS
   - Deliver only after PASS or after explaining remaining issues

3. DURING COMPLEX TASKS (your judgment)
   When to use:
   - Long reasoning chains that could have errors
   - 50+ lines of code
   - Multi-step calculations
   - When you're uncertain about correctness

   Workflow:
   - Generate your response
   - Call self_critique if you have doubts
   - Iterate if needed
   - Deliver with confidence

The subagent is ADVERSARIAL - it actively searches for flaws, not validation.
Trust its verdict: a "PASS" means it genuinely couldn't find significant issues.
If it reports issues, fix them before delivering.

IMPORTANT: self_critique creates files in sandbox (tests, visualizations).
These are for verification only - don't deliver them to user unless relevant.
</self_critique_usage>
```

---

## 6. Cost Analysis

### Per verification call:
- Input tokens: ~2000-5000 (context + tool results)
- Output tokens: ~500-2000 (reasoning + JSON result)
- Tool iterations: 1-5 typically

### With Sonnet ($3/$15 per 1M):
- Simple verification: ~$0.01-0.02
- Complex with code execution: ~$0.03-0.05
- Thorough with visualization: ~$0.05-0.10

### With Opus ($5/$25 per 1M):
- Simple: ~$0.02-0.03
- Complex: ~$0.05-0.08
- Thorough: ~$0.08-0.15

### Balance threshold rationale:
$0.50 minimum ensures user can afford ~5-10 verification calls,
enough for iterative improvement cycle.

---

## 7. Testing Plan

### Unit tests:
- `test_self_critique_balance_check` - verify balance >= $0.50 required
- `test_self_critique_builds_context` - verify context building
- `test_self_critique_tool_execution` - verify tool routing
- `test_self_critique_json_parsing` - verify result parsing

### Integration tests:
- `test_self_critique_finds_code_bugs` - give buggy code, expect FAIL
- `test_self_critique_passes_correct_code` - give working code, expect PASS
- `test_self_critique_checks_alignment` - mismatched response, expect low alignment
- `test_self_critique_uses_visualization` - data task, expect visualization tool use

### E2E tests:
- Full flow: user dissatisfaction → self_critique → iteration → success

---

## 8. File Structure

```
bot/core/tools/
├── self_critique.py           # NEW: Main implementation
│   ├── SELF_CRITIQUE_TOOL     # Tool definition
│   ├── CRITICAL_REVIEWER_SYSTEM_PROMPT
│   ├── SUBAGENT_TOOLS         # Tools available to subagent
│   ├── execute_self_critique()
│   ├── _build_verification_context()
│   └── _execute_subagent_tool()
├── registry.py                # Modified: add self_critique
├── base.py                    # No changes
└── ... other tools ...

bot/prompts/
└── system_prompt.py           # Modified: replace <self_correction>

bot/telegram/handlers/
└── claude.py                  # Modified: pass user_id, model_id to execute_tool
```

---

## 9. Trigger Detection

Add helper function to detect when self_critique should be suggested:

```python
# bot/core/tools/self_critique.py

DISSATISFACTION_TRIGGERS = {
    # Russian
    "переделай", "перепиши", "не то", "неправильно", "плохо",
    "не так", "ошибка", "исправь", "заново",
    # English
    "redo", "wrong", "incorrect", "fix", "try again", "not right",
    "doesn't work", "broken", "failed", "bad"
}

VERIFICATION_TRIGGERS = {
    # Russian
    "проверь", "убедись", "тщательно", "внимательно", "точно",
    "аккуратно", "критически", "перепроверь",
    # English
    "verify", "check", "make sure", "double-check", "carefully",
    "thoroughly", "accurately", "critically"
}

def should_use_self_critique(user_message: str, is_retry: bool = False) -> tuple[bool, str]:
    """Check if self_critique should be used.

    Returns:
        (should_use, reason) tuple
    """
    message_lower = user_message.lower()

    # Check dissatisfaction triggers
    if is_retry:
        for trigger in DISSATISFACTION_TRIGGERS:
            if trigger in message_lower:
                return True, "user_dissatisfaction"

    # Check verification request triggers
    for trigger in VERIFICATION_TRIGGERS:
        if trigger in message_lower:
            return True, "user_requested_verification"

    return False, ""
```

---

## 10. Step-by-Step Implementation Plan

### Phase 1: Create self_critique tool module

**File:** `bot/core/tools/self_critique.py`

```
1. Create CRITICAL_REVIEWER_SYSTEM_PROMPT constant
2. Create SUBAGENT_TOOLS list (definitions for execute_python, preview_file, etc.)
3. Create SELF_CRITIQUE_TOOL definition
4. Implement execute_self_critique() with:
   - Balance check (>= $0.50)
   - Context building
   - Tool loop with parallel execution
   - Extended thinking enabled
5. Implement _build_verification_context()
6. Implement _execute_subagent_tool() for routing
7. Create TOOL_CONFIG for registry
```

### Phase 2: Update registry

**File:** `bot/core/tools/registry.py`

```python
# Add import
from core.tools.self_critique import TOOL_CONFIG as SELF_CRITIQUE_CONFIG

# Add to TOOLS dict
TOOLS["self_critique"] = SELF_CRITIQUE_CONFIG
```

### Phase 3: Update execute_tool signature

**File:** `bot/core/tools/registry.py`

```python
async def execute_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    user_id: Optional[int] = None,      # NEW - for balance check & cost tracking
) -> Dict[str, str]:
    # Note: model_id NOT needed - self_critique always uses Opus
```

### Phase 4: Update handler to pass user context

**File:** `bot/telegram/handlers/claude.py`

Find where `execute_tool` is called and add:
```python
result = await execute_tool(
    tool_name=tool_name,
    tool_input=tool_input,
    bot=self.bot,
    session=session,
    thread_id=thread_id,
    user_id=user.telegram_id,    # Add
    model_id=user.model_id,       # Add
)
```

### Phase 5: Update system prompt

**File:** `bot/prompts/system_prompt.py`

1. Remove old `<self_correction>` section
2. Add new `<self_critique_usage>` section with:
   - Three trigger cases
   - Iterative workflow
   - Balance requirement note

### Phase 6: Write tests

**File:** `bot/tests/core/tools/test_self_critique.py`

```
1. test_balance_check_insufficient
2. test_balance_check_sufficient
3. test_context_building
4. test_tool_loop_single_iteration
5. test_tool_loop_with_tools
6. test_parallel_tool_execution
7. test_verdict_pass
8. test_verdict_fail
9. test_max_iterations
```

### Phase 7: Integration testing

```bash
# Manual E2E test scenarios:
1. Simple verification (no tools needed)
2. Verification with code execution
3. Verification with visualization
4. Iterative fix loop (FAIL → fix → PASS)
```

---

## 11. Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `bot/core/tools/self_critique.py` | CREATE | Main tool implementation |
| `bot/core/tools/registry.py` | MODIFY | Add to TOOLS, update execute_tool signature |
| `bot/telegram/handlers/claude.py` | MODIFY | Pass user_id, model_id to execute_tool |
| `bot/prompts/system_prompt.py` | MODIFY | Replace self_correction with self_critique_usage |
| `bot/tests/core/tools/test_self_critique.py` | CREATE | Unit tests |

---

## 12. Summary

### What we're building:
- **Full-featured verification subagent** with tool access
- **ALWAYS uses Claude Opus 4.5** for maximum verification quality
- **Adversarial system prompt** for honest critique (not validation)
- **Extended thinking** enabled for deep analysis
- **Parallel tool execution** for efficiency
- **Dynamic pricing** — user pays actual costs
- **Full Grafana integration** — all costs tracked as user expenses

### Key features:
| Feature | Description |
|---------|-------------|
| **Always Opus** | Best model for finding errors, regardless of user's model |
| **Tool access** | execute_python, preview_file, analyze_image, analyze_pdf |
| **Parallel execution** | asyncio.gather() for multiple tools |
| **Extended thinking** | 10K budget tokens for deep reasoning |
| **Balance check** | Requires >= $0.50 to START |
| **Dynamic cost** | User pays actual Opus tokens + tool costs |
| **Grafana metrics** | Requests, costs, tokens, tools all tracked |
| **Three triggers** | Dissatisfaction, verification request, complexity |
| **Iterative workflow** | FAIL → fix → self_critique → repeat until PASS |

### Critical design decisions:
1. **Always Opus** — best model for verification, not user's model
2. **Dynamic pricing** — user pays real costs, no fixed fee
3. **Adversarial prompt** — actively searches for flaws, not validates
4. **Tool loop pattern** — follows official Anthropic API pattern
5. **Thinking blocks preserved** — for interleaved thinking
6. **Full cost tracking** — every token and tool call billed to user

### Implementation order:
```
Phase 1: Create self_critique.py (tool + executor + CostTracker)
Phase 2: Update registry.py (add tool)
Phase 3: Update execute_tool signature (user_id only, no model_id)
Phase 4: Update claude.py handler (pass user context)
Phase 5: Update system_prompt.py (new section)
Phase 6: Add Prometheus metrics
Phase 7: Write unit tests
Phase 8: E2E integration testing
```

### Estimated cost per verification (Opus only):
| Complexity | Input tokens | Output tokens | Tool cost | Total |
|------------|--------------|---------------|-----------|-------|
| Simple | ~2K | ~1K | $0 | ~$0.03 |
| With code | ~3K | ~2K | ~$0.01 | ~$0.07 |
| Thorough | ~5K | ~3K | ~$0.03 | ~$0.12 |

**Opus pricing:** $5/M input, $25/M output

### Risk mitigation:
- **Balance check >= $0.50** prevents starting without funds
- **Dynamic billing** — user sees real costs, no surprises
- **Max iterations** (20) prevents infinite loops
- **Timeout** on tool execution prevents hangs
- **Grafana dashboards** — monitor costs in real-time

### Prometheus metrics:
```
self_critique_requests_total{user_id, verdict}
self_critique_cost_usd{user_id}
self_critique_tokens_total{user_id, token_type}
self_critique_tools_total{tool_name}
```
