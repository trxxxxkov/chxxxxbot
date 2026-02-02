"""Tests for tool cost estimation.

Tests the is_paid_tool() and estimate_tool_cost() functions used for
balance pre-checks before executing expensive tools.
"""

from decimal import Decimal

from core.tools.cost_estimator import estimate_tool_cost
from core.tools.cost_estimator import is_paid_tool
from core.tools.cost_estimator import PAID_TOOLS
import pytest


class TestIsPaidTool:
    """Tests for is_paid_tool() function."""

    def test_paid_tools_in_set(self):
        """All paid tools are in PAID_TOOLS set."""
        assert "generate_image" in PAID_TOOLS
        assert "transcribe_audio" in PAID_TOOLS
        assert "web_search" in PAID_TOOLS
        assert "execute_python" in PAID_TOOLS
        assert "analyze_image" in PAID_TOOLS
        assert "analyze_pdf" in PAID_TOOLS
        assert "preview_file" in PAID_TOOLS

    def test_free_tools_not_in_set(self):
        """Free tools are not in PAID_TOOLS set."""
        assert "render_latex" not in PAID_TOOLS
        assert "web_fetch" not in PAID_TOOLS
        assert "deliver_file" not in PAID_TOOLS

    def test_is_paid_tool_returns_true_for_paid(self):
        """is_paid_tool returns True for paid tools."""
        assert is_paid_tool("generate_image") is True
        assert is_paid_tool("transcribe_audio") is True
        assert is_paid_tool("web_search") is True
        assert is_paid_tool("execute_python") is True
        assert is_paid_tool("analyze_image") is True
        assert is_paid_tool("analyze_pdf") is True
        assert is_paid_tool("preview_file") is True

    def test_is_paid_tool_returns_false_for_free(self):
        """is_paid_tool returns False for free tools."""
        assert is_paid_tool("render_latex") is False
        assert is_paid_tool("web_fetch") is False
        assert is_paid_tool("deliver_file") is False

    def test_is_paid_tool_returns_false_for_unknown(self):
        """is_paid_tool returns False for unknown tools."""
        assert is_paid_tool("unknown_tool") is False
        assert is_paid_tool("") is False
        assert is_paid_tool("some_random_tool") is False


class TestEstimateToolCost:
    """Tests for estimate_tool_cost() function."""

    def test_generate_image_default_resolution(self):
        """generate_image with default resolution costs $0.134."""
        cost = estimate_tool_cost("generate_image", {})
        assert cost == Decimal("0.134")

    def test_generate_image_1k_resolution(self):
        """generate_image with 1k resolution costs $0.134."""
        cost = estimate_tool_cost("generate_image", {"resolution": "1k"})
        assert cost == Decimal("0.134")

    def test_generate_image_2k_resolution(self):
        """generate_image with 2k resolution costs $0.134."""
        cost = estimate_tool_cost("generate_image", {"resolution": "2k"})
        assert cost == Decimal("0.134")

    def test_generate_image_4k_resolution(self):
        """generate_image with 4k resolution costs $0.240."""
        cost = estimate_tool_cost("generate_image", {"resolution": "4k"})
        assert cost == Decimal("0.240")

    def test_transcribe_audio_with_duration(self):
        """transcribe_audio cost based on duration."""
        # 60 seconds = 1 minute = $0.006
        cost = estimate_tool_cost("transcribe_audio", {},
                                  audio_duration_seconds=60)
        assert cost == Decimal("0.006")

        # 120 seconds = 2 minutes = $0.012
        cost = estimate_tool_cost("transcribe_audio", {},
                                  audio_duration_seconds=120)
        assert cost == Decimal("0.012")

        # 30 seconds = 0.5 minutes = $0.003
        cost = estimate_tool_cost("transcribe_audio", {},
                                  audio_duration_seconds=30)
        assert cost == Decimal("0.003")

    def test_transcribe_audio_without_duration(self):
        """transcribe_audio without duration estimates 5 minutes ($0.03)."""
        cost = estimate_tool_cost("transcribe_audio", {})
        assert cost == Decimal("0.03")

    def test_web_search_fixed_cost(self):
        """web_search has fixed cost of $0.01."""
        cost = estimate_tool_cost("web_search", {})
        assert cost == Decimal("0.01")

        # Input doesn't affect cost
        cost = estimate_tool_cost("web_search", {"query": "test query"})
        assert cost == Decimal("0.01")

    def test_execute_python_default_timeout(self):
        """execute_python with default timeout (3600s) costs ~$0.13."""
        cost = estimate_tool_cost("execute_python", {})
        expected = Decimal("3600") * Decimal("0.000036")
        assert cost == expected
        assert cost == Decimal("0.1296")

    def test_execute_python_custom_timeout(self):
        """execute_python cost based on timeout parameter."""
        # 60 seconds = $0.00216
        cost = estimate_tool_cost("execute_python", {"timeout": 60})
        expected = Decimal("60") * Decimal("0.000036")
        assert cost == expected

        # 300 seconds = $0.0108
        cost = estimate_tool_cost("execute_python", {"timeout": 300})
        expected = Decimal("300") * Decimal("0.000036")
        assert cost == expected

    def test_free_tools_return_none(self):
        """Free tools return None (no cost estimate)."""
        assert estimate_tool_cost("render_latex", {}) is None
        assert estimate_tool_cost("web_fetch", {}) is None
        assert estimate_tool_cost("deliver_file", {}) is None

    def test_claude_api_tools_return_none(self):
        """Claude API tools return None (cost calculated after call)."""
        # analyze_image, analyze_pdf, preview_file (for images/PDF) are paid
        # but cost depends on response tokens, so can't be estimated upfront
        assert estimate_tool_cost("analyze_image", {}) is None
        assert estimate_tool_cost("analyze_pdf", {}) is None
        assert estimate_tool_cost("preview_file", {}) is None

    def test_unknown_tools_return_none(self):
        """Unknown tools return None (no cost)."""
        assert estimate_tool_cost("unknown_tool", {}) is None
        assert estimate_tool_cost("some_random_tool", {}) is None


class TestPaidToolsCount:
    """Test that PAID_TOOLS set has expected count."""

    def test_paid_tools_count(self):
        """Exactly 8 paid tools in the set."""
        assert len(PAID_TOOLS) == 8
