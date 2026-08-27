"""Helpers for safely reading Genesis API payloads."""

from collections.abc import Mapping
from typing import Any


def as_mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping value, or an empty mapping for malformed payloads."""
    return value if isinstance(value, Mapping) else {}


def latest_usage_breakdown(value: Any) -> Mapping[str, Any] | None:
    """Return the first electricity usage breakdown when it is a mapping."""
    electricity = as_mapping(value).get("electricity")
    breakdowns = as_mapping(electricity).get("breakdowns")
    if isinstance(breakdowns, list) and breakdowns:
        breakdown = breakdowns[0]
        return breakdown if isinstance(breakdown, Mapping) else None
    return None
