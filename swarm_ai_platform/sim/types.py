from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Message:
    msg_type: str
    src: str
    dst: str
    payload: Dict[str, Any]
    timestamp_s: int


@dataclass
class Link:
    src: str
    dst: str
    bandwidth_bps: int
    latency_ms: int = 0
    loss_rate: float = 0.1
