"""Tests for Redis client module.

Tests connection handling and circuit breaker pattern.
"""

import time
from unittest.mock import AsyncMock
from unittest.mock import patch

from cache.client import _is_circuit_open
from cache.client import _record_failure
from cache.client import _record_success
from cache.client import CIRCUIT_FAILURE_THRESHOLD
from cache.client import CIRCUIT_RESET_TIMEOUT
from cache.client import get_circuit_breaker_state
from cache.client import get_redis
from cache.client import reset_circuit_breaker
import pytest


class TestCircuitBreaker:
    """Tests for circuit breaker functionality."""

    def setup_method(self):
        """Reset circuit breaker before each test."""
        reset_circuit_breaker()

    def test_initial_state_closed(self):
        """Test circuit breaker starts closed."""
        state = get_circuit_breaker_state()
        assert state["is_open"] is False
        assert state["failure_count"] == 0

    def test_opens_after_threshold_failures(self):
        """Test circuit opens after threshold consecutive failures."""
        # Record failures up to threshold
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            _record_failure()

        state = get_circuit_breaker_state()
        assert state["is_open"] is True
        assert state["failure_count"] == CIRCUIT_FAILURE_THRESHOLD

    def test_closes_on_success(self):
        """Test circuit closes on successful operation."""
        # Open the circuit
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            _record_failure()

        assert _is_circuit_open() is True

        # Record success
        _record_success()

        state = get_circuit_breaker_state()
        assert state["is_open"] is False
        assert state["failure_count"] == 0

    def test_reset_clears_state(self):
        """Test reset_circuit_breaker clears all state."""
        # Open the circuit
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            _record_failure()

        reset_circuit_breaker()

        state = get_circuit_breaker_state()
        assert state["is_open"] is False
        assert state["failure_count"] == 0

    def test_half_open_after_timeout(self):
        """Test circuit becomes half-open after timeout."""
        # Open the circuit
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            _record_failure()

        # Get the current open_until timestamp
        state = get_circuit_breaker_state()
        open_until = state["open_until"]

        # Mock time to be after timeout
        future_time = open_until + 1
        with patch("cache.client.time") as mock_time_module:
            mock_time_module.time.return_value = future_time

            # Circuit should be half-open (is_open returns False)
            assert _is_circuit_open() is False

    @pytest.mark.asyncio
    async def test_get_redis_skips_when_circuit_open(self):
        """Test get_redis returns None immediately when circuit is open."""
        # Open the circuit
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            _record_failure()

        # get_redis should return None without trying ping
        result = await get_redis()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_redis_records_failure_on_connection_error(self):
        """Test get_redis records failure when connection fails."""
        reset_circuit_breaker()

        mock_client = AsyncMock()
        mock_client.ping.side_effect = Exception("Connection refused")

        with patch("cache.client._redis_client", mock_client):
            result = await get_redis()

        assert result is None
        state = get_circuit_breaker_state()
        assert state["failure_count"] == 1

    @pytest.mark.asyncio
    async def test_get_redis_records_success_on_ping(self):
        """Test get_redis records success when ping succeeds."""
        reset_circuit_breaker()

        # First record some failures
        _record_failure()
        _record_failure()

        mock_client = AsyncMock()
        mock_client.ping.return_value = True

        with patch("cache.client._redis_client", mock_client):
            result = await get_redis()

        assert result is mock_client
        state = get_circuit_breaker_state()
        assert state["failure_count"] == 0


class TestCircuitBreakerState:
    """Tests for get_circuit_breaker_state function."""

    def setup_method(self):
        """Reset circuit breaker before each test."""
        reset_circuit_breaker()

    def test_returns_correct_structure(self):
        """Test state dict has expected keys."""
        state = get_circuit_breaker_state()

        assert "is_open" in state
        assert "failure_count" in state
        assert "open_until" in state
        assert "seconds_until_retry" in state

    def test_seconds_until_retry_when_closed(self):
        """Test seconds_until_retry is 0 when circuit closed."""
        state = get_circuit_breaker_state()
        assert state["seconds_until_retry"] == 0

    def test_seconds_until_retry_when_open(self):
        """Test seconds_until_retry shows remaining time."""
        # Open the circuit
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            _record_failure()

        state = get_circuit_breaker_state()
        assert state["seconds_until_retry"] > 0
        assert state["seconds_until_retry"] <= CIRCUIT_RESET_TIMEOUT
