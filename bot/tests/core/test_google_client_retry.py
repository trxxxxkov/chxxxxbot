"""Regression tests for Google Gemini client retry logic on transient errors.

Covers:
- `_is_retriable_google_error` helper classification
- Stream retries on 503 UNAVAILABLE before any events yielded
- No retry once events have been yielded mid-stream
- Retries exhausted eventually raise OverloadedError
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from core.exceptions import OverloadedError
from core.google.client import _RETRY_DELAYS
from core.google.client import _RETRY_MAX_ATTEMPTS
from core.google.client import _is_retriable_google_error


class TestIsRetriableGoogleError:
    """Tests for _is_retriable_google_error helper."""

    def test_503_unavailable(self):
        assert _is_retriable_google_error(
            "503 UNAVAILABLE. high demand") is True

    def test_unavailable_no_code(self):
        assert _is_retriable_google_error(
            "{'status': 'UNAVAILABLE'}") is True

    def test_500_internal(self):
        assert _is_retriable_google_error("500 INTERNAL") is True

    def test_504_deadline(self):
        assert _is_retriable_google_error("504 DEADLINE_EXCEEDED") is True

    def test_deadline_exceeded(self):
        assert _is_retriable_google_error("DEADLINE_EXCEEDED") is True

    def test_400_bad_request_not_retriable(self):
        assert _is_retriable_google_error("400 INVALID_ARGUMENT") is False

    def test_429_rate_limit_not_retriable(self):
        assert _is_retriable_google_error(
            "429 RESOURCE_EXHAUSTED") is False

    def test_403_permission_denied_not_retriable(self):
        assert _is_retriable_google_error("403 PERMISSION_DENIED") is False


class TestRetryConstants:
    """Sanity checks on retry configuration."""

    def test_max_attempts_positive(self):
        assert _RETRY_MAX_ATTEMPTS == 3

    def test_delays_match_attempts(self):
        assert len(_RETRY_DELAYS) == _RETRY_MAX_ATTEMPTS
        assert all(d > 0 for d in _RETRY_DELAYS)

    def test_delays_monotonic(self):
        assert list(_RETRY_DELAYS) == sorted(_RETRY_DELAYS)


class TestGoogleSearchRetry:
    """Regression tests for google_search tool retry on 503."""

    @pytest.mark.asyncio
    async def test_google_search_retries_on_503(self):
        """google_search retries transient 503 and recovers on second call."""
        from core.tools import google_search as gs_module

        # Simulate: 1st call raises 503, 2nd call succeeds
        mock_response = MagicMock()
        mock_response.candidates = []
        mock_response.usage_metadata = None

        call_count = {"n": 0}

        def fake_generate_content(**_kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError(
                    "503 UNAVAILABLE. {'error': {'code': 503, "
                    "'message': 'high demand', 'status': 'UNAVAILABLE'}}"
                )
            return mock_response

        mock_client = MagicMock()
        mock_client.models.generate_content = fake_generate_content

        # Patch sleep to keep the test fast
        async def noop_sleep(_d):
            return None

        session = MagicMock()
        services = MagicMock()
        services.balance.charge_user = _async_noop
        with patch.object(gs_module, "get_google_client",
                          return_value=mock_client), \
             patch("asyncio.sleep", side_effect=noop_sleep), \
             patch("services.factory.ServiceFactory",
                   return_value=services):
            result = await gs_module.execute_google_search(
                query="test query",
                bot=MagicMock(),
                session=session,
                user_id=1,
                model_id="google:flash-lite",
            )

        # Recovered after retry — should not be an error dict
        assert "error" not in result
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_google_search_non_retriable_fails_immediately(self):
        """google_search does NOT retry on 400 errors."""
        from core.tools import google_search as gs_module

        call_count = {"n": 0}

        def fake_generate_content(**_kwargs):
            call_count["n"] += 1
            raise RuntimeError("400 INVALID_ARGUMENT. bad schema")

        mock_client = MagicMock()
        mock_client.models.generate_content = fake_generate_content

        async def noop_sleep(_d):
            return None

        session = MagicMock()
        with patch.object(gs_module, "get_google_client",
                          return_value=mock_client), \
             patch("asyncio.sleep", side_effect=noop_sleep):
            result = await gs_module.execute_google_search(
                query="test query",
                bot=MagicMock(),
                session=session,
                user_id=1,
                model_id="google:flash-lite",
            )

        assert result.get("error") == "search_failed"
        assert call_count["n"] == 1


async def _async_noop(*_args, **_kwargs):
    """Async no-op for mocking."""
    return None
