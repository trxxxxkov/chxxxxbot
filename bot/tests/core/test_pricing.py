"""Tests for core/pricing.py - cost calculation utilities.

Pure function tests for all pricing calculations.

NO __init__.py - use direct import:
    pytest tests/core/test_pricing.py
"""

from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import patch

from core.pricing import calculate_cache_write_cost
from core.pricing import calculate_claude_cost
from core.pricing import calculate_e2b_cost
from core.pricing import calculate_gemini_image_cost
from core.pricing import calculate_web_search_cost
from core.pricing import calculate_whisper_cost
from core.pricing import cost_to_float
from core.pricing import E2B_COST_PER_SECOND
from core.pricing import format_cost
from core.pricing import GEMINI_IMAGE_COST_4K
from core.pricing import GEMINI_IMAGE_COST_STANDARD
from core.pricing import WEB_SEARCH_COST_PER_REQUEST
from core.pricing import WHISPER_COST_PER_MINUTE
import pytest

# =============================================================================
# Test Fixtures
# =============================================================================


@dataclass
class MockModelConfig:  # pylint: disable=too-many-instance-attributes
    """Mock model config for testing Claude pricing."""

    provider: str
    model_id: str
    alias: str
    display_name: str
    pricing_input: float
    pricing_output: float
    pricing_cache_read: float | None = None
    pricing_cache_write_5m: float | None = None
    pricing_cache_write_1h: float | None = None


@pytest.fixture
def mock_model_registry():
    """Create mock MODEL_REGISTRY with test models."""
    return {
        "claude:haiku":
            MockModelConfig(
                provider="claude",
                model_id="claude-haiku-test",
                alias="haiku",
                display_name="Test Haiku",
                pricing_input=1.0,  # $1 per 1M input tokens
                pricing_output=5.0,  # $5 per 1M output tokens
                pricing_cache_read=0.1,  # $0.10 per 1M cache read
                pricing_cache_write_5m=1.25,  # $1.25 per 1M cache write (1.25x)
                pricing_cache_write_1h=2.0,  # $2.00 per 1M cache write (2x)
            ),
        "claude:sonnet":
            MockModelConfig(
                provider="claude",
                model_id="claude-sonnet-test",
                alias="sonnet",
                display_name="Test Sonnet",
                pricing_input=3.0,  # $3 per 1M input tokens
                pricing_output=15.0,  # $15 per 1M output tokens
                pricing_cache_read=0.30,  # $0.30 per 1M cache read
                pricing_cache_write_5m=3.75,  # $3.75 per 1M cache write (1.25x)
                pricing_cache_write_1h=6.0,  # $6.00 per 1M cache write (2x)
            ),
        "claude:opus":
            MockModelConfig(
                provider="claude",
                model_id="claude-opus-test",
                alias="opus",
                display_name="Test Opus",
                pricing_input=15.0,  # $15 per 1M input tokens
                pricing_output=75.0,  # $75 per 1M output tokens
                pricing_cache_read=1.5,  # $1.50 per 1M cache read
                pricing_cache_write_5m=18.75,  # $18.75 per 1M cache write (1.25x)
                pricing_cache_write_1h=30.0,  # $30.00 per 1M cache write (2x)
            ),
        "claude:no_cache":
            MockModelConfig(
                provider="claude",
                model_id="claude-no-cache",
                alias="nocache",
                display_name="Test No Cache",
                pricing_input=2.0,
                pricing_output=10.0,
                pricing_cache_read=None,  # No cache support
                pricing_cache_write_5m=None,
                pricing_cache_write_1h=None,
            ),
    }


# =============================================================================
# Whisper Pricing Tests
# =============================================================================


class TestCalculateWhisperCost:
    """Tests for calculate_whisper_cost function."""

    @pytest.mark.parametrize(
        "duration_seconds,expected",
        [
            (60, Decimal("0.006")),  # 1 minute = $0.006
            (120, Decimal("0.012")),  # 2 minutes = $0.012
            (30, Decimal("0.003")),  # 30 seconds = $0.003
            (90, Decimal("0.009")),  # 1.5 minutes = $0.009
            (0, Decimal("0")),  # 0 seconds = $0
        ])
    def test_whisper_cost_calculations(self, duration_seconds, expected):
        """Should calculate Whisper cost correctly."""
        result = calculate_whisper_cost(duration_seconds)
        assert result == expected

    def test_whisper_cost_fractional_seconds(self):
        """Should handle fractional seconds."""
        # 45.5 seconds = 0.7583... minutes
        result = calculate_whisper_cost(45.5)
        expected = Decimal("45.5") / Decimal("60") * WHISPER_COST_PER_MINUTE
        assert result == expected

    def test_whisper_cost_long_audio(self):
        """Should handle long audio files."""
        # 1 hour = 3600 seconds = 60 minutes = $0.36
        result = calculate_whisper_cost(3600)
        assert result == Decimal("0.36")

    def test_whisper_cost_returns_decimal(self):
        """Should return Decimal type for precision."""
        result = calculate_whisper_cost(60)
        assert isinstance(result, Decimal)


# =============================================================================
# E2B Sandbox Pricing Tests
# =============================================================================


class TestCalculateE2bCost:
    """Tests for calculate_e2b_cost function."""

    @pytest.mark.parametrize(
        "duration_seconds,expected",
        [
            (1, Decimal("0.00005")),  # 1 second
            (60, Decimal("0.003")),  # 1 minute
            (3600, Decimal("0.18")),  # 1 hour
            (0, Decimal("0")),  # 0 seconds
        ])
    def test_e2b_cost_calculations(self, duration_seconds, expected):
        """Should calculate E2B cost correctly."""
        result = calculate_e2b_cost(duration_seconds)
        assert result == expected

    def test_e2b_cost_fractional_seconds(self):
        """Should handle fractional seconds."""
        result = calculate_e2b_cost(1.5)
        expected = Decimal("1.5") * E2B_COST_PER_SECOND
        assert result == expected

    def test_e2b_cost_returns_decimal(self):
        """Should return Decimal type for precision."""
        result = calculate_e2b_cost(100)
        assert isinstance(result, Decimal)


# =============================================================================
# Gemini Image Pricing Tests
# =============================================================================


class TestCalculateGeminiImageCost:
    """Tests for calculate_gemini_image_cost function."""

    @pytest.mark.parametrize(
        "resolution,expected",
        [
            ("1024x1024", GEMINI_IMAGE_COST_STANDARD),
            ("2048x2048", GEMINI_IMAGE_COST_STANDARD),
            ("4096x4096", GEMINI_IMAGE_COST_4K),
            ("1024x4096", GEMINI_IMAGE_COST_4K),  # Contains 4096
            ("4096x1024", GEMINI_IMAGE_COST_4K),  # Contains 4096
        ])
    def test_gemini_image_cost_by_resolution(self, resolution, expected):
        """Should return correct cost based on resolution."""
        result = calculate_gemini_image_cost(resolution)
        assert result == expected

    def test_gemini_default_resolution(self):
        """Should default to standard cost when no resolution provided."""
        result = calculate_gemini_image_cost()
        assert result == GEMINI_IMAGE_COST_STANDARD

    def test_gemini_image_cost_returns_decimal(self):
        """Should return Decimal type."""
        result = calculate_gemini_image_cost("2048x2048")
        assert isinstance(result, Decimal)


# =============================================================================
# Web Search Pricing Tests
# =============================================================================


class TestCalculateWebSearchCost:
    """Tests for calculate_web_search_cost function."""

    @pytest.mark.parametrize(
        "request_count,expected",
        [
            (1, Decimal("0.01")),  # 1 request = $0.01
            (10, Decimal("0.10")),  # 10 requests = $0.10
            (100, Decimal("1.00")),  # 100 requests = $1.00
            (1000, Decimal("10.00")),  # 1000 requests = $10.00
            (0, Decimal("0")),  # 0 requests = $0
        ])
    def test_web_search_cost_calculations(self, request_count, expected):
        """Should calculate web search cost correctly."""
        result = calculate_web_search_cost(request_count)
        assert result == expected

    def test_web_search_cost_returns_decimal(self):
        """Should return Decimal type."""
        result = calculate_web_search_cost(5)
        assert isinstance(result, Decimal)


# =============================================================================
# Claude API Pricing Tests
# =============================================================================


class TestCalculateClaudeCost:
    """Tests for calculate_claude_cost function."""

    def test_basic_input_output_cost(self, mock_model_registry):
        """Should calculate basic input/output costs."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Haiku: $1/1M input, $5/1M output
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=1000,  # 0.001M * $1 = $0.001
                output_tokens=500,  # 0.0005M * $5 = $0.0025
            )
            expected = Decimal("0.001") + Decimal("0.0025")
            assert result == expected

    def test_sonnet_pricing(self, mock_model_registry):
        """Should use correct pricing for Sonnet model."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Sonnet: $3/1M input, $15/1M output
            result = calculate_claude_cost(
                model_id="claude-sonnet-test",
                input_tokens=1_000_000,  # $3
                output_tokens=100_000,  # $1.50
            )
            expected = Decimal("3") + Decimal("1.5")
            assert result == expected

    def test_opus_pricing(self, mock_model_registry):
        """Should use correct pricing for Opus model."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Opus: $15/1M input, $75/1M output
            result = calculate_claude_cost(
                model_id="claude-opus-test",
                input_tokens=100_000,  # $1.50
                output_tokens=10_000,  # $0.75
            )
            expected = Decimal("1.5") + Decimal("0.75")
            assert result == expected

    def test_cache_read_tokens(self, mock_model_registry):
        """Should calculate cache read token cost."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Haiku: $0.10/1M cache read
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=1_000_000,  # $0.10
            )
            assert result == Decimal("0.1")

    def test_cache_creation_tokens_1h_default(self, mock_model_registry):
        """Should calculate cache creation cost with 1h TTL (default)."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Haiku: $2.00/1M cache write for 1h TTL (default)
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=0,
                output_tokens=0,
                cache_creation_tokens=1_000_000,  # $2.00 for 1h
            )
            assert result == Decimal("2.0")

    def test_cache_creation_tokens_5m(self, mock_model_registry):
        """Should calculate cache creation cost with 5m TTL."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Haiku: $1.25/1M cache write for 5m TTL
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=0,
                output_tokens=0,
                cache_creation_tokens=1_000_000,  # $1.25 for 5m
                cache_ttl="5m",
            )
            assert result == Decimal("1.25")

    def test_thinking_tokens_billed_as_output(self, mock_model_registry):
        """Should bill thinking tokens at output token rate."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Haiku: $5/1M output (thinking uses output rate)
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=0,
                output_tokens=0,
                thinking_tokens=1_000_000,  # $5 (output rate)
            )
            assert result == Decimal("5")

    def test_combined_all_token_types(self, mock_model_registry):
        """Should correctly sum all token type costs with 1h TTL (default)."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Haiku: $1 input, $5 output, $0.10 cache read, $2.00 cache write (1h)
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=1_000_000,  # $1
                output_tokens=200_000,  # $1
                cache_read_tokens=2_000_000,  # $0.20
                cache_creation_tokens=800_000,  # $1.60 (0.8M * $2.00 for 1h)
                thinking_tokens=100_000,  # $0.50
            )
            # $1 + $1 + $0.20 + $1.60 + $0.50 = $4.30
            expected = Decimal("1") + Decimal("1") + Decimal("0.2") + Decimal(
                "1.6") + Decimal("0.5")
            assert result == expected

    def test_model_without_cache_support(self, mock_model_registry):
        """Should handle models without cache pricing."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Model with None cache pricing - both TTLs should work
            for ttl in ["5m", "1h"]:
                result = calculate_claude_cost(
                    model_id="claude-no-cache",
                    input_tokens=1_000_000,
                    output_tokens=500_000,
                    cache_read_tokens=1_000_000,  # Should be ignored
                    cache_creation_tokens=1_000_000,  # Should be ignored
                    cache_ttl=ttl,
                )
                # Only input + output: $2 + $5 = $7
                expected = Decimal("2") + Decimal("5")
                assert result == expected

    def test_unknown_model_returns_zero(self, mock_model_registry):
        """Should return 0 for unknown model IDs."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            result = calculate_claude_cost(
                model_id="unknown-model",
                input_tokens=1_000_000,
                output_tokens=500_000,
            )
            assert result == Decimal("0")

    def test_zero_tokens_returns_zero(self, mock_model_registry):
        """Should return 0 when all token counts are 0."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=0,
                output_tokens=0,
            )
            assert result == Decimal("0")

    def test_returns_decimal_type(self, mock_model_registry):
        """Should return Decimal for precision."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=1000,
                output_tokens=500,
            )
            assert isinstance(result, Decimal)

    def test_large_token_counts(self, mock_model_registry):
        """Should handle large token counts without overflow."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # 100M tokens
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=100_000_000,  # $100
                output_tokens=50_000_000,  # $250
            )
            expected = Decimal("100") + Decimal("250")
            assert result == expected

    def test_small_token_counts_precision(self, mock_model_registry):
        """Should maintain precision for small token counts."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # 1 token - very small cost
            result = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=1,
                output_tokens=1,
            )
            # 1 token = 0.000001M tokens
            # Input: 0.000001 * $1 = $0.000001
            # Output: 0.000001 * $5 = $0.000005
            expected = Decimal("0.000001") + Decimal("0.000005")
            assert result == expected


# =============================================================================
# Cache Write Cost Tests
# =============================================================================


class TestCalculateCacheWriteCost:
    """Tests for calculate_cache_write_cost function."""

    def test_cache_write_cost_1h(self, mock_model_registry):
        """Should calculate cache write cost with 1h TTL."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Haiku: $2.00/1M cache write for 1h TTL
            result = calculate_cache_write_cost(
                model_id="claude-haiku-test",
                cache_creation_tokens=1_000_000,
                cache_ttl="1h",
            )
            assert result == Decimal("2.0")

    def test_cache_write_cost_5m(self, mock_model_registry):
        """Should calculate cache write cost with 5m TTL."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Haiku: $1.25/1M cache write for 5m TTL
            result = calculate_cache_write_cost(
                model_id="claude-haiku-test",
                cache_creation_tokens=1_000_000,
                cache_ttl="5m",
            )
            assert result == Decimal("1.25")

    def test_cache_write_cost_zero_tokens(self, mock_model_registry):
        """Should return 0 for zero tokens."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            result = calculate_cache_write_cost(
                model_id="claude-haiku-test",
                cache_creation_tokens=0,
            )
            assert result == Decimal("0")

    def test_cache_write_cost_unknown_model(self, mock_model_registry):
        """Should return 0 for unknown model."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            result = calculate_cache_write_cost(
                model_id="unknown-model",
                cache_creation_tokens=1_000_000,
            )
            assert result == Decimal("0")

    def test_cache_write_cost_no_cache_support(self, mock_model_registry):
        """Should return 0 for model without cache pricing."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            result = calculate_cache_write_cost(
                model_id="claude-no-cache",
                cache_creation_tokens=1_000_000,
            )
            assert result == Decimal("0")

    def test_cache_write_cost_consistency(self, mock_model_registry):
        """Cache write cost should equal difference of total cost with/without cache."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            tokens = 500_000
            # Cost with cache creation
            cost_with = calculate_claude_cost(
                model_id="claude-sonnet-test",
                input_tokens=0,
                output_tokens=0,
                cache_creation_tokens=tokens,
                cache_ttl="1h",
            )
            # Cost without cache creation
            cost_without = calculate_claude_cost(
                model_id="claude-sonnet-test",
                input_tokens=0,
                output_tokens=0,
                cache_creation_tokens=0,
                cache_ttl="1h",
            )
            # Standalone cache write cost
            cache_write = calculate_cache_write_cost(
                model_id="claude-sonnet-test",
                cache_creation_tokens=tokens,
                cache_ttl="1h",
            )
            assert cost_with - cost_without == cache_write

    def test_cache_write_cost_returns_decimal(self, mock_model_registry):
        """Should return Decimal type."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            result = calculate_cache_write_cost(
                model_id="claude-haiku-test",
                cache_creation_tokens=1000,
            )
            assert isinstance(result, Decimal)

    def test_cache_write_cost_opus(self, mock_model_registry):
        """Should calculate Opus cache write cost correctly."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Opus: $30.00/1M cache write for 1h TTL
            result = calculate_cache_write_cost(
                model_id="claude-opus-test",
                cache_creation_tokens=100_000,  # 0.1M * $30 = $3.00
                cache_ttl="1h",
            )
            assert result == Decimal("3.0")


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestFormatCost:
    """Tests for format_cost function."""

    @pytest.mark.parametrize("cost,precision,expected", [
        (Decimal("0.001234"), 6, "$0.001234"),
        (Decimal("0.001234"), 4, "$0.0012"),
        (Decimal("1.5"), 2, "$1.50"),
        (Decimal("0"), 6, "$0.000000"),
        (Decimal("123.456789"), 4, "$123.4568"),
    ])
    def test_format_cost_variations(self, cost, precision, expected):
        """Should format costs with correct precision."""
        result = format_cost(cost, precision)
        assert result == expected

    def test_format_cost_default_precision(self):
        """Should use default precision of 6."""
        result = format_cost(Decimal("0.123456789"))
        assert result == "$0.123457"


class TestCostToFloat:
    """Tests for cost_to_float function."""

    @pytest.mark.parametrize("cost,expected", [
        (Decimal("0.001234"), 0.001234),
        (Decimal("1.5"), 1.5),
        (Decimal("0"), 0.0),
        (Decimal("123.456"), 123.456),
    ])
    def test_cost_to_float_conversion(self, cost, expected):
        """Should convert Decimal to float correctly."""
        result = cost_to_float(cost)
        assert result == pytest.approx(expected)
        assert isinstance(result, float)


# =============================================================================
# Integration Tests
# =============================================================================


class TestPricingIntegration:
    """Integration tests combining multiple pricing functions."""

    def test_realistic_claude_request_cost(self, mock_model_registry):
        """Test realistic Claude API request pricing."""
        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Typical request: 5000 input, 1500 output, 1000 thinking
            cost = calculate_claude_cost(
                model_id="claude-sonnet-test",
                input_tokens=5000,
                output_tokens=1500,
                thinking_tokens=1000,
            )
            # Input: 0.005 * $3 = $0.015
            # Output: 0.0015 * $15 = $0.0225
            # Thinking: 0.001 * $15 = $0.015
            expected = Decimal("0.015") + Decimal("0.0225") + Decimal("0.015")
            assert cost == expected

    def test_realistic_whisper_plus_claude_workflow(self, mock_model_registry):
        """Test workflow: transcribe audio then process with Claude."""
        # 5-minute audio transcription
        whisper_cost = calculate_whisper_cost(300)  # $0.03

        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Claude processing the transcript
            claude_cost = calculate_claude_cost(
                model_id="claude-haiku-test",
                input_tokens=2000,  # Transcript
                output_tokens=500,  # Summary
            )

        total = whisper_cost + claude_cost
        assert isinstance(total, Decimal)
        assert total > Decimal("0")

    def test_tool_usage_cost_calculation(self, mock_model_registry):
        """Test cost calculation for tool usage scenario."""
        # Web search
        search_cost = calculate_web_search_cost(2)  # $0.02

        # Code execution
        e2b_cost = calculate_e2b_cost(30)  # $0.0015

        # Image generation
        image_cost = calculate_gemini_image_cost("2048x2048")  # $0.134

        with patch.dict("config.MODEL_REGISTRY",
                        mock_model_registry,
                        clear=True):
            # Claude orchestration
            claude_cost = calculate_claude_cost(
                model_id="claude-sonnet-test",
                input_tokens=10000,
                output_tokens=2000,
            )

        total = search_cost + e2b_cost + image_cost + claude_cost
        assert isinstance(total, Decimal)
        # Should be reasonable total
        assert Decimal("0.1") < total < Decimal("1.0")
