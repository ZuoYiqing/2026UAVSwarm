"""Versioned, time-bounded evidence shared by simulation producers."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def timestamp_seconds(value: Any) -> float:
    if not isinstance(value, str):
        raise ValueError("timestamp_required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_timezone_required")
    return parsed.timestamp()


def freshness(payload: dict[str, Any], *, now: float | None = None) -> tuple[bool, str, float | None]:
    """Check the producer's timestamp, not the time a saved file was read."""
    try:
        if payload.get("contract_version") != "1.0":
            return False, "unsupported_evidence_version", None
        ttl = payload["valid_for_ms"]
        if isinstance(ttl, bool) or not isinstance(ttl, (float, int)) or not math.isfinite(ttl) or not 100 <= ttl <= 60000:
            raise ValueError("invalid_evidence_ttl")
        age = ((datetime.now(timezone.utc).timestamp() if now is None else now)
               - timestamp_seconds(payload["source_timestamp"])) * 1000
        if age < -100:
            return False, "evidence_from_future", age
        if age > ttl:
            return False, "evidence_stale", age
        return True, "ok", max(0.0, age)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False, "invalid_evidence_timestamp_or_ttl", None


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def json_messages(output: str) -> list[dict[str, Any]]:
    """gz topic --json-output emits one protobuf JSON object per line."""
    rows = []
    for line in output.splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("gazebo_message_not_object")
            rows.append(value)
    return rows


def proto_time(value: dict[str, Any]) -> float:
    return int(value.get("sec", 0)) + int(value.get("nsec", 0)) / 1_000_000_000
