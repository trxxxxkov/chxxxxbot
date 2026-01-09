"""Execute Python code tool using E2B Code Interpreter.

This module implements the execute_python tool for running AI-generated
Python code in secure sandboxed environments with internet access and
pip package installation support.

NO __init__.py - use direct import:
    from core.tools.execute_python import execute_python, EXECUTE_PYTHON_TOOL
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from e2b_code_interpreter import Sandbox
from utils.structured_logging import get_logger

logger = get_logger(__name__)


def read_secret(secret_name: str) -> str:
    """Read secret from Docker secrets.

    Args:
        secret_name: Name of the secret file.

    Returns:
        Secret value as string.
    """
    secret_path = Path(f"/run/secrets/{secret_name}")
    return secret_path.read_text(encoding="utf-8").strip()


# Global E2B API key (read once)
_e2b_api_key: str | None = None


def get_e2b_api_key() -> str:
    """Get E2B API key from secrets.

    Returns:
        E2B API key string.
    """
    global _e2b_api_key  # pylint: disable=global-statement
    if _e2b_api_key is None:
        _e2b_api_key = read_secret("e2b_api_key")
        logger.info("tools.execute_python.api_key_loaded")
    return _e2b_api_key


async def execute_python(code: str,
                         requirements: Optional[str] = None,
                         timeout: Optional[float] = 30.0) -> Dict[str, str]:
    """Execute Python code in E2B sandbox with internet access.

    Runs Python code in a secure, isolated E2B sandbox environment.
    Supports pip package installation, internet access, and file operations.
    Sandboxes are ephemeral and destroyed after execution.

    Args:
        code: Python code to execute. Can be multiple lines, imports, etc.
        requirements: Optional space-separated list of pip packages to install
            before execution (e.g., "numpy pandas matplotlib").
        timeout: Maximum execution time in seconds. Default: 30 seconds.

    Returns:
        Dictionary with execution results:
        - 'stdout': Standard output from the code.
        - 'stderr': Standard error output (warnings, errors).
        - 'results': Serialized results (matplotlib plots, return values).
        - 'error': Error message if execution failed, otherwise empty string.
        - 'success': 'true' if execution completed without errors, 'false'
            otherwise.

    Raises:
        Exception: If sandbox creation or execution fails.

    Examples:
        >>> result = await execute_python(
        ...     code="print('Hello, world!')"
        ... )
        >>> print(result['stdout'])
        Hello, world!

        >>> result = await execute_python(
        ...     code="import requests; print(requests.get('https://api.github.com').status_code)",
        ...     requirements="requests"
        ... )
        >>> print(result['stdout'])
        200
    """
    try:
        logger.info("tools.execute_python.called",
                    code_length=len(code),
                    requirements=requirements,
                    timeout=timeout)

        api_key = get_e2b_api_key()

        # Create sandbox
        sandbox = Sandbox(api_key=api_key)

        try:
            # Install pip packages if specified
            if requirements:
                logger.info("tools.execute_python.installing_packages",
                            requirements=requirements)
                install_output = sandbox.commands.run(
                    f"pip install {requirements}")
                logger.info("tools.execute_python.packages_installed",
                            exit_code=install_output.exit_code,
                            stdout_length=len(install_output.stdout))

            # Execute code
            logger.info("tools.execute_python.executing_code",
                        code_length=len(code))

            # Collect stdout and stderr
            stdout_lines: List[str] = []
            stderr_lines: List[str] = []

            execution = sandbox.run_code(code=code,
                                         timeout=timeout,
                                         on_stdout=stdout_lines.append,
                                         on_stderr=stderr_lines.append)

            # Build result
            stdout_str = "".join(stdout_lines)
            stderr_str = "".join(stderr_lines)
            error_str = str(execution.error) if execution.error else ""
            success = execution.error is None

            # Serialize results (matplotlib plots, return values, etc.)
            results_serialized = json.dumps([{
                "type": r.type,
                "data": str(r)[:1000]
            } for r in (execution.results or [])],
                                            ensure_ascii=False)

            logger.info("tools.execute_python.success",
                        success=success,
                        stdout_length=len(stdout_str),
                        stderr_length=len(stderr_str),
                        results_count=len(execution.results or []),
                        has_error=bool(error_str))

            return {
                "stdout": stdout_str,
                "stderr": stderr_str,
                "results": results_serialized,
                "error": error_str,
                "success": str(success).lower()
            }

        finally:
            # Always close sandbox
            sandbox.close()
            logger.info("tools.execute_python.sandbox_closed")

    except Exception as e:
        logger.error("tools.execute_python.failed", error=str(e), exc_info=True)
        # Re-raise to let caller handle
        raise


# Tool definition for Claude API (anthropic tools format)
EXECUTE_PYTHON_TOOL = {
    "name":
        "execute_python",
    "description":
        """Execute Python code in a secure sandbox with internet access.

Use this tool when you need to run Python code, perform calculations,
analyze data, make HTTP requests, or use Python libraries. The sandbox
has full internet access and can install any pip package on demand.

Key features:
- Secure isolated environment (ephemeral sandboxes)
- Internet access for API calls, web scraping, etc.
- Pip install any packages (numpy, pandas, requests, matplotlib, etc.)
- File operations (read/write/process files)
- Return values, stdout, stderr, and matplotlib plots

When to use: User asks to run code, perform calculations, analyze data,
make HTTP requests, process data with Python libraries, generate plots,
or execute any Python-based task.

When NOT to use: For simple arithmetic (use your built-in capabilities),
when code execution is not required, or when user explicitly asks NOT
to run code.

Limitations: 30 second timeout by default, sandbox starts fresh each time
(no persistence between calls), limited CPU/RAM (1 vCPU, reasonable memory),
no GUI/display output (headless environment).

Cost: ~$0.05 per hour of sandbox runtime. Typical execution: <1 second,
so cost per execution is <$0.0001. Free tier: $100 credit (~2000 hours).""",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type":
                    "string",
                "description": (
                    "Python code to execute. Can include imports, multiple "
                    "lines, functions, classes, etc. The code will be executed "
                    "in a fresh Python interpreter. Use print() for output.")
            },
            "requirements": {
                "type":
                    "string",
                "description": (
                    "Optional space-separated list of pip packages to install "
                    "before execution (e.g., 'numpy pandas matplotlib requests'). "
                    "Only specify packages that are not in Python standard library."
                )
            },
            "timeout": {
                "type":
                    "number",
                "description":
                    ("Maximum execution time in seconds. Default: 30. "
                     "Increase for long-running tasks.")
            }
        },
        "required": ["code"]
    }
}
