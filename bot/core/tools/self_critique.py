"""Self-critique subagent tool for critical verification.

This tool launches an independent verification session using Claude Opus 4.5
with an adversarial system prompt focused on finding flaws.

The subagent has access to tools:
- execute_python: Run tests, debug, visualize
- preview_file: Examine any file type
- analyze_image: Vision analysis
- analyze_pdf: PDF analysis
- web_search: Search the web to verify facts (server-side, $0.01/search)
- web_fetch: Read full content of web pages (documentation, articles)

Cost:
- Requires balance >= $0.50 to start
- Dynamic pricing: user pays actual Opus token costs + tool costs
- All costs tracked in Grafana/Prometheus

NO __init__.py - use direct import:
    from core.tools.self_critique import TOOL_CONFIG, execute_self_critique
"""

import asyncio
from decimal import Decimal
import json
from typing import Any, Optional, TYPE_CHECKING

from anthropic import AsyncAnthropic
from config import get_model
from core.pricing import calculate_claude_cost
from core.pricing import calculate_e2b_cost
from core.tools.base import ToolConfig
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Always use Opus for verification - best model for finding errors
VERIFICATION_MODEL_ID = "claude:opus"

# Minimum balance required to start self_critique
MIN_BALANCE_FOR_CRITIQUE = Decimal("0.50")

# Maximum iterations for subagent tool loop
# High limit to allow extensive web searching for fact verification
MAX_SUBAGENT_ITERATIONS = 40

# Extended thinking budget for deep analysis (doubled for thorough verification)
THINKING_BUDGET_TOKENS = 16000

# =============================================================================
# Prometheus Metrics
# =============================================================================

try:
    from prometheus_client import Counter
    from prometheus_client import Histogram

    SELF_CRITIQUE_REQUESTS = Counter('self_critique_requests_total',
                                     'Total self_critique invocations',
                                     ['verdict'])
    SELF_CRITIQUE_COST = Histogram(
        'self_critique_cost_usd',
        'Cost of self_critique calls in USD',
        buckets=[0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.0])
    SELF_CRITIQUE_TOKENS = Counter(
        'self_critique_tokens_total',
        'Tokens used by self_critique',
        ['token_type']  # input, output, thinking
    )
    SELF_CRITIQUE_TOOLS = Counter('self_critique_tools_total',
                                  'Tool calls made by self_critique subagent',
                                  ['tool_name'])
    SELF_CRITIQUE_ITERATIONS = Histogram(
        'self_critique_iterations',
        'Number of iterations per self_critique call',
        buckets=[1, 2, 3, 5, 10, 20])
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    logger.warning("self_critique.prometheus_unavailable",
                   msg="prometheus_client not available, metrics disabled")

# =============================================================================
# Critical Reviewer System Prompt
# =============================================================================

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
- web_search: Search the internet to verify facts, check claims, find
  authoritative sources. USE EXTENSIVELY for fact-checking!
- web_fetch: Fetch and read full content of web pages (documentation, articles).
  Use after web_search to read complete documentation pages.
</verification_tools>

<parallel_tool_execution>
If you intend to call multiple tools and there are no dependencies between the
tool calls, make ALL independent tool calls in parallel. Maximize use of parallel
tool calls to increase speed and efficiency.

Examples of parallel execution:
- Checking code AND visualizing output → parallel
- Running tests for multiple functions → parallel
- Analyzing multiple files → parallel
- Searching for multiple facts simultaneously → parallel (HIGHLY RECOMMENDED)
- Verifying library docs AND running tests → parallel

However, if some tool calls depend on previous calls to inform parameters, call
those tools sequentially. Never use placeholders or guess missing parameters.
</parallel_tool_execution>

<thinking_guidance>
After receiving tool results, carefully reflect on their quality and determine
optimal next steps before proceeding. Use your thinking to:
- Plan which verifications to run next based on findings
- Iterate based on new information
- Track confidence levels in your assessments
- Self-critique your own verification approach

For complex verification tasks, develop competing hypotheses about potential
issues and systematically test each one. Update your confidence as you gather
evidence.
</thinking_guidance>

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

   For FACTS/CLAIMS:
   - USE WEB_SEARCH EXTENSIVELY to verify factual claims
   - Search for authoritative sources (official docs, Wikipedia, etc.)
   - Cross-reference multiple sources
   - Check dates, numbers, names, technical specifications
   - Don't trust the original response's facts without verification

   For CODE WITH EXTERNAL LIBRARIES/APIs:
   - ALWAYS search for the OFFICIAL documentation of libraries used
   - Verify API methods, parameters, and return types are CURRENT
   - Check if the library version implied is up-to-date
   - Search for "[library] changelog" or "[library] migration guide"
   - Look for deprecation warnings or breaking changes
   - Verify correct import paths and package names
   - Check if there are newer, better alternatives
   - Example searches: "pandas read_csv parameters 2024", "requests library
     timeout parameter", "numpy array creation best practices"

   CRITICAL: Libraries evolve! Code that worked 6 months ago may be:
   - Using deprecated functions
   - Missing new required parameters
   - Using old import paths
   - Incompatible with current versions

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
After verification, respond with a JSON object ONLY:

{
  "verdict": "PASS" | "FAIL" | "NEEDS_IMPROVEMENT",
  "alignment_score": <0-100, how well does output match user's request>,
  "confidence": <0-100, how confident are you in this assessment>,
  "issues": [
    {
      "severity": "critical" | "major" | "minor",
      "category": "accuracy" | "completeness" | "logic" | "user_intent" |
                  "code_correctness" | "formatting" | "edge_cases" |
                  "api_outdated" | "factual_error" | "security",
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

<web_search_strategy>
Use web_search EXTENSIVELY for verification. Search proactively and often.
After finding relevant URLs, use web_fetch to read full documentation pages.

WORKFLOW: web_search → find URLs → web_fetch to read full content

For FACTUAL CLAIMS:
- Search for authoritative sources (Wikipedia, official docs, academic papers)
- Cross-reference at least 2-3 sources for important facts
- Check dates, numbers, names, technical specifications
- Search: "[topic] fact check", "[claim] true or false"
- Use web_fetch to read Wikipedia articles or reference pages in full

For CODE/LIBRARIES:
- ALWAYS search for official documentation of any library mentioned
- Search: "[library] official documentation [year]"
- Search: "[library] changelog", "[library] breaking changes"
- Search: "[function name] deprecated", "[library] migration guide"
- Use web_fetch to read the FULL documentation page, not just snippets!
- Verify import paths, method signatures, parameter names
- Check if there are newer/better alternatives

For APIs:
- Search: "[API name] documentation [year]"
- Search: "[API] rate limits", "[API] authentication"
- Use web_fetch to read the COMPLETE API reference
- Verify endpoint URLs, required headers, response formats
- Check for version changes or deprecations

IMPORTANT: Don't trust your training data for library/API information!
Libraries change frequently. ALWAYS verify against current documentation.
Use web_fetch to read full docs - search snippets are often incomplete!
</web_search_strategy>

<context_awareness>
You have a limited context window for this verification task.
Focus on the most important verifications first.
If you run out of context, provide your best assessment based on what you verified.
</context_awareness>"""

# =============================================================================
# Tools available to the subagent
# =============================================================================

# Server-side tools (Anthropic handles execution)
WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 100,  # Allow extensive searches for thorough fact-checking
}

WEB_FETCH_TOOL = {
    "type": "web_fetch_20250910",
    "name": "web_fetch",
    "max_uses": 50,  # Allow fetching documentation pages
    "citations": {
        "enabled": True
    },
    "max_content_tokens": 50000,  # Reasonable limit for docs
}

SUBAGENT_TOOLS = [{
    "name": "execute_python",
    "description":
        "Execute Python code for testing, debugging, or visualization. "
        "Use this to: write and run tests, step through code, create plots, "
        "verify calculations, check edge cases. "
        "Files are saved to /tmp/ and can be examined with preview_file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Python code to execute"
            },
            "requirements": {
                "type":
                    "array",
                "items": {
                    "type": "string"
                },
                "description":
                    "pip packages to install (e.g., ['numpy', 'pandas'])"
            }
        },
        "required": ["code"]
    }
}, {
    "name": "preview_file",
    "description":
        "Preview any file content. Works with exec_xxx (sandbox files), "
        "file_xxx (Files API), or telegram file_id. "
        "Use for: checking generated files, examining data, reviewing code. "
        "For images/PDFs, provide a question for Vision analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_id": {
                "type":
                    "string",
                "description":
                    "File ID to preview (exec_xxx, file_xxx, or telegram file_id)"
            },
            "question": {
                "type":
                    "string",
                "description":
                    "For images/PDFs: what to analyze (e.g., 'Is this chart correct?')"
            },
            "max_rows": {
                "type": "integer",
                "description": "For CSV/XLSX: max rows to show (default: 20)"
            },
            "max_chars": {
                "type": "integer",
                "description": "For text files: max characters (default: 5000)"
            }
        },
        "required": ["file_id"]
    }
}, {
    "name": "analyze_image",
    "description": "Deep vision analysis of images using Claude Vision. "
                   "Use when you need detailed examination of image content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claude_file_id": {
                "type": "string",
                "description": "File ID of image (file_xxx format)"
            },
            "question": {
                "type":
                    "string",
                "description":
                    "What to analyze (e.g., 'Check if this chart shows correct data')"
            }
        },
        "required": ["claude_file_id", "question"]
    }
}, {
    "name":
        "analyze_pdf",
    "description":
        "Analyze PDF document content and structure using Claude Vision.",
    "input_schema": {
        "type": "object",
        "properties": {
            "claude_file_id": {
                "type": "string",
                "description": "File ID of PDF (file_xxx format)"
            },
            "question": {
                "type":
                    "string",
                "description":
                    "What to analyze (e.g., 'Verify the calculations in this document')"
            }
        },
        "required": ["claude_file_id", "question"]
    }
}]

# =============================================================================
# Tool Definition
# =============================================================================

SELF_CRITIQUE_TOOL = {
    "name":
        "self_critique",
    "description":
        """Critical self-verification subagent using Claude Opus 4.5.

Launches an independent verification session with ADVERSARIAL mindset to find
flaws in your response before sending to user.

The subagent can:
- Run Python code to test your solutions (execute_python)
- Examine files you generated (preview_file)
- Analyze images/PDFs with Vision (analyze_image, analyze_pdf)
- Search the web to verify facts and claims (web_search)
- Fetch and read full documentation pages (web_fetch)

COST: Requires balance >= $0.50. User pays actual Opus token costs + tool costs.
Typical cost: $0.03-0.15 per verification.

WHEN TO USE: You decide. Consider verification when quality matters or you're uncertain.

DYNAMIC WORKFLOW:
1. Generate solution → decide if verification needed → if yes, call self_critique
2. After receiving critique, evaluate the issues:
   - Trivial/clear fixes → fix and deliver (no more critique needed)
   - Non-trivial fixes → fix and call self_critique again
   - PASS → deliver with confidence
3. Decide at each step whether another round is needed (max 5 rounds)
4. If issues remain after 5 rounds → report unresolved problems to user

The subagent can: test code, check visual outputs, search current API docs, find flaws.

Returns structured verdict: PASS, FAIL, or NEEDS_IMPROVEMENT with specific issues.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description":
                    "Text, code, or reasoning to verify. Include the full "
                    "response you're about to send."
            },
            "file_ids": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description":
                    "File IDs to verify (exec_xxx, file_xxx, telegram file_id). "
                    "The subagent will analyze these files."
            },
            "user_request": {
                "type":
                    "string",
                "description":
                    "The ORIGINAL user request. Critical for checking alignment."
            },
            "verification_hints": {
                "type": "array",
                "items": {
                    "type":
                        "string",
                    "enum": [
                        "run_tests", "check_edge_cases", "visualize_data",
                        "verify_calculations", "check_logic_chain",
                        "compare_with_spec", "debug_execution",
                        "validate_output_format"
                    ]
                },
                "description": "Suggested verification approaches."
            },
            "focus_areas": {
                "type": "array",
                "items": {
                    "type":
                        "string",
                    "enum": [
                        "accuracy", "completeness", "logic", "user_intent",
                        "code_correctness", "formatting", "edge_cases"
                    ]
                },
                "description": "Areas to focus critical analysis on."
            }
        },
        "required": ["user_request"]
    }
}

# =============================================================================
# Cost Tracker
# =============================================================================


class CostTracker:
    """Track costs for self_critique subagent.

    Accumulates:
    - Opus API token costs (input + output + thinking)
    - Tool execution costs (E2B sandbox, Vision API for files)

    On finalize: charges user and records Prometheus metrics.
    """

    def __init__(self, model_id: str, user_id: int):
        """Initialize cost tracker.

        Args:
            model_id: Model identifier (e.g., 'claude-opus-4-5-20251101').
            user_id: User ID for logging.
        """
        self.model_id = model_id
        self.user_id = user_id

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_thinking_tokens = 0
        self.tool_costs: list[tuple[str, Decimal]] = []

    def add_api_usage(self,
                      input_tokens: int,
                      output_tokens: int,
                      thinking_tokens: int = 0) -> None:
        """Track API token usage."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_thinking_tokens += thinking_tokens

        # Record Prometheus metrics
        if METRICS_AVAILABLE:
            SELF_CRITIQUE_TOKENS.labels(token_type='input').inc(input_tokens)
            SELF_CRITIQUE_TOKENS.labels(token_type='output').inc(output_tokens)
            if thinking_tokens > 0:
                SELF_CRITIQUE_TOKENS.labels(
                    token_type='thinking').inc(thinking_tokens)

    def add_tool_cost(self, tool_name: str, cost: Decimal) -> None:
        """Track tool execution cost."""
        self.tool_costs.append((tool_name, cost))

        if METRICS_AVAILABLE:
            SELF_CRITIQUE_TOOLS.labels(tool_name=tool_name).inc()

    def calculate_total_cost(self) -> Decimal:
        """Calculate total cost in USD."""
        # Token costs (Opus pricing)
        token_cost = calculate_claude_cost(
            model_id=self.model_id,
            input_tokens=self.total_input_tokens,
            output_tokens=self.total_output_tokens,
            thinking_tokens=self.total_thinking_tokens,
        )

        # Tool costs
        tool_cost = sum(cost for _, cost in self.tool_costs)

        return token_cost + tool_cost

    async def finalize_and_charge(self,
                                  session: 'AsyncSession',
                                  user_id: int,
                                  verdict: str = "UNKNOWN",
                                  iterations: int = 1) -> Decimal:
        """Finalize tracking, charge user, record metrics.

        Args:
            session: Database session.
            user_id: User to charge.
            verdict: Verification verdict for metrics.
            iterations: Number of tool loop iterations.

        Returns:
            Total cost charged in USD.
        """
        # Import here to avoid circular imports
        from db.repositories.balance_operation_repository import \
            BalanceOperationRepository
        from db.repositories.user_repository import UserRepository
        from services.balance_service import BalanceService

        total_cost = self.calculate_total_cost()

        # Charge user
        user_repo = UserRepository(session)
        balance_op_repo = BalanceOperationRepository(session)
        balance_service = BalanceService(session, user_repo, balance_op_repo)

        tool_cost_sum = sum(cost for _, cost in self.tool_costs)
        description = (
            f"self_critique verification (Opus): "
            f"{self.total_input_tokens} in, {self.total_output_tokens} out, "
            f"{self.total_thinking_tokens} thinking, "
            f"tools: ${float(tool_cost_sum):.4f}")

        await balance_service.charge_user(
            user_id=user_id,
            amount=total_cost,
            description=description,
        )

        # Record Prometheus metrics
        if METRICS_AVAILABLE:
            SELF_CRITIQUE_REQUESTS.labels(verdict=verdict).inc()
            SELF_CRITIQUE_COST.observe(float(total_cost))
            SELF_CRITIQUE_ITERATIONS.observe(iterations)

        logger.info("self_critique.cost_charged",
                    user_id=user_id,
                    total_cost=float(total_cost),
                    input_tokens=self.total_input_tokens,
                    output_tokens=self.total_output_tokens,
                    thinking_tokens=self.total_thinking_tokens,
                    tool_costs=[
                        (name, float(cost)) for name, cost in self.tool_costs
                    ],
                    verdict=verdict,
                    iterations=iterations)

        return total_cost


# =============================================================================
# Helper Functions
# =============================================================================


def _build_verification_context(user_request: str, content: Optional[str],
                                file_ids: Optional[list[str]],
                                verification_hints: Optional[list[str]],
                                focus_areas: Optional[list[str]]) -> str:
    """Build the verification context message for the subagent."""
    parts = []

    parts.append("<verification_task>")
    parts.append(
        "You are reviewing another Claude's response. Your job is to find flaws."
    )
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
        parts.append(
            "Use preview_file or analyze_image/analyze_pdf to examine these:")
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
    parts.append("5. Return your verdict as JSON (no other text)")
    parts.append("</instructions>")

    return "\n".join(parts)


async def _execute_subagent_tool(tool_name: str, tool_input: dict[str, Any],
                                 tool_use_id: str, bot: 'Bot',
                                 session: 'AsyncSession',
                                 thread_id: Optional[int],
                                 cost_tracker: CostTracker) -> dict[str, Any]:
    """Execute a tool call from the subagent and track costs."""
    logger.debug("self_critique.tool_call",
                 tool_name=tool_name,
                 tool_input_keys=list(tool_input.keys()))

    try:
        # Import tool executors here to avoid circular imports
        from core.tools.analyze_image import analyze_image
        from core.tools.analyze_pdf import analyze_pdf
        from core.tools.execute_python import execute_python
        from core.tools.preview_file import preview_file

        result: dict[str, Any] = {}

        if tool_name == "execute_python":
            result = await execute_python(
                code=tool_input["code"],
                requirements=tool_input.get("requirements"),
                bot=bot,
                session=session,
                thread_id=thread_id)
            # Track E2B cost
            if "execution_time" in result:
                e2b_cost = calculate_e2b_cost(result["execution_time"])
                cost_tracker.add_tool_cost("execute_python", e2b_cost)

        elif tool_name == "preview_file":
            result = await preview_file(file_id=tool_input["file_id"],
                                        question=tool_input.get("question"),
                                        max_rows=tool_input.get("max_rows"),
                                        max_chars=tool_input.get("max_chars"),
                                        bot=bot,
                                        session=session,
                                        thread_id=thread_id)
            # Vision API cost tracked by preview_file itself
            if "cost" in result:
                cost_tracker.add_tool_cost("preview_file",
                                           Decimal(str(result["cost"])))

        elif tool_name == "analyze_image":
            result = await analyze_image(
                claude_file_id=tool_input["claude_file_id"],
                question=tool_input["question"],
                bot=bot,
                session=session)
            # Vision API cost
            if "cost" in result:
                cost_tracker.add_tool_cost("analyze_image",
                                           Decimal(str(result["cost"])))

        elif tool_name == "analyze_pdf":
            result = await analyze_pdf(
                claude_file_id=tool_input["claude_file_id"],
                question=tool_input["question"],
                bot=bot,
                session=session)
            # Vision API cost
            if "cost" in result:
                cost_tracker.add_tool_cost("analyze_pdf",
                                           Decimal(str(result["cost"])))

        else:
            result = {"error": f"Unknown tool: {tool_name}"}

        return {
            "type":
                "tool_result",
            "tool_use_id":
                tool_use_id,
            "content":
                json.dumps(result, default=str)
                if isinstance(result, dict) else str(result)
        }

    except Exception as e:
        logger.exception("self_critique.tool_error",
                         tool_name=tool_name,
                         error=str(e))
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps({"error": str(e)}),
            "is_error": True
        }


# =============================================================================
# Main Executor
# =============================================================================


async def execute_self_critique(
    user_request: str,
    content: Optional[str] = None,
    file_ids: Optional[list[str]] = None,
    verification_hints: Optional[list[str]] = None,
    focus_areas: Optional[list[str]] = None,
    *,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    user_id: int,
) -> dict[str, Any]:
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
    # Import here to avoid circular imports
    from db.repositories.balance_operation_repository import \
        BalanceOperationRepository
    from db.repositories.user_repository import UserRepository
    from services.balance_service import BalanceService

    # Always use Opus for verification
    model_config = get_model(VERIFICATION_MODEL_ID)

    logger.info("self_critique.started",
                user_id=user_id,
                model=VERIFICATION_MODEL_ID,
                has_content=bool(content),
                file_count=len(file_ids) if file_ids else 0)

    # 1. Check balance (minimum $0.50 to start)
    user_repo = UserRepository(session)
    balance_op_repo = BalanceOperationRepository(session)
    balance_service = BalanceService(session, user_repo, balance_op_repo)
    balance = await balance_service.get_balance(user_id)

    if balance < MIN_BALANCE_FOR_CRITIQUE:
        logger.info("self_critique.insufficient_balance",
                    user_id=user_id,
                    balance=float(balance),
                    required=float(MIN_BALANCE_FOR_CRITIQUE))
        return {
            "error": "insufficient_balance",
            "verdict": "SKIPPED",
            "message":
                f"self_critique requires balance >= ${MIN_BALANCE_FOR_CRITIQUE}. "
                f"Current balance: ${balance:.2f}",
            "required_balance": float(MIN_BALANCE_FOR_CRITIQUE),
            "current_balance": float(balance)
        }

    # 2. Initialize cost tracking
    cost_tracker = CostTracker(model_id=model_config.model_id, user_id=user_id)

    # 3. Build verification context
    verification_context = _build_verification_context(
        user_request=user_request,
        content=content,
        file_ids=file_ids,
        verification_hints=verification_hints,
        focus_areas=focus_areas)

    # 4. Create Anthropic client
    # API key loaded from environment (ANTHROPIC_API_KEY)
    client = AsyncAnthropic()

    # 5. Run subagent tool loop
    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": verification_context
    }]

    for iteration in range(MAX_SUBAGENT_ITERATIONS):
        logger.debug("self_critique.iteration",
                     iteration=iteration,
                     message_count=len(messages))

        # Call Claude API with extended thinking
        response = await client.messages.create(
            model=model_config.model_id,
            max_tokens=16000,
            thinking={
                "type": "enabled",
                "budget_tokens": THINKING_BUDGET_TOKENS
            },
            system=CRITICAL_REVIEWER_SYSTEM_PROMPT,
            tools=SUBAGENT_TOOLS + [WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
            messages=messages)

        # Track token costs
        thinking_tokens = 0
        if hasattr(response.usage, 'thinking_tokens'):
            thinking_tokens = response.usage.thinking_tokens or 0

        cost_tracker.add_api_usage(input_tokens=response.usage.input_tokens,
                                   output_tokens=response.usage.output_tokens,
                                   thinking_tokens=thinking_tokens)

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Done - extract JSON result from text blocks
            result_text = ""
            for block in response.content:
                if block.type == "text":
                    result_text += block.text

            # Try to parse JSON
            try:
                # Find JSON in response (may have markdown code blocks)
                json_text = result_text
                if "```json" in result_text:
                    start = result_text.find("```json") + 7
                    end = result_text.find("```", start)
                    json_text = result_text[start:end].strip()
                elif "```" in result_text:
                    start = result_text.find("```") + 3
                    end = result_text.find("```", start)
                    json_text = result_text[start:end].strip()

                result = json.loads(json_text)

                # Finalize cost and charge user
                verdict = result.get("verdict", "UNKNOWN")
                total_cost = await cost_tracker.finalize_and_charge(
                    session=session,
                    user_id=user_id,
                    verdict=verdict,
                    iterations=iteration + 1)

                result["cost_usd"] = float(total_cost)
                result["iterations"] = iteration + 1
                result["tokens_used"] = {
                    "input": cost_tracker.total_input_tokens,
                    "output": cost_tracker.total_output_tokens,
                    "thinking": cost_tracker.total_thinking_tokens
                }

                logger.info("self_critique.completed",
                            verdict=verdict,
                            alignment_score=result.get("alignment_score"),
                            issues_count=len(result.get("issues", [])),
                            iterations=iteration + 1,
                            total_cost=float(total_cost))

                return result

            except json.JSONDecodeError as e:
                logger.warning("self_critique.invalid_json",
                               error=str(e),
                               response_preview=result_text[:500])

                # Still charge for the attempt
                total_cost = await cost_tracker.finalize_and_charge(
                    session=session,
                    user_id=user_id,
                    verdict="ERROR",
                    iterations=iteration + 1)

                return {
                    "verdict": "ERROR",
                    "error": "invalid_response_format",
                    "raw_response": result_text[:2000],
                    "cost_usd": float(total_cost),
                    "iterations": iteration + 1
                }

        # Handle tool use
        elif response.stop_reason == "tool_use":
            # Add assistant message (preserve thinking blocks for interleaved thinking)
            messages.append({
                "role": "assistant",
                "content": [block.model_dump() for block in response.content]
            })

            # Execute ALL tools in parallel
            tool_use_blocks = [
                block for block in response.content if block.type == "tool_use"
            ]

            tool_tasks = [
                _execute_subagent_tool(tool_name=block.name,
                                       tool_input=block.input,
                                       tool_use_id=block.id,
                                       bot=bot,
                                       session=session,
                                       thread_id=thread_id,
                                       cost_tracker=cost_tracker)
                for block in tool_use_blocks
            ]

            tool_results = await asyncio.gather(*tool_tasks)

            # Add ALL tool results in ONE user message
            messages.append({"role": "user", "content": list(tool_results)})

        else:
            logger.warning("self_critique.unexpected_stop",
                           stop_reason=response.stop_reason)
            break

    # Max iterations reached
    logger.warning("self_critique.max_iterations",
                   iterations=MAX_SUBAGENT_ITERATIONS)

    total_cost = await cost_tracker.finalize_and_charge(
        session=session,
        user_id=user_id,
        verdict="ERROR",
        iterations=MAX_SUBAGENT_ITERATIONS)

    return {
        "verdict":
            "ERROR",
        "error":
            "max_iterations_reached",
        "message":
            f"Verification did not complete within {MAX_SUBAGENT_ITERATIONS} iterations",
        "cost_usd":
            float(total_cost),
        "iterations":
            MAX_SUBAGENT_ITERATIONS
    }


# =============================================================================
# Tool Configuration for Registry
# =============================================================================

TOOL_CONFIG = ToolConfig(
    name="self_critique",
    definition=SELF_CRITIQUE_TOOL,
    executor=execute_self_critique,
    emoji="🔍",
    needs_bot_session=True,
)
