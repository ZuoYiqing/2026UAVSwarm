"""Envelope、ActionRequest、PolicyDecision、ActionResult 等数据模型。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .enums import AuthorityScope, CommandSource, DecisionCode, MessageType


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Envelope:
    message_type: MessageType
    trace_id: str
    timestamp: str = field(default_factory=utc_now_iso)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ActionRequest:
    action: str
    params: dict[str, Any]
    source: CommandSource
    scope: AuthorityScope
    priority: int = 50


@dataclass(slots=True)
class PolicyDecision:
    decision: DecisionCode
    primary_reason: str | None = None
    preempt_target_task_id: str | None = None
    handover_plan: dict[str, Any] | None = None


@dataclass(slots=True)
class ActionResult:
    accepted: bool
    detail: str
    adapter: str
