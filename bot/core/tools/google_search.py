"""Google Search + URL Context subagent tool for Gemini models.

Launches a separate Gemini request with Google Search grounding and URL
context enabled. This works around the API limitation that prevents
combining built-in tools (google_search, url_context) with custom
function calling in the same request.

Architecture: similar to self_critique — a subagent with a single request.
The subagent uses a lightweight model (Flash-Lite) with grounding + URL
context to answer search queries or read specific URLs.

Available only for Google provider (Claude has native web_search/web_fetch).

NO __init__.py - use direct import:
    from core.tools.google_search import TOOL_CONFIG, execute_google_search
"""

from decimal import Decimal
from typing import Any, Optional, TYPE_CHECKING

from config import get_model
from core.clients import get_google_client
from core.pricing import GOOGLE_SEARCH_GROUNDING_COST
from core.tools.base import ToolConfig
from utils.structured_logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# Fallback model if user's model is unavailable
FALLBACK_SEARCH_MODEL_ID = "google:flash-lite"

# =============================================================================
# Prometheus Metrics
# =============================================================================

try:
    from prometheus_client import Counter
    from prometheus_client import Histogram

    GOOGLE_SEARCH_REQUESTS = Counter(
        'google_search_tool_requests_total',
        'Total google_search tool invocations',
        ['status'])
    GOOGLE_SEARCH_COST = Histogram(
        'google_search_tool_cost_usd',
        'Cost of google_search tool calls in USD',
        buckets=[0.001, 0.005, 0.01, 0.02, 0.05])
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False

# =============================================================================
# Tool Definition
# =============================================================================

GOOGLE_SEARCH_TOOL = {
    "name":
        "web_search",
    "description":
        """Search the internet or read a specific URL.

Use this tool when you need:
- Current information, facts, news, documentation (web search)
- To read content from a specific URL the user shared (URL fetch)

Supports both search queries and direct URLs (web pages, PDFs, images).

Returns: grounded answer with sources. Cost: ~$0.02 per query.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type":
                    "string",
                "description":
                    "Search query or question to answer using web search. "
                    "Be specific for better results."
            },
        },
        "required": ["query"]
    }
}

# =============================================================================
# Main Executor
# =============================================================================


async def execute_google_search(
    query: str,
    *,
    bot: 'Bot',
    session: 'AsyncSession',
    thread_id: Optional[int] = None,
    user_id: int,
    model_id: Optional[str] = None,
    **kwargs,
) -> dict[str, Any]:
    """Execute web search via Google Search grounding subagent.

    Uses the same Gemini model the user selected for the search request.
    Grounding does the heavy lifting; the model synthesizes results.

    Args:
        query: Search query or question.
        bot: Telegram bot instance.
        session: Database session.
        thread_id: Current thread ID.
        user_id: User ID for cost tracking.
        model_id: User's current model (e.g. "google:pro"). Falls back
            to flash-lite if not provided or not a Google model.

    Returns:
        Dict with search results and cost.
    """
    import asyncio  # pylint: disable=import-outside-toplevel
    from google.genai import types as genai_types  # pylint: disable=import-outside-toplevel

    # Use user's model for search (same model = better context understanding)
    search_model_id = FALLBACK_SEARCH_MODEL_ID
    if model_id:
        try:
            cfg = get_model(model_id)
            if cfg.provider == "google":
                search_model_id = model_id
        except KeyError:
            pass

    logger.info("google_search.started",
                user_id=user_id,
                model=search_model_id,
                query=query[:200])

    try:
        model_config = get_model(search_model_id)
    except KeyError:
        return {
            "error": "search_model_unavailable",
            "message": f"Search model {search_model_id} not configured",
        }

    # Build request with ONLY google_search grounding (no function calling)
    system_prompt = (
        "You are a search assistant. Answer the user's query using the "
        "information from Google Search and URL context. Be factual and "
        "concise. Include relevant details, numbers, and dates. "
        "If the query contains a URL, read and summarize its content. "
        "If the search returns multiple perspectives, present them fairly."
    )

    config = genai_types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=4096,
        temperature=0.2,
        tools=[
            genai_types.Tool(google_search=genai_types.GoogleSearch()),
            genai_types.Tool(url_context=genai_types.UrlContext()),
        ],
    )

    try:
        client = get_google_client()

        def _sync_generate():
            return client.models.generate_content(
                model=model_config.model_id,
                contents=[{"role": "user", "parts": [{"text": query}]}],
                config=config,
            )

        # Retry on transient server errors (503 UNAVAILABLE, 500, 504).
        # Google's search models see bursty demand spikes; a short backoff
        # usually recovers without the user seeing a failure.
        max_retries = 3
        retry_delays = (2, 5, 10)
        response = None
        for attempt in range(max_retries + 1):
            try:
                response = await asyncio.to_thread(_sync_generate)
                break
            except Exception as retry_exc:  # pylint: disable=broad-exception-caught
                err_msg = str(retry_exc)
                is_retriable = (
                    "503" in err_msg
                    or "UNAVAILABLE" in err_msg
                    or "500 INTERNAL" in err_msg
                    or "504" in err_msg
                    or "DEADLINE_EXCEEDED" in err_msg
                )
                if is_retriable and attempt < max_retries:
                    delay = retry_delays[attempt]
                    logger.warning(
                        "google_search.server_error_retry",
                        user_id=user_id,
                        attempt=attempt + 1,
                        max_attempts=max_retries + 1,
                        delay_seconds=delay,
                        error=err_msg[:200],
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        # Extract text from response
        response_text = ""
        if response.candidates:
            candidate = response.candidates[0]
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if part.text:
                        response_text += part.text

        # Extract grounding sources
        sources = []
        if response.candidates:
            candidate = response.candidates[0]
            g_meta = getattr(candidate, 'grounding_metadata', None)
            if g_meta:
                chunks = getattr(g_meta, 'grounding_chunks', None)
                if chunks:
                    for chunk in chunks:
                        web = getattr(chunk, 'web', None)
                        if web:
                            sources.append({
                                "title": getattr(web, 'title', ''),
                                "uri": getattr(web, 'uri', ''),
                            })

            # Extract URL context metadata (fetched URLs)
            url_meta = getattr(candidate, 'url_context_metadata', None)
            if url_meta:
                url_metadata = getattr(url_meta, 'url_metadata', [])
                for um in (url_metadata or []):
                    url = getattr(um, 'retrieved_url', '')
                    status = getattr(um, 'url_retrieval_status', '')
                    if url and 'SUCCESS' in str(status):
                        # Add fetched URL to sources if not already there
                        if not any(s.get('uri') == url for s in sources):
                            sources.append({
                                "title": f"[fetched] {url[:60]}",
                                "uri": url,
                            })

        # Calculate cost (API tokens + grounding)
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            meta = response.usage_metadata
            input_tokens = getattr(meta, 'prompt_token_count', 0) or 0
            output_tokens = getattr(meta, 'candidates_token_count', 0) or 0

        # Token cost for Flash-Lite
        token_cost = (
            Decimal(str(input_tokens)) / Decimal("1000000")
            * Decimal(str(model_config.pricing_input))
            + Decimal(str(output_tokens)) / Decimal("1000000")
            * Decimal(str(model_config.pricing_output))
        )
        total_cost = token_cost + GOOGLE_SEARCH_GROUNDING_COST

        # Charge user
        from services.factory import ServiceFactory  # pylint: disable=import-outside-toplevel
        services = ServiceFactory(session)
        await services.balance.charge_user(
            user_id=user_id,
            amount=total_cost,
            description=f"Google Search: {query[:50]}",
        )

        # Metrics
        if METRICS_AVAILABLE:
            GOOGLE_SEARCH_REQUESTS.labels(status='success').inc()
            GOOGLE_SEARCH_COST.observe(float(total_cost))

        logger.info("google_search.completed",
                     user_id=user_id,
                     response_length=len(response_text),
                     sources_count=len(sources),
                     input_tokens=input_tokens,
                     output_tokens=output_tokens,
                     cost_usd=float(total_cost))

        # Log for Grafana cost tracking
        logger.info("tools.loop.user_charged_for_tool",
                     tool_name="web_search",
                     cost_usd=float(total_cost),
                     source="google_search_subagent")

        result = {
            "answer": response_text,
            "sources": sources[:10],
            "cost_usd": float(total_cost),
            "_already_charged": True,
        }

        # Format as readable string for the model
        if sources:
            source_lines = "\n".join(
                f"- {s['title']}: {s['uri']}" for s in sources[:10]
            )
            result["formatted"] = (
                f"{response_text}\n\nSources:\n{source_lines}"
            )
        else:
            result["formatted"] = response_text

        return result

    except Exception as e:
        logger.error("google_search.error",
                     user_id=user_id,
                     query=query[:200],
                     error=str(e),
                     error_type=type(e).__name__)

        if METRICS_AVAILABLE:
            GOOGLE_SEARCH_REQUESTS.labels(status='error').inc()

        return {
            "error": "search_failed",
            "message": f"Google Search failed: {str(e)[:200]}",
        }


# =============================================================================
# Tool Configuration for Registry
# =============================================================================

TOOL_CONFIG = ToolConfig(
    name="web_search",
    definition=GOOGLE_SEARCH_TOOL,
    executor=execute_google_search,
    emoji="🔍",
    needs_bot_session=True,
    providers={"google"},  # Google only — Claude has native web_search
)
