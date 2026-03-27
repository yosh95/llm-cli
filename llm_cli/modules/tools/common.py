# llm_cli/modules/tools/common.py

import functools
from collections.abc import Callable
from typing import Any

from llm_cli.security.path_validator import (
    PathValidationError,
)
from llm_cli.security.path_validator import (
    validate_path as validate_path,
)
from llm_cli.security.pqc import sign_tool_result

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "cache",
    ".cache",
    "__pycache__",
    "venv",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    ".idea",
    ".vscode",
    ".env",
    ".DS_Store",
}


def file_tool_handler(
    func: Callable[..., Any],
) -> Callable[..., Any]:
    """Decorator to handle common file tool logic."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        reqs = kwargs.pop("__security_requirements__", None)
        variant_raw = reqs.get("pqc_variant") if isinstance(reqs, dict) else None
        variant = str(variant_raw) if variant_raw else "ML-DSA-65"

        try:
            result = func(*args, **kwargs)
            return sign_tool_result(result, variant=variant) if isinstance(result, str) else result
        except PathValidationError as e:
            return sign_tool_result(f"[ERROR] Security Error: {e}", variant=variant)
        except Exception as e:
            return sign_tool_result(f"[ERROR] {e}", variant=variant)

    return wrapper
