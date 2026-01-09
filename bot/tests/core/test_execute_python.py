"""Tests for execute_python tool (Phase 1.5 Stage 5).

Tests Python code execution tool functionality, including:
- Successful code execution
- Package installation
- Error handling
- Timeout configuration
- Stdout/stderr capture
"""

from unittest.mock import Mock
from unittest.mock import patch

# Import the module to test
from core.tools.execute_python import execute_python
from core.tools.execute_python import EXECUTE_PYTHON_TOOL
import pytest


@pytest.fixture(autouse=True)
def reset_api_key():
    """Reset global API key before and after each test."""
    # Reset before test
    import core.tools.execute_python  # pylint: disable=import-outside-toplevel
    core.tools.execute_python._e2b_api_key = None
    yield
    # Reset after test
    core.tools.execute_python._e2b_api_key = None


class TestExecutePython:
    """Tests for execute_python() function."""

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_success(self, mock_get_api_key,
                                          mock_sandbox_class):
        """Test successful code execution."""
        # Setup mock API key
        mock_get_api_key.return_value = "test_api_key"

        # Setup mock sandbox with context manager support
        mock_sandbox = Mock()

        # E2B v1.0+ API: execution.logs.stdout/stderr
        mock_logs = Mock()
        mock_logs.stdout = ["Hello, world!\n"]
        mock_logs.stderr = []

        mock_execution = Mock()
        mock_execution.error = None
        mock_execution.results = []
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Test
        result = await execute_python(code="print('Hello, world!')")

        # Verify
        assert result["success"] == "true"
        assert result["error"] == ""
        assert "stdout" in result
        assert "stderr" in result
        assert "Hello, world!" in result["stdout"]

        # Verify sandbox was created and context manager was used
        mock_sandbox_class.create.assert_called_once()
        mock_sandbox.__enter__.assert_called_once()
        mock_sandbox.__exit__.assert_called_once()

        # Verify run_code was called
        mock_sandbox.run_code.assert_called_once()
        call_kwargs = mock_sandbox.run_code.call_args[1]
        assert call_kwargs["code"] == "print('Hello, world!')"
        assert call_kwargs["timeout"] == 180.0

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_with_requirements(self, mock_get_api_key,
                                                    mock_sandbox_class):
        """Test code execution with pip package installation."""
        # Setup mock API key
        mock_get_api_key.return_value = "test_api_key"

        # Setup mock sandbox with context manager support
        mock_sandbox = Mock()
        mock_install_result = Mock()
        mock_install_result.exit_code = 0
        mock_install_result.stdout = "Successfully installed numpy"
        mock_sandbox.commands.run.return_value = mock_install_result

        # E2B v1.0+ API
        mock_logs = Mock()
        mock_logs.stdout = ["1.24.0\n"]
        mock_logs.stderr = []

        mock_execution = Mock()
        mock_execution.error = None
        mock_execution.results = []
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Test
        result = await execute_python(
            code="import numpy; print(numpy.__version__)", requirements="numpy")

        # Verify
        assert result["success"] == "true"

        # Verify pip install was called
        mock_sandbox.commands.run.assert_called_once_with("pip install numpy")

        # Verify context manager was used
        mock_sandbox.__enter__.assert_called_once()
        mock_sandbox.__exit__.assert_called_once()

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_with_error(self, mock_get_api_key,
                                             mock_sandbox_class):
        """Test code execution with Python error."""
        # Setup mock API key
        mock_get_api_key.return_value = "test_api_key"

        # Setup mock sandbox with context manager support
        mock_sandbox = Mock()

        # E2B v1.0+ API
        mock_logs = Mock()
        mock_logs.stdout = []
        mock_logs.stderr = []

        mock_execution = Mock()
        mock_execution.error = Exception(
            "NameError: name 'undefined_var' is not defined")
        mock_execution.results = []
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Test
        result = await execute_python(code="print(undefined_var)")

        # Verify
        assert result["success"] == "false"
        assert "NameError" in result["error"]

        # Verify context manager was used even after error
        mock_sandbox.__enter__.assert_called_once()
        mock_sandbox.__exit__.assert_called_once()

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_with_stdout_stderr(self, mock_get_api_key,
                                                     mock_sandbox_class):
        """Test capturing stdout and stderr."""
        # Setup mock API key
        mock_get_api_key.return_value = "test_api_key"

        # Setup mock sandbox with context manager support
        mock_sandbox = Mock()

        # E2B v1.0+ API: execution.logs contains stdout/stderr lists
        mock_logs = Mock()
        mock_logs.stdout = ["Hello from stdout\n"]
        mock_logs.stderr = ["Warning from stderr\n"]

        mock_execution = Mock()
        mock_execution.error = None
        mock_execution.results = []
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Test
        result = await execute_python(code="print('test')")

        # Verify
        assert "Hello from stdout" in result["stdout"]
        assert "Warning from stderr" in result["stderr"]
        assert result["success"] == "true"

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_with_custom_timeout(self, mock_get_api_key,
                                                      mock_sandbox_class):
        """Test code execution with custom timeout."""
        # Setup mock API key
        mock_get_api_key.return_value = "test_api_key"

        # Setup mock sandbox with context manager support
        mock_sandbox = Mock()

        # E2B v1.0+ API
        mock_logs = Mock()
        mock_logs.stdout = []
        mock_logs.stderr = []

        mock_execution = Mock()
        mock_execution.error = None
        mock_execution.results = []
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Test
        result = await execute_python(code="import time; time.sleep(1)",
                                      timeout=60.0)

        # Verify
        assert result["success"] == "true"

        # Verify timeout was passed
        call_kwargs = mock_sandbox.run_code.call_args[1]
        assert call_kwargs["timeout"] == 60.0

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_sandbox_exception(self, mock_get_api_key,
                                                    mock_sandbox_class):
        """Test handling of sandbox creation failure."""
        # Setup mock API key
        mock_get_api_key.return_value = "test_api_key"

        # Setup mock to raise exception on create()
        mock_sandbox_class.create.side_effect = Exception(
            "Sandbox creation failed")

        # Test
        with pytest.raises(Exception, match="Sandbox creation failed"):
            await execute_python(code="print('test')")

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_with_results(self, mock_get_api_key,
                                               mock_sandbox_class):
        """Test code execution with matplotlib-like results."""
        # Setup mock API key
        mock_get_api_key.return_value = "test_api_key"

        # Setup mock sandbox with context manager support
        mock_sandbox = Mock()

        # E2B v1.0+ API
        mock_logs = Mock()
        mock_logs.stdout = []
        mock_logs.stderr = []

        mock_result_obj = Mock()
        mock_result_obj.__str__ = lambda self: "<matplotlib plot>"

        mock_execution = Mock()
        mock_execution.error = None
        mock_execution.results = [mock_result_obj]
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Test
        result = await execute_python(
            code="import matplotlib.pyplot as plt; plt.plot([1,2,3])")

        # Verify
        assert result["success"] == "true"
        assert result["results"] != "[]"  # Should contain serialized results
        assert "<matplotlib plot>" in result["results"]


class TestExecutePythonToolDefinition:
    """Tests for EXECUTE_PYTHON_TOOL definition."""

    def test_tool_definition_structure(self):
        """Test that EXECUTE_PYTHON_TOOL has correct structure."""
        tool = EXECUTE_PYTHON_TOOL

        # Check basic structure
        assert tool["name"] == "execute_python"
        assert "description" in tool
        assert "input_schema" in tool

        # Check input schema
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema

        # Check required parameters
        assert "code" in schema["required"]
        assert "requirements" not in schema["required"]  # Optional
        assert "timeout" not in schema["required"]  # Optional

        # Check properties
        properties = schema["properties"]
        assert "code" in properties
        assert "requirements" in properties
        assert "timeout" in properties

        # Check property types
        assert properties["code"]["type"] == "string"
        assert properties["requirements"]["type"] == "string"
        assert properties["timeout"]["type"] == "number"

    def test_tool_description_content(self):
        """Test that tool description contains key information."""
        description = EXECUTE_PYTHON_TOOL["description"]

        # Should mention key features
        assert "python" in description.lower() or "code" in description.lower()
        assert "sandbox" in description.lower()

        # Should mention when to use (case insensitive)
        assert "when to use" in description.lower()
        assert "when not to use" in description.lower()

        # Should mention limitations
        assert "limitations" in description.lower(
        ) or "timeout" in description.lower()

    def test_tool_description_mentions_features(self):
        """Test that description includes key features."""
        description = EXECUTE_PYTHON_TOOL["description"]

        # Should mention important capabilities
        assert any(keyword in description.lower()
                   for keyword in ["internet", "pip", "package", "install"])
