"""Execute Python code tool using E2B Code Interpreter.

This module implements the execute_python tool for running AI-generated
Python code in secure sandboxed environments with internet access and
pip package installation support.

NO __init__.py - use direct import:
    from core.tools.execute_python import execute_python, EXECUTE_PYTHON_TOOL
"""

import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.claude.files_api import download_from_files_api
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


# pylint: disable=too-many-locals,too-many-statements
async def execute_python(code: str,
                         file_inputs: Optional[List[Dict[str, str]]] = None,
                         requirements: Optional[str] = None,
                         timeout: Optional[float] = 180.0) -> Dict[str, Any]:
    """Execute Python code in E2B sandbox with file support.

    Runs Python code in secure E2B sandbox (Linux, Python 3.11+, headless).
    Supports pip packages, internet access, input/output file operations.
    Sandboxes are ephemeral and destroyed after execution.

    Environment:
    - Working directory: /home/user
    - Input files (if file_inputs provided): /tmp/inputs/{filename}
    - Output files: Save to /tmp/ or subdirectories
    - Bot auto-detects and downloads all new files from /tmp/

    Args:
        code: Python code to execute. Can include imports, multiple
            lines, functions, classes, etc.
        file_inputs: Optional list of input files to upload to sandbox.
            Each item: {"file_id": "file_abc...", "name": "document.pdf"}.
            Files will be available at /tmp/inputs/{name}.
        requirements: Optional space-separated list of pip packages
            (e.g., "numpy pandas matplotlib requests").
        timeout: Maximum execution time in seconds. Default: 180 seconds
            (3 minutes). Can be increased up to 3600 seconds (1 hour).

    Returns:
        Dictionary with execution results:
        - 'stdout': Standard output from the code.
        - 'stderr': Standard error output (warnings, errors).
        - 'results': Serialized results (matplotlib plots, return values).
        - 'error': Error message if execution failed, otherwise empty.
        - 'success': 'true' if no errors, 'false' otherwise.
        - 'generated_files': JSON list of generated files with metadata:
            [{"filename": "output.pdf", "size": 102400, "mime_type": "..."}]

    Raises:
        Exception: If sandbox creation, file operations, or execution fails.

    Examples:
        >>> # Simple execution
        >>> result = await execute_python(code="print('Hello!')")
        >>> print(result['stdout'])
        Hello!

        >>> # With input files
        >>> result = await execute_python(
        ...     code=("import pandas as pd; "
        ...           "df = pd.read_csv('/tmp/inputs/data.csv'); "
        ...           "print(df.head())"),
        ...     file_inputs=[{"file_id": "file_xyz", "name": "data.csv"}],
        ...     requirements="pandas"
        ... )

        >>> # With output files
        >>> result = await execute_python(
        ...     code="with open('/tmp/output.txt', 'w') as f: f.write('Result')"
        ... )
        >>> print(result['generated_files'])
        [{"filename": "output.txt", "size": 6, "mime_type": "text/plain"}]
    """
    try:
        logger.info("tools.execute_python.called",
                    code_length=len(code),
                    file_inputs_count=len(file_inputs or []),
                    requirements=requirements,
                    timeout=timeout)

        api_key = get_e2b_api_key()

        # Set E2B_API_KEY environment variable for Sandbox.create()
        import os  # pylint: disable=import-outside-toplevel
        os.environ["E2B_API_KEY"] = api_key

        # Create sandbox (new API in v1.0+ with context manager)
        with Sandbox.create() as sandbox:
            # Upload input files to sandbox if specified
            if file_inputs:
                logger.info("tools.execute_python.uploading_input_files",
                            file_count=len(file_inputs))

                # Create /tmp/inputs/ directory
                sandbox.commands.run("mkdir -p /tmp/inputs")

                for file_input in file_inputs:
                    file_id = file_input["file_id"]
                    filename = file_input["name"]

                    logger.info(
                        "tools.execute_python.downloading_file_from_api",
                        file_id=file_id,
                        filename=filename)

                    # Download from Files API
                    file_content = await download_from_files_api(file_id)

                    # Upload to sandbox
                    sandbox_path = f"/tmp/inputs/{filename}"
                    sandbox.files.write(sandbox_path, file_content)

                    logger.info("tools.execute_python.file_uploaded_to_sandbox",
                                file_id=file_id,
                                filename=filename,
                                sandbox_path=sandbox_path,
                                size_bytes=len(file_content))

            # Install pip packages if specified
            if requirements:
                logger.info("tools.execute_python.installing_packages",
                            requirements=requirements)
                install_output = sandbox.commands.run(
                    f"pip install {requirements}")
                logger.info("tools.execute_python.packages_installed",
                            exit_code=install_output.exit_code,
                            stdout_length=len(install_output.stdout))

            # Execute code (E2B v1.0+ API)
            logger.info("tools.execute_python.executing_code",
                        code_length=len(code),
                        timeout=timeout)

            execution = sandbox.run_code(code=code, timeout=timeout)

            # E2B v1.0+ API: execution.logs.stdout/stderr are lists of strings
            stdout_list = execution.logs.stdout if execution.logs else []
            stderr_list = execution.logs.stderr if execution.logs else []

            logger.info("tools.execute_python.execution_complete",
                        stdout_lines=len(stdout_list),
                        stderr_lines=len(stderr_list),
                        has_error=bool(execution.error),
                        has_results=bool(execution.results))

            # Build result strings
            stdout_str = "".join(stdout_list)
            stderr_str = "".join(stderr_list)
            error_str = str(execution.error) if execution.error else ""
            success = execution.error is None

            # Serialize results
            # execution.results is a list of result objects
            results_list = []
            if execution.results:
                for r in execution.results:
                    # Log result structure for debugging
                    logger.debug("tools.execute_python.result_object",
                                 result_type=type(r).__name__,
                                 result_str=str(r)[:200])
                    results_list.append(str(r)[:1000])

            results_serialized = json.dumps(results_list, ensure_ascii=False)

            # Scan for generated files in /tmp/ (excluding /tmp/inputs/)
            generated_files: List[Dict[str, Any]] = []

            try:
                logger.info("tools.execute_python.scanning_output_files")

                # List all files in /tmp/ recursively
                all_files = sandbox.files.list("/tmp")

                for entry in all_files:
                    # Skip directories and input files
                    if not entry.name or entry.name == "inputs":
                        continue

                    file_path = entry.path

                    # Skip /tmp/inputs/ files
                    if file_path.startswith("/tmp/inputs/"):
                        continue

                    # Download file content
                    logger.info("tools.execute_python.downloading_output_file",
                                path=file_path,
                                name=entry.name)

                    file_bytes = sandbox.files.read(file_path, format="bytes")

                    # Determine mime type from extension
                    mime_type, _ = mimetypes.guess_type(entry.name)
                    if not mime_type:
                        mime_type = "application/octet-stream"

                    # Store file metadata (content will be handled by caller)
                    generated_files.append({
                        "filename": entry.name,
                        "path": file_path,
                        "size": len(file_bytes),
                        "mime_type": mime_type,
                        "content": file_bytes  # Raw bytes for caller
                    })

                    logger.info("tools.execute_python.output_file_found",
                                filename=entry.name,
                                size=len(file_bytes),
                                mime_type=mime_type)

                logger.info("tools.execute_python.output_files_scanned",
                            file_count=len(generated_files))

            except Exception as scan_error:  # pylint: disable=broad-exception-caught
                logger.warning("tools.execute_python.output_scan_failed",
                               error=str(scan_error),
                               exc_info=True)
                # Continue execution even if scan fails

            # Serialize generated_files for JSON (remove content bytes)
            generated_files_meta = [{
                "filename": f["filename"],
                "path": f["path"],
                "size": f["size"],
                "mime_type": f["mime_type"]
            } for f in generated_files]

            logger.info("tools.execute_python.success",
                        success=success,
                        stdout_length=len(stdout_str),
                        stderr_length=len(stderr_str),
                        results_count=len(execution.results or []),
                        generated_files_count=len(generated_files),
                        has_error=bool(error_str))

            return {
                "stdout":
                    stdout_str,
                "stderr":
                    stderr_str,
                "results":
                    results_serialized,
                "error":
                    error_str,
                "success":
                    str(success).lower(),
                "generated_files":
                    json.dumps(generated_files_meta, ensure_ascii=False),
                "_file_contents":
                    generated_files  # Internal: raw bytes
            }

        # Context manager automatically closes sandbox
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
        """Execute Python code in secure E2B sandbox with file I/O support.

Use this when you need to: run code, perform calculations, analyze data,
make HTTP requests, process files, generate files (PDF/PNG/CSV/etc.),
or use Python libraries. Full internet + pip install support.

ENVIRONMENT (E2B sandbox - Linux, Python 3.11+, headless):
- Working directory: /home/user
- Input files (if file_inputs provided): /tmp/inputs/{filename}
- Output files: Save to /tmp/ or subdirectories (e.g., /tmp/output.pdf)
- Bot auto-downloads ALL new files from /tmp/ (excluding /tmp/inputs/)

INPUT FILES:
Specify file_inputs with file_id and name from "Available files" section.
Files uploaded to /tmp/inputs/ before execution.
Example: file_inputs=[{"file_id": "file_abc...", "name": "document.pdf"}]
In code: open('/tmp/inputs/document.pdf', 'rb')

OUTPUT FILES:
Save to /tmp/ (any format: PDF, PNG, CSV, XLSX, TXT, etc.)
Bot automatically detects, downloads, uploads to Files API, sends to user,
and adds to context. Generated files become available for future operations.
Example: plt.savefig('/tmp/chart.png')

WORKFLOW EXAMPLE:
User: "Convert data.csv to PDF report with chart"
1. Call: execute_python(file_inputs=[{"file_id":"file_xyz", "name":"data.csv"}], ...)
2. Code: pd.read_csv('/tmp/inputs/data.csv'); generate_report('/tmp/report.pdf')
3. Bot downloads report.pdf, sends to user, adds to context
4. You can reference report.pdf in next messages

KEY FEATURES:
- Secure isolated environment (ephemeral, starts fresh each time)
- Internet access (API calls, web scraping, downloads)
- Pip packages (numpy, pandas, matplotlib, requests, pillow, etc.)
- File processing (read/write/convert any format)
- Return: stdout, stderr, matplotlib plots, generated files

WHEN TO USE:
User asks to: run code, perform calculations, analyze data, make HTTP requests,
process files, generate files (reports/charts/images), use Python libraries,
data transformations, file format conversions, image processing, or any
Python-based task.

WHEN NOT TO USE:
Simple arithmetic (use built-in capabilities), no code execution needed,
or user explicitly asks NOT to run code.

LIMITATIONS:
- 180 second timeout (3 minutes, configurable up to 1 hour)
- No persistence between calls (fresh sandbox each time)
- Limited CPU/RAM (1 vCPU, reasonable memory)
- Headless (no GUI/display output, but can save to files)

COST: ~$0.05/hour of runtime. Typical execution: <1 second = <$0.0001.
Free tier: $100 credit (~2000 hours).""",
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type":
                    "string",
                "description": (
                    "Python code to execute. Can include imports, multiple "
                    "lines, functions, classes, etc. Input files at /tmp/inputs/, "
                    "save outputs to /tmp/. Use print() for debug output.")
            },
            "file_inputs": {
                "type":
                    "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type":
                                "string",
                            "description": (
                                "claude_file_id from 'Available files' section "
                                "in system prompt (e.g., 'file_abc123...').")
                        },
                        "name": {
                            "type":
                                "string",
                            "description": (
                                "Original filename from 'Available files' "
                                "(e.g., 'document.pdf'). File will be available "
                                "at /tmp/inputs/{name} in sandbox.")
                        }
                    },
                    "required": ["file_id", "name"]
                },
                "description":
                    ("List of input files to upload to sandbox. "
                     "Use file_id and name from 'Available files' section. "
                     "Files uploaded to /tmp/inputs/ before code execution. "
                     "Optional - omit if no file inputs needed.")
            },
            "requirements": {
                "type":
                    "string",
                "description": (
                    "Space-separated list of pip packages to install before "
                    "execution (e.g., 'numpy pandas matplotlib requests pillow'). "
                    "Only packages not in Python standard library. Optional.")
            },
            "timeout": {
                "type":
                    "number",
                "description": (
                    "Maximum execution time in seconds. Default: 180 (3 minutes). "
                    "Can be increased up to 3600 (1 hour) for long tasks. Optional."
                )
            }
        },
        "required": ["code"]
    }
}
