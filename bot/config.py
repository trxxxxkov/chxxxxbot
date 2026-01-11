"""Application configuration and constants.

This module contains all configuration constants used throughout the bot
application. No secrets should be stored here - they are read from Docker
secrets in main.py.
"""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional

# Timeouts
REQUEST_TIMEOUT = 30  # seconds
POLLING_TIMEOUT = 60  # seconds

# Message limits
MAX_MESSAGE_LENGTH = 4096  # Telegram limit
MAX_CAPTION_LENGTH = 1024  # Telegram limit

# Bot settings
BOT_NAME = "LLM Bot"
BOT_DESCRIPTION = "Telegram bot with LLM access"

# Database settings
DATABASE_POOL_SIZE = 5  # Base connection pool size
DATABASE_MAX_OVERFLOW = 10  # Additional connections during load spikes
DATABASE_POOL_TIMEOUT = 30  # seconds
DATABASE_POOL_RECYCLE = 3600  # Recycle connections after 1 hour
DATABASE_ECHO = False  # Set True for SQL debugging

# Claude API settings
CLAUDE_MAX_TOKENS = 4096  # Max tokens to generate per response
CLAUDE_TEMPERATURE = 1.0  # Sampling temperature (0.0-2.0)
CLAUDE_TIMEOUT = 60  # API request timeout in seconds
CLAUDE_TOKEN_BUFFER_PERCENT = 0.10  # Safety buffer for token counting

# Files API settings (Phase 1.5)
FILES_API_TTL_HOURS = int(os.getenv("FILES_API_TTL_HOURS", "24"))


@dataclass
class ModelConfig:  # pylint: disable=too-many-instance-attributes
    """Universal model configuration for any LLM provider.

    Designed to support Claude, OpenAI, Google, and future providers.
    Uses flexible capabilities dict for provider-specific features.

    Attributes:
        provider: Provider name ("claude", "openai", "google").
        model_id: Provider-specific model ID for API calls.
        alias: Short alias within provider ("sonnet", "haiku", "opus").
        display_name: Human-readable name for UI.

        context_window: Maximum input tokens.
        max_output: Maximum output tokens.

        pricing_input: Input token cost per million tokens (USD).
        pricing_output: Output token cost per million tokens (USD).
        pricing_cache_write_5m: 5-minute cache write cost (or None).
        pricing_cache_write_1h: 1-hour cache write cost (or None).
        pricing_cache_read: Cache read cost (or None).

        latency_tier: "fastest" | "fast" | "moderate" | "slow"

        capabilities: Dict with boolean flags for provider-specific features.
            Claude: {"extended_thinking", "effort", "vision", "streaming"}
            OpenAI: {"function_calling", "vision", "json_mode"}
            Google: {"grounding", "code_execution", "vision"}
    """

    # Identity
    provider: str
    model_id: str
    alias: str
    display_name: str

    # Technical specs
    context_window: int
    max_output: int

    # Pricing (None if not supported by provider)
    pricing_input: float
    pricing_output: float
    pricing_cache_write_5m: Optional[float]
    pricing_cache_write_1h: Optional[float]
    pricing_cache_read: Optional[float]

    # Performance
    latency_tier: str

    # Provider-specific capabilities (flexible)
    capabilities: dict[str, bool]

    def get_full_id(self) -> str:
        """Get full model identifier: 'provider:alias'.

        Examples:
            - claude:sonnet
            - openai:gpt4
            - google:gemini

        Returns:
            Composite identifier string.
        """
        return f"{self.provider}:{self.alias}"

    def has_capability(self, capability: str) -> bool:
        """Check if model supports specific capability.

        Args:
            capability: Capability name to check.

        Returns:
            True if capability supported, False otherwise.
        """
        return self.capabilities.get(capability, False)


# ============================================================================
# Model Registry (Universal - supports Claude, OpenAI, Google, and future)
# ============================================================================
# Key format: "provider:alias" (e.g., "claude:sonnet", "openai:gpt4")
# Pricing verified: https://platform.claude.com/docs/en/about-claude/pricing

MODEL_REGISTRY: dict[str, ModelConfig] = {
    # ============ Claude 4.5 Models (Phase 1.4.1) ============
    # Ordered by capability: Haiku (fastest) -> Sonnet (balanced) -> Opus (most capable)
    "claude:haiku":
        ModelConfig(
            provider="claude",
            model_id="claude-haiku-4-5-20251001",
            alias="haiku",
            display_name="Claude Haiku 4.5",
            context_window=200_000,
            max_output=64_000,
            pricing_input=1.0,
            pricing_output=5.0,
            pricing_cache_write_5m=1.25,  # 1.25x multiplier
            pricing_cache_write_1h=2.0,  # 2x multiplier
            pricing_cache_read=0.10,  # 0.1x multiplier
            latency_tier="fastest",
            capabilities={
                "extended_thinking": True,
                "interleaved_thinking": True,
                "effort": False,
                "context_awareness": True,
                "vision": True,
                "streaming": True,
                "prompt_caching": True,
            },
        ),
    "claude:sonnet":
        ModelConfig(
            provider="claude",
            model_id="claude-sonnet-4-5-20250929",
            alias="sonnet",
            display_name="Claude Sonnet 4.5",
            context_window=200_000,  # 200K (1M with beta, but we use 200K)
            max_output=64_000,
            pricing_input=3.0,
            pricing_output=15.0,
            pricing_cache_write_5m=3.75,  # 1.25x multiplier
            pricing_cache_write_1h=6.0,  # 2x multiplier
            pricing_cache_read=0.30,  # 0.1x multiplier
            latency_tier="fast",
            capabilities={
                "extended_thinking": True,
                "interleaved_thinking": True,
                "effort": False,
                "context_awareness": True,
                "vision": True,
                "streaming": True,
                "prompt_caching": True,
            },
        ),
    "claude:opus":
        ModelConfig(
            provider="claude",
            model_id="claude-opus-4-5-20251101",
            alias="opus",
            display_name="Claude Opus 4.5",
            context_window=200_000,
            max_output=64_000,
            pricing_input=5.0,
            pricing_output=25.0,
            pricing_cache_write_5m=6.25,  # 1.25x multiplier
            pricing_cache_write_1h=10.0,  # 2x multiplier
            pricing_cache_read=0.50,  # 0.1x multiplier
            latency_tier="moderate",
            capabilities={
                "extended_thinking": True,
                "interleaved_thinking": True,
                "effort": True,  # Only Opus 4.5 supports effort parameter!
                "context_awareness": True,
                "vision": True,
                "streaming": True,
                "prompt_caching": True,
            },
        ),
    # ============ Future: OpenAI Models (Phase 3.4) ============
    # "openai:gpt4": ModelConfig(
    #     provider="openai",
    #     model_id="gpt-4-turbo-2024-04-09",
    #     alias="gpt4",
    #     display_name="GPT-4 Turbo",
    #     context_window=128_000,
    #     max_output=4_096,
    #     pricing_input=10.0,
    #     pricing_output=30.0,
    #     pricing_cache_write_5m=None,  # OpenAI doesn't have prompt caching
    #     pricing_cache_write_1h=None,
    #     pricing_cache_read=None,
    #     latency_tier="fast",
    #     capabilities={
    #         "function_calling": True,
    #         "vision": True,
    #         "json_mode": True,
    #         "streaming": True,
    #     },
    # ),
    # ============ Future: Google Models (Phase 3.4) ============
    # "google:gemini": ModelConfig(
    #     provider="google",
    #     model_id="gemini-1.5-pro",
    #     alias="gemini",
    #     display_name="Gemini 1.5 Pro",
    #     context_window=1_000_000,
    #     max_output=8_192,
    #     pricing_input=3.5,
    #     pricing_output=10.5,
    #     pricing_cache_write_5m=None,
    #     pricing_cache_write_1h=None,
    #     pricing_cache_read=None,
    #     latency_tier="moderate",
    #     capabilities={
    #         "grounding": True,
    #         "code_execution": True,
    #         "vision": True,
    #         "streaming": True,
    #     },
    # ),
}

# Default model (Claude Sonnet 4.5 - best balance of intelligence, speed, cost)
DEFAULT_MODEL_ID = "claude:sonnet"

# ============================================================================
# System Prompt Architecture
# ============================================================================
# Phase 1.4.2 will implement 3-level system prompt composition:
#
# 1. GLOBAL_SYSTEM_PROMPT (below) - Always cached, same for all users
#    - Base instructions for Claude
#    - Tool descriptions (code execution, image generation, etc.)
#    - General behavior guidelines
#
# 2. User.custom_prompt (per user) - Rarely changes, can be cached
#    - Personal preferences (language, tone, style)
#    - User-specific instructions
#
# 3. Thread.files_context (per thread) - Dynamic, NOT cached
#    - List of files available in current thread
#    - Auto-generated when files are added
#
# Final prompt = GLOBAL + User.custom_prompt + Thread.files_context
# ============================================================================

GLOBAL_SYSTEM_PROMPT = (
    # Phase 1.5 Stage 6: Enhanced with Claude 4.5 best practices
    # Reference:
    # https://platform.claude.com/docs/en/build-with-claude/...
    # .../prompt-engineering/claude-4-best-practices
    # Changes:
    # - Explicit instructions with context (WHY)
    # - XML tags for structured sections
    # - Parallel tool calling optimization
    # - Proactive tool use (default_to_action)
    # - Thinking after tool use for reflection
    # - Context awareness (automatic compaction)
    # - Communication style guidance
    "# Identity\n"
    "You are Claude, an AI assistant created by Anthropic. The current model is Claude Sonnet 4.5. "
    "You are communicating via a Telegram bot that allows users to have "
    "conversations with you in separate topics (threads).\n\n"
    "# Purpose\n"
    "Your purpose is to provide helpful, accurate, and thoughtful responses to user "
    "questions and requests. Users rely on you for information, analysis, creative "
    "tasks, problem-solving, and general assistance.\n\n"
    "# Communication Style\n"
    "- **Be concise and direct**: Provide clear answers without unnecessary preamble. "
    "Claude 4.5 users expect efficient, focused responses.\n"
    "- **Use markdown formatting**: Structure your responses with headers, lists, "
    "code blocks, and emphasis to improve readability.\n"
    "- **Be honest about uncertainty**: If you don't know something or are uncertain, "
    "state this clearly. When lacking information, acknowledge limitations rather than guessing.\n"
    "- **Break down complexity**: When explaining complex topics, break them into "
    "logical parts. Use examples and analogies when helpful.\n"
    "- **Provide updates after tool use**: After completing tasks that involve tool use, "
    "provide a brief summary of what you accomplished so users can track your progress.\n\n"
    "# Approach\n"
    "- **Consider context carefully**: Evaluate what the user is asking and why they "
    "might need this information before responding.\n"
    "- **Ask clarifying questions**: When a request is ambiguous, ask specific "
    "questions to understand the user's needs better.\n"
    "- **Provide actionable information**: Focus on practical, useful responses rather "
    "than abstract or theoretical answers unless specifically requested.\n"
    "- **Adapt to user preferences**: Pay attention to how users communicate and adjust "
    "your responses accordingly (formality, detail level, language).\n\n"
    "# Thread Context\n"
    "Each conversation takes place in a separate Telegram topic (thread). Context from "
    "previous messages in the same thread is maintained, but threads are independent "
    "of each other. Consider the full conversation history when formulating responses.\n\n"
    "<context_awareness>\n"
    "Your context window will be automatically compacted as it approaches its limit, "
    "allowing you to continue working indefinitely. Therefore, complete all tasks fully "
    "even if approaching token budget limits. Never artificially stop tasks early due to "
    "context concerns.\n"
    "</context_awareness>\n\n"
    "<default_to_action>\n"
    "Implement changes rather than only suggesting them when appropriate. This is important "
    "because users expect you to be helpful and take action to solve their problems, not just "
    "provide advice. If the user's intent is unclear, infer the most useful likely action and "
    "proceed, using tools to discover any missing details. Try to infer whether a tool call "
    "(e.g., file edit, code execution) is intended and act accordingly. However, for ambiguous "
    "requests, default to providing information and recommendations first.\n"
    "</default_to_action>\n\n"
    "<use_parallel_tool_calls>\n"
    "When calling multiple tools without dependencies between them, "
    "make all independent tool calls in parallel. This improves "
    "performance by running operations simultaneously rather than "
    "waiting for each to complete sequentially.\n\n"
    "Examples of parallel execution:\n"
    "- Verifying multiple URLs → Call web_fetch for all URLs simultaneously\n"
    "- Analyzing multiple files → Call analyze_pdf/analyze_image in parallel\n"
    "- Reading multiple files → Call all reads at once\n"
    "- Multiple web searches → Run searches concurrently\n\n"
    "For dependent operations where one tool's output informs "
    "another's input, call them sequentially and provide concrete "
    "values rather than placeholders.\n"
    "</use_parallel_tool_calls>\n\n"
    "<reflection_after_tool_use>\n"
    "After receiving tool results, carefully reflect on their quality and determine optimal next "
    "steps before proceeding. This reflection is crucial because it helps you catch errors early, "
    "validate assumptions, and adjust your approach if needed. Use your thinking to plan and "
    "iterate based on new information, then take the best next action.\n"
    "</reflection_after_tool_use>\n\n"
    "# Available Tools\n"
    "You have access to several specialized tools. Use them proactively when appropriate:\n\n"
    "**Vision & Documents:**\n"
    "- `analyze_image`: Fast image analysis using Claude Vision (OCR, objects, scenes, charts)\n"
    "- `analyze_pdf`: Fast PDF analysis using Claude PDF capabilities (text + visual)\n\n"
    "**Audio & Video:**\n"
    "- `transcribe_audio`: Convert speech to text using Whisper (audio/video files)\n"
    "  - Supports 90+ languages with auto-detection\n"
    "  - Works with MP3, WAV, FLAC, OGG, MP4, MOV, AVI, etc.\n"
    "  - Cost: ~$0.006 per minute\n"
    "  - Note: Voice messages are AUTO-TRANSCRIBED on upload (check message text)\n\n"
    "**Image Generation:**\n"
    "- `generate_image`: Create high-quality images up to 4K resolution\n"
    "  - Model: Google Nano Banana Pro (gemini-3-pro-image-preview)\n"
    "  - Features: Up to 4K resolution, Google Search grounding for references\n"
    "  - Parameters you control: aspect_ratio (1:1, 3:4, 4:3, 9:16, "
    "16:9), image_size (1K, 2K, 4K)\n"
    "  - Cost: $0.134 per image (1K/2K), $0.24 per image (4K)\n"
    "  - English prompts only (max 480 tokens)\n"
    "  - Generates ONE image per call\n"
    "  - Generated images are automatically sent to user and added to 'Available files'\n\n"
    "**Code Execution:**\n"
    "- `execute_python`: Run Python code in sandboxed environment\n"
    "  - Process files (convert, analyze, transform)\n"
    "  - Generate outputs (charts, reports, PDFs, etc.)\n"
    "  - Install packages with requirements parameter\n"
    "  - Full file I/O: read user files, create new files\n\n"
    "<web_access_tools>\n"
    "**Web Access:**\n"
    "You have two powerful tools for accessing web content. Use them when "
    "users reference external information, links, or online resources.\n\n"
    "- `web_search`: Search the web for current information, news, research\n"
    "  - Use for: Finding recent information, comparing sources, research queries\n"
    "  - Cost: $0.01 per search\n"
    "  - Returns: URLs, titles, snippets with citations\n\n"
    "- `web_fetch`: Fetch and read complete web pages or online PDFs\n"
    "  - Use for: Reading articles, checking online profiles, verifying links\n"
    "  - Cost: FREE (only tokens for content)\n"
    "  - Supports: HTML pages, online PDFs, public URLs\n\n"
    "**When to use web_fetch for verification:**\n"
    "When users upload documents (PDFs, resumes, reports) containing URLs "
    "or references to online profiles, use `web_fetch` to verify claims by "
    "checking the actual sources. This helps ensure your analysis is "
    "grounded in real data rather than assumptions.\n\n"
    "Examples where web_fetch is helpful:\n"
    "- PDF mentions \"eLibrary ID: 1149143\" → Fetch "
    "elibrary.ru/author_profile.asp?id=1149143 to see actual "
    "publications\n"
    "- Document references \"ORCID: 0000-0003-3304-4934\" → Fetch "
    "orcid.org/0000-0003-3304-4934 to verify profile\n"
    "- Resume lists \"Google Scholar\" → Fetch scholar.google.com "
    "profile to check publication count\n"
    "- User says \"check this article: https://...\" → Use web_fetch to read the full content\n"
    "- PDF contains research citations → Fetch source papers to verify accuracy\n\n"
    "**Research workflow (for verification tasks):**\n"
    "1. Extract all URLs and identifiers from documents using "
    "analyze_pdf\n"
    "2. Use web_fetch to check each source (run multiple fetches in "
    "parallel when possible)\n"
    "3. Compare claimed information with actual data from sources\n"
    "4. Track confidence levels: verified vs. claimed vs. contradicted\n"
    "5. Provide evidence-based conclusions with source citations\n\n"
    "When verifying information from web sources, call web_fetch to obtain "
    "actual data rather than speculating about what the sources might "
    "contain. Ground your answers in real information.\n"
    "</web_access_tools>\n\n"
    "<tool_selection_guidelines>\n"
    "**Tool Selection Guidelines:**\n"
    "- Images → `analyze_image` (fastest)\n"
    "- PDFs → `analyze_pdf` (fastest)\n"
    "- Speech/audio → `transcribe_audio`\n"
    "- File processing → `execute_python`\n"
    "- Current info/research → `web_search`, `web_fetch`\n"
    "- Link verification → `web_fetch` (fetch to verify, rather than guessing)\n"
    "</tool_selection_guidelines>\n\n"
    "# Working with Files\n"
    "When users upload files (photos, PDFs, audio, video, "
    "documents), they appear in 'Available files' section "
    "with file_id and filename.\n\n"
    "**Processing uploaded files:**\n"
    "- Images → Use `analyze_image` (fastest, direct vision analysis)\n"
    "- PDFs → Use `analyze_pdf` (fastest, direct PDF+vision analysis)\n"
    "- Audio/Video → Use `transcribe_audio` (speech-to-text)\n"
    "- Other files → Use `execute_python` (universal file processing)\n\n"
    "**Input files for execute_python:**\n"
    "- Specify file_inputs parameter with list of {file_id, name} from 'Available files'\n"
    "- Files will be uploaded to /tmp/inputs/{name} in sandbox before execution\n"
    "- Example: file_inputs=[{\"file_id\": \"file_abc...\", \"name\": \"document.pdf\"}]\n"
    "- In code: open('/tmp/inputs/document.pdf', 'rb')\n\n"
    "**Output files (IMPORTANT - this is how you return files to "
    "users):**\n"
    "- Save to /tmp/ or subdirectories (any format: PDF, PNG, CSV, XLSX, "
    "TXT, etc.)\n"
    "- Bot automatically downloads, uploads to Files API, sends to "
    "Telegram user\n"
    "- Generated files are added to context ('Available files') for future "
    "use\n"
    "- Example: plt.savefig('/tmp/chart.png') or "
    "pdf.write('/tmp/report.pdf')\n\n"
    "**Workflow example:**\n"
    "User: 'Convert data.csv to PDF report with chart'\n"
    "1. Call execute_python with file_inputs=[{file_id from 'Available "
    "files', name='data.csv'}]\n"
    "2. Code: read /tmp/inputs/data.csv, generate /tmp/report.pdf and "
    "/tmp/chart.png\n"
    "3. Bot sends report.pdf and chart.png to user\n"
    "4. Files appear in 'Available files', you can reference them: "
    "'I created report.pdf...'\n\n"
    "**Always use execute_python to generate files** - it's the ONLY way "
    "to return files to users.")

# ============================================================================
# Model Registry Helper Functions
# ============================================================================


def get_model(full_id: str) -> ModelConfig:
    """Get model by full ID (provider:alias).

    Args:
        full_id: Composite identifier like "claude:sonnet" or "openai:gpt4".

    Returns:
        ModelConfig for requested model.

    Raises:
        KeyError: If model not found in registry.

    Examples:
        >>> model = get_model("claude:sonnet")
        >>> model.display_name
        'Claude Sonnet 4.5'
    """
    if full_id not in MODEL_REGISTRY:
        available = list(MODEL_REGISTRY.keys())
        raise KeyError(f"Model '{full_id}' not found in registry. "
                       f"Available models: {available}")
    return MODEL_REGISTRY[full_id]


def get_model_by_provider_id(provider: str, model_id: str) -> ModelConfig:
    """Get model by provider and exact model_id.

    Useful for reverse lookup from API responses.

    Args:
        provider: Provider name ("claude", "openai", "google").
        model_id: Exact model ID (e.g., "claude-sonnet-4-5-20250929").

    Returns:
        ModelConfig for requested model.

    Raises:
        ValueError: If model not found.

    Examples:
        >>> model = get_model_by_provider_id("claude",
        ...                                  "claude-sonnet-4-5-20250929")
        >>> model.alias
        'sonnet'
    """
    for model in MODEL_REGISTRY.values():
        if model.provider == provider and model.model_id == model_id:
            return model

    raise ValueError(f"Model with provider='{provider}' and "
                     f"model_id='{model_id}' not found in registry.")


def get_models_by_provider(provider: str) -> list[ModelConfig]:
    """Get all models for specific provider.

    Args:
        provider: Provider name ("claude", "openai", "google").

    Returns:
        List of ModelConfig objects for this provider, in registry order
        (Haiku -> Sonnet -> Opus for Claude).

    Examples:
        >>> claude_models = get_models_by_provider("claude")
        >>> len(claude_models)
        3
    """
    # Preserve order from MODEL_REGISTRY (dict preserves insertion order in Python 3.7+)
    models = [
        model for model in MODEL_REGISTRY.values() if model.provider == provider
    ]
    return models


def get_default_model() -> ModelConfig:
    """Get default model (Claude Sonnet 4.5).

    Returns:
        Default ModelConfig.
    """
    return MODEL_REGISTRY[DEFAULT_MODEL_ID]


def list_all_models() -> list[tuple[str, str]]:
    """List all available models (id, display_name).

    Returns:
        List of tuples (full_id, display_name) sorted by provider and alias.

    Examples:
        >>> models = list_all_models()
        >>> models
        [('claude:haiku', 'Claude Haiku 4.5'),
         ('claude:opus', 'Claude Opus 4.5'),
         ('claude:sonnet', 'Claude Sonnet 4.5')]
    """
    items = [(full_id, model.display_name)
             for full_id, model in MODEL_REGISTRY.items()]
    return sorted(items, key=lambda x: x[0])


# ============================================================================
# Payment System Configuration (Phase 2.1)
# ============================================================================

# Stars to USD conversion rate (market rate, BEFORE commissions)
STARS_TO_USD_RATE: float = 0.013  # $0.013 per Star (~$13 per 1000 Stars)

# ============================================================================
# External API Pricing (Phase 2.1: Cost Tracking)
# ============================================================================

# E2B Code Interpreter pricing
# Based on E2B pricing: https://e2b.dev/pricing
# Standard tier: $0.00005 per second (~$0.18 per hour) of sandbox runtime
E2B_COST_PER_SECOND: float = 0.00005  # $0.00005 per second

# OpenAI Whisper API pricing
# Already tracked in transcribe_audio tool: $0.006 per minute
# Reference: https://openai.com/api/pricing/
WHISPER_COST_PER_MINUTE: float = 0.006  # $0.006 per minute

# Google Gemini Image Generation pricing
# Already tracked in generate_image tool
# 1K/2K: $0.134 per image, 4K: $0.240 per image
# Reference: https://ai.google.dev/pricing
GEMINI_IMAGE_COST_1K: float = 0.134  # $0.134 per 1K/2K image
GEMINI_IMAGE_COST_4K: float = 0.240  # $0.240 per 4K image

# Commission rates for formula: y = x * (1 - k1 - k2 - k3)
TELEGRAM_WITHDRAWAL_FEE: float = 0.35  # k1: 35% Telegram withdrawal commission
TELEGRAM_TOPICS_FEE: float = 0.15  # k2: 15% Topics in private chats commission
DEFAULT_OWNER_MARGIN: float = 0.0  # k3: 0% Default owner margin (configurable)

# Balance settings
STARTER_BALANCE_USD: float = 0.10  # New users get $0.10 starter balance
MINIMUM_BALANCE_FOR_REQUEST: float = 0.0  # Allow requests while balance > 0

# Refund settings
REFUND_PERIOD_DAYS: int = 30  # Maximum days for refund eligibility

# Predefined Stars packages (for /buy command)
STARS_PACKAGES: list[dict[str, int | str]] = [
    {
        "stars": 10,
        "label": "Micro"
    },
    {
        "stars": 50,
        "label": "Starter"
    },
    {
        "stars": 100,
        "label": "Basic"
    },
    {
        "stars": 250,
        "label": "Standard"
    },
    {
        "stars": 500,
        "label": "Premium"
    },
]

# Custom amount range
MIN_CUSTOM_STARS: int = 1
MAX_CUSTOM_STARS: int = 2500

# Payment invoice customization
PAYMENT_INVOICE_TITLE: str = "Bot Balance Top-up"
PAYMENT_INVOICE_DESCRIPTION_TEMPLATE: str = (
    "Pay {stars_amount}⭐ to add ${usd_amount:.2f} to your balance.\n\n"
    "💡 After payment, you'll receive a transaction ID for refunds.")

# Privileged users (loaded from secrets at startup)
PRIVILEGED_USERS: set[int] = set(
)  # Populated from secrets/privileged_users.txt

# ============================================================================
# Database Configuration
# ============================================================================


def get_database_url() -> str:
    """Construct PostgreSQL connection URL from environment and secrets.

    Reads password from Docker secret and constructs async PostgreSQL URL
    for use with SQLAlchemy and asyncpg.

    Connection parameters are read from environment variables with defaults:
    - DATABASE_HOST: postgres (default)
    - DATABASE_PORT: 5432 (default)
    - DATABASE_USER: postgres (default)
    - DATABASE_NAME: postgres (default)

    Returns:
        Connection URL in format:
            postgresql+asyncpg://user:pass@host:port/database

    Raises:
        FileNotFoundError: If postgres_password secret not found.
    """
    # Read password from Docker secret
    secret_path = Path("/run/secrets/postgres_password")
    password = secret_path.read_text(encoding='utf-8').strip()

    # Connection parameters (from environment or defaults)
    host = os.getenv("DATABASE_HOST", "postgres")
    port = os.getenv("DATABASE_PORT", "5432")
    user = os.getenv("DATABASE_USER", "postgres")
    database = os.getenv("DATABASE_NAME", "postgres")

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
