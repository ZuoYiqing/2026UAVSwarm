from __future__ import annotations


def require_keys(payload: dict, keys: set[str]) -> None:
    missing = keys - set(payload.keys())
    if missing:
        raise ValueError(f"missing keys: {sorted(missing)}")


def ensure_non_empty(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty string")
