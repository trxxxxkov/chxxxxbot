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


@pytest.fixture
def mock_bot():
    """Mock Telegram Bot for tests."""
    return Mock()


@pytest.fixture
def mock_session():
    """Mock database session for tests."""
    return Mock()


class TestExecutePython:
    """Tests for execute_python() function."""

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_success(self, mock_get_api_key,
                                          mock_sandbox_class, mock_bot,
                                          mock_session):
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
        # Mock files.list() to return empty list (no output files)
        mock_sandbox.files.list.return_value = []
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Test
        result = await execute_python(code="print('Hello, world!')",
                                      bot=mock_bot,
                                      session=mock_session)

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
        assert call_kwargs["timeout"] == 3600.0

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_with_requirements(self, mock_get_api_key,
                                                    mock_sandbox_class,
                                                    mock_bot, mock_session):
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
            code="import numpy; print(numpy.__version__)",
            bot=mock_bot,
            session=mock_session,
            requirements="numpy")

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
                                             mock_sandbox_class, mock_bot,
                                             mock_session):
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
        result = await execute_python(code="print(undefined_var)",
                                      bot=mock_bot,
                                      session=mock_session)

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
                                                     mock_sandbox_class,
                                                     mock_bot, mock_session):
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
        result = await execute_python(code="print('test')",
                                      bot=mock_bot,
                                      session=mock_session)

        # Verify
        assert "Hello from stdout" in result["stdout"]
        assert "Warning from stderr" in result["stderr"]
        assert result["success"] == "true"

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_with_custom_timeout(self, mock_get_api_key,
                                                      mock_sandbox_class,
                                                      mock_bot, mock_session):
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
                                      bot=mock_bot,
                                      session=mock_session,
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
                                                    mock_sandbox_class,
                                                    mock_bot, mock_session):
        """Test handling of sandbox creation failure."""
        # Setup mock API key
        mock_get_api_key.return_value = "test_api_key"

        # Setup mock to raise exception on create()
        mock_sandbox_class.create.side_effect = Exception(
            "Sandbox creation failed")

        # Test
        with pytest.raises(Exception, match="Sandbox creation failed"):
            await execute_python(code="print('test')",
                                 bot=mock_bot,
                                 session=mock_session)

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_execute_python_with_results(self, mock_get_api_key,
                                               mock_sandbox_class, mock_bot,
                                               mock_session):
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
            code="import matplotlib.pyplot as plt; plt.plot([1,2,3])",
            bot=mock_bot,
            session=mock_session)

        # Verify
        assert result["success"] == "true"
        assert result["results"] != "[]"  # Should contain serialized results
        assert "<matplotlib plot>" in result["results"]


class TestExecutePythonValidation:
    """Tests for execute_python validation."""

    @pytest.mark.asyncio
    async def test_missing_file_inputs_with_tmp_inputs_path(
            self, mock_bot, mock_session):
        """Test that missing file_inputs returns clear error.

        Regression test: When code references /tmp/inputs/ but file_inputs
        is empty, should return a helpful error message instead of
        FileNotFoundError from sandbox.
        """
        code = """
import json
with open('/tmp/inputs/data.csv', 'r') as f:
    print(f.read())
"""
        result = await execute_python(code=code,
                                      bot=mock_bot,
                                      session=mock_session,
                                      file_inputs=None)

        # Verify early validation caught the issue
        assert result["success"] == "false"
        assert "file_inputs" in result["error"]
        assert "/tmp/inputs/" in result["error"]
        # Should not cost anything (no sandbox created)
        assert result["cost_usd"] == "0.000000"

    @pytest.mark.asyncio
    async def test_missing_file_inputs_empty_list(self, mock_bot, mock_session):
        """Test validation with empty file_inputs list."""
        code = "open('/tmp/inputs/file.txt', 'r')"
        result = await execute_python(code=code,
                                      bot=mock_bot,
                                      session=mock_session,
                                      file_inputs=[])

        assert result["success"] == "false"
        assert "file_inputs" in result["error"]

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_no_validation_without_tmp_inputs(self, mock_get_api_key,
                                                    mock_sandbox_class,
                                                    mock_bot, mock_session):
        """Test that code without /tmp/inputs/ doesn't trigger validation."""
        mock_get_api_key.return_value = "test_api_key"

        mock_sandbox = Mock()
        mock_logs = Mock()
        mock_logs.stdout = ["OK\n"]
        mock_logs.stderr = []

        mock_execution = Mock()
        mock_execution.error = None
        mock_execution.results = []
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution
        mock_sandbox.files.list.return_value = []
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Code without /tmp/inputs/ should execute normally
        result = await execute_python(code="print('OK')",
                                      bot=mock_bot,
                                      session=mock_session,
                                      file_inputs=None)

        assert result["success"] == "true"
        mock_sandbox.run_code.assert_called_once()


class TestExecutePythonOutputFiles:
    """Tests for output_files handling (Phase 3.2+).

    Files are cached in Redis and metadata returned to Claude.
    Tests verify:
    - output_files is empty list when no files generated
    - output_files contains metadata when files are cached
    """

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_output_files_empty_when_no_files(self, mock_get_api_key,
                                                    mock_sandbox_class,
                                                    mock_bot, mock_session):
        """output_files should be empty list when no files generated."""
        mock_get_api_key.return_value = "test_api_key"

        mock_sandbox = Mock()
        mock_logs = Mock()
        mock_logs.stdout = ["Hello\n"]
        mock_logs.stderr = []

        mock_execution = Mock()
        mock_execution.error = None
        mock_execution.results = []
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution
        # No output files
        mock_sandbox.files.list.return_value = []
        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        result = await execute_python(code="print('Hello')",
                                      bot=mock_bot,
                                      session=mock_session)

        # output_files should be empty list when no files
        assert "output_files" in result
        assert result["output_files"] == []

    @pytest.mark.asyncio
    @patch('core.tools.execute_python.store_exec_file')
    @patch('core.tools.execute_python.Sandbox')
    @patch('core.tools.execute_python.get_e2b_api_key')
    async def test_output_files_contains_metadata_when_cached(
            self, mock_get_api_key, mock_sandbox_class, mock_store_exec_file,
            mock_bot, mock_session):
        """output_files should contain metadata when files are cached."""
        mock_get_api_key.return_value = "test_api_key"

        mock_sandbox = Mock()
        mock_logs = Mock()
        mock_logs.stdout = ["Saved to /tmp/output.txt\n"]
        mock_logs.stderr = []

        mock_execution = Mock()
        mock_execution.error = None
        mock_execution.results = []
        mock_execution.logs = mock_logs

        mock_sandbox.run_code.return_value = mock_execution

        # Simulate output file
        mock_file_entry = Mock()
        mock_file_entry.name = "output.txt"
        mock_file_entry.path = "/tmp/output.txt"
        mock_sandbox.files.list.return_value = [mock_file_entry]
        mock_sandbox.files.read.return_value = b"Hello, World!"

        mock_sandbox.__enter__ = Mock(return_value=mock_sandbox)
        mock_sandbox.__exit__ = Mock(return_value=None)
        mock_sandbox_class.create.return_value = mock_sandbox

        # Mock Redis cache response
        mock_store_exec_file.return_value = {
            "temp_id": "exec_abc12345_output.txt",
            "filename": "output.txt",
            "size_bytes": 13,
            "mime_type": "text/plain",
            "preview": "Text file, 1 lines, 13 chars: \"Hello, World!\"",
        }

        result = await execute_python(
            code="with open('/tmp/output.txt', 'w') as f: f.write('Hello')",
            bot=mock_bot,
            session=mock_session)

        # output_files should contain cached file metadata
        assert "output_files" in result
        assert len(result["output_files"]) == 1
        assert result["output_files"][0]["filename"] == "output.txt"
        assert result["output_files"][0][
            "temp_id"] == "exec_abc12345_output.txt"
        assert result["output_files"][0]["preview"] is not None

        # Verify store_exec_file was called correctly
        mock_store_exec_file.assert_called_once()
        call_kwargs = mock_store_exec_file.call_args[1]
        assert call_kwargs["filename"] == "output.txt"
        assert call_kwargs["content"] == b"Hello, World!"
        assert call_kwargs["mime_type"] == "text/plain"


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

        # Should mention when to use (XML format)
        assert "<when_to_use>" in description
        assert "<when_not_to_use>" in description

        # Should mention limitations (XML format)
        assert "<limitations>" in description or "timeout" in description.lower(
        )

    def test_tool_description_mentions_features(self):
        """Test that description includes key features."""
        description = EXECUTE_PYTHON_TOOL["description"]

        # Should mention important capabilities
        assert any(keyword in description.lower()
                   for keyword in ["internet", "pip", "package", "install"])
