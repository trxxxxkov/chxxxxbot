"""Tests for async execution in tools.

These tests verify that tools use asyncio.to_thread() for blocking calls,
which is required for keepalive to work during long operations.
"""

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


class TestGenerateImageAsync:
    """Tests for generate_image async execution."""

    @pytest.mark.asyncio
    async def test_generate_image_uses_to_thread(self):
        """generate_image should use asyncio.to_thread for API call."""
        with patch('core.tools.generate_image.get_google_client') as mock_client, \
             patch('core.tools.generate_image.asyncio.to_thread',
                   new_callable=AsyncMock) as mock_to_thread:

            # Set up mock response with image data
            mock_image = MagicMock()
            mock_image._pil_image = MagicMock()
            mock_image.data = b"fake_image_data"
            mock_response = MagicMock()
            mock_response.candidates = [
                MagicMock(content=MagicMock(
                    parts=[MagicMock(inline_data=MagicMock(data=b"fake"))]))
            ]
            mock_to_thread.return_value = mock_response

            from core.tools.generate_image import generate_image

            mock_bot = MagicMock()
            mock_session = MagicMock()

            try:
                await generate_image(prompt="test image",
                                     bot=mock_bot,
                                     session=mock_session)
            except Exception:
                pass  # May fail due to incomplete mocking

            # Verify to_thread was called
            mock_to_thread.assert_called_once()


class TestAnalyzeImageAsync:
    """Tests for analyze_image async execution."""

    @pytest.mark.asyncio
    async def test_analyze_image_uses_to_thread(self):
        """analyze_image should use asyncio.to_thread for API call."""
        with patch('core.tools.analyze_image.get_anthropic_client') as mock_client, \
             patch('core.tools.analyze_image.asyncio.to_thread',
                   new_callable=AsyncMock) as mock_to_thread:

            # Set up mock response
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="analysis")]
            mock_response.usage = MagicMock(input_tokens=100, output_tokens=50)
            mock_to_thread.return_value = mock_response

            from core.tools.analyze_image import analyze_image

            result = await analyze_image(claude_file_id="file_123",
                                         question="What is in this image?")

            # Verify to_thread was called
            mock_to_thread.assert_called_once()
            assert "analysis" in result.get("analysis", "")


class TestAnalyzePdfAsync:
    """Tests for analyze_pdf async execution."""

    @pytest.mark.asyncio
    async def test_analyze_pdf_uses_to_thread(self):
        """analyze_pdf should use asyncio.to_thread for API call."""
        with patch('core.tools.analyze_pdf.get_anthropic_client') as mock_client, \
             patch('core.tools.analyze_pdf.asyncio.to_thread',
                   new_callable=AsyncMock) as mock_to_thread:

            # Set up mock response
            mock_response = MagicMock()
            mock_response.content = [MagicMock(text="pdf analysis")]
            mock_response.usage = MagicMock(input_tokens=100,
                                            output_tokens=50,
                                            cache_creation_input_tokens=0,
                                            cache_read_input_tokens=0)
            mock_to_thread.return_value = mock_response

            from core.tools.analyze_pdf import analyze_pdf

            result = await analyze_pdf(claude_file_id="file_123",
                                       question="Summarize this document")

            # Verify to_thread was called
            mock_to_thread.assert_called_once()
            assert "pdf analysis" in result.get("analysis", "")


class TestExecutePythonAsync:
    """Tests for execute_python async execution."""

    @pytest.mark.asyncio
    async def test_execute_python_uses_to_thread(self):
        """execute_python should use asyncio.to_thread for sandbox."""
        with patch('core.tools.execute_python._run_sandbox_sync') as mock_sandbox, \
             patch('core.tools.execute_python.asyncio.to_thread',
                   new_callable=AsyncMock) as mock_to_thread:

            # Set up mock response
            mock_result = {
                "stdout": "Hello",
                "stderr": "",
                "results": "[]",
                "error": "",
                "success": "true",
                "generated_files": "[]",
                "_file_contents": [],
            }
            # Return tuple: (result, sandbox_duration, sandbox_id)
            mock_to_thread.return_value = (mock_result, 1.0, "sandbox_123")

            from core.tools.execute_python import execute_python

            mock_bot = MagicMock()
            mock_session = MagicMock()

            result = await execute_python(code="print('Hello')",
                                          bot=mock_bot,
                                          session=mock_session)

            # Verify to_thread was called with _run_sandbox_sync
            mock_to_thread.assert_called_once()
            args = mock_to_thread.call_args[0]
            from core.tools.execute_python import _run_sandbox_sync
            assert args[0] == _run_sandbox_sync


class TestKeepaliveCompatibility:
    """Tests to verify keepalive can work during tool execution."""

    @pytest.mark.asyncio
    async def test_event_loop_not_blocked(self):
        """Verify that a long-running tool doesn't block the event loop."""
        # This test simulates what happens during tool execution

        keepalive_called = False
        tool_completed = False

        async def mock_keepalive():
            nonlocal keepalive_called
            await asyncio.sleep(0.1)
            keepalive_called = True

        async def mock_tool_with_to_thread():
            nonlocal tool_completed
            # Simulate blocking call in thread
            await asyncio.to_thread(lambda: None)
            tool_completed = True

        # Run both concurrently
        async def run_with_keepalive():
            keepalive_task = asyncio.create_task(mock_keepalive())
            tool_task = asyncio.create_task(mock_tool_with_to_thread())

            await asyncio.gather(keepalive_task, tool_task)

        await asyncio.wait_for(run_with_keepalive(), timeout=2.0)

        # Both should have completed
        assert keepalive_called
        assert tool_completed


class TestRunSandboxSync:
    """Tests for _run_sandbox_sync function."""

    def test_run_sandbox_sync_is_synchronous(self):
        """_run_sandbox_sync should be a regular (non-async) function."""
        import inspect

        from core.tools.execute_python import _run_sandbox_sync

        # Should not be a coroutine function
        assert not inspect.iscoroutinefunction(_run_sandbox_sync)

    def test_run_sandbox_sync_signature(self):
        """_run_sandbox_sync should have correct signature."""
        import inspect

        from core.tools.execute_python import _run_sandbox_sync

        sig = inspect.signature(_run_sandbox_sync)
        params = list(sig.parameters.keys())

        assert "code" in params
        assert "downloaded_files" in params
        assert "requirements" in params
        assert "timeout" in params
