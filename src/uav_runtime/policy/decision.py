"""PolicyDecisionEnvelope 与 handover 输出模型。"""
from __future__ import annotations

from dataclasses import dataclass, field

from uav_runtime.protocol.enums import DecisionCode


@dataclass(slots=True)
class PolicyDecisionEnvelope:
    decision: DecisionCode
    reason: str | None = None
    extras: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HandoverDecision:
    handover_back: bool
    target: str | None = None
