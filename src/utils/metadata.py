# src/utils/metadata.py
"""Metadata sanitisation shared by the CLI and the recording route (VRT-10)."""

from __future__ import annotations

from typing import Any


def sanitize_metadata(data: Any) -> Any:
    """
    Recursively decodes C-style byte strings into UTF-8 strings
    to prevent JSON serialization crashes in the database manager.
    """
    if isinstance(data, dict):
        return {k: sanitize_metadata(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_metadata(v) for v in data]
    elif isinstance(data, bytes):
        return data.decode("utf-8", errors="ignore")
    return data
