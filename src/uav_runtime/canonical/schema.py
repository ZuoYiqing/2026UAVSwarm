from __future__ import annotations

CANONICAL_REQUIRED_FIELDS = {"msg_type", "source", "target", "body"}


def validate_canonical_payload(payload: dict) -> None:
    missing = CANONICAL_REQUIRED_FIELDS - set(payload.keys())
    if missing:
        raise ValueError(f"missing canonical fields: {sorted(missing)}")
    if not isinstance(payload["body"], dict):
        raise ValueError("body must be dict")
