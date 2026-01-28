"""Root conftest.py to ensure path is set before test collection."""
import os
import sys

# Add /app to sys.path before any test imports
_app_path = os.path.dirname(os.path.abspath(__file__))
if _app_path not in sys.path:
    sys.path.insert(0, _app_path)

# Pre-import modules that have import issues during pytest collection
# This ensures they're in sys.modules before pytest tries to import test files
# pylint: disable=wrong-import-position,unused-import
import utils.metrics  # noqa: E402,F401
import utils.structured_logging  # noqa: E402,F401
