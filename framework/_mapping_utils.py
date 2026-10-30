"""Shared helpers for mapping metadata values and filenames."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

def safe_filename(name: str) -> str:
    """Replace characters that are unsafe in common file systems."""
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return filename or "mapping"

def unique_filename(name: str, used_names: set[str]) -> str:
    filename = safe_filename(name)
    candidate = filename
    suffix = 2
    while candidate.casefold() in used_names:
        candidate = f"{filename}_{suffix}"
        suffix += 1
    used_names.add(candidate.casefold())
    return candidate

def unique_nested_filename(
    name: str,
    directories: tuple[str, ...],
    used_paths: set[str],
) -> str:
    filename = safe_filename(name)
    candidate = filename
    suffix = 2
    while PurePosixPath(*directories, f"{candidate}.yaml").as_posix().casefold() in used_paths:
        candidate = f"{filename}_{suffix}"
        suffix += 1
    used_paths.add(
        PurePosixPath(*directories, f"{candidate}.yaml").as_posix().casefold()
    )
    return candidate

def mapping_value(value: Any) -> Any:
    """Convert Excel date/time values to stable ISO-8601 strings."""
    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except (OverflowError, ValueError):
            pass
    return value
