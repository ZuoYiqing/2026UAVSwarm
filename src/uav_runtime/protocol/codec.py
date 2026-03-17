"""Envelope JSON 编解码入口（含时间字段处理）。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .enums import MessageType
from .schema import Envelope


def encode_envelope(env: Envelope) -> str:
    return json.dumps(env.to_dict(), ensure_ascii=False)


def decode_envelope(text: str) -> Envelope:
    raw: dict[str, Any] = json.loads(text)
    datetime.fromisoformat(raw["timestamp"])
    return Envelope(
        message_type=MessageType(raw["message_type"]),
        trace_id=raw["trace_id"],
        timestamp=raw["timestamp"],
        payload=raw.get("payload", {}),
    )
