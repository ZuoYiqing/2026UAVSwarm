"""本轮最后修补点：强化 canonical 优先级与 risk_hint(MVP int) 冻结说明，保留 legacy alias 迁移兼容。"""
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
    protocol_version: str = "1.0"
    schema_id: str = "uav_runtime.envelope.v1"
    message_id: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    causation_id: str | None = None
    mission_id: str | None = None
    source: str = "runtime"
    target: str = "runtime"
    timestamp: str = field(default_factory=utc_now_iso)
    ttl: int = 30
    payload: dict[str, Any] = field(default_factory=dict)
    audit_ref: str | None = None
    replay_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ActionRequest:
    # legacy aliases（迁移兼容）:
    # - action   -> canonical: action_type
    # - scope    -> canonical: requested_scope
    # - priority -> canonical: priority_hint
    # canonical 优先级（冻结）：action_type / requested_scope / priority_hint。
    # legacy 字段仅为平滑迁移保留，不是长期主入口。
    action: str
    params: dict[str, Any]
    source: CommandSource
    scope: AuthorityScope
    priority: int = 50

    # canonical contract skeleton fields
    request_id: str = ""
    mission_id: str = ""
    action_type: str = ""
    skill_group: str = "generic"
    target_set: list[str] = field(default_factory=list)
    requested_scope: AuthorityScope | None = None
    # 冻结说明：MVP risk_hint 使用 int 风险等级；未来如切换 R1/R2 枚举，必须统一升级 schema/test/registry。
    risk_hint: int = 1
    priority_hint: int | None = None
    requires_confirmation_hint: bool = False
    delegation_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        # 轻量规范化方向：优先写入 canonical 字段，legacy 仅回填兼容。
        if not self.action_type:
            self.action_type = self.action
        if self.requested_scope is None:
            self.requested_scope = self.scope
        if self.priority_hint is None:
            self.priority_hint = self.priority


@dataclass(slots=True)
class PolicyDecision:
    # 注：PolicyDecisionEnvelope（policy/decision.py）是当前 policy 层权威决策对象；
    # 本类仅作协议/兼容视图，后续可收敛到单一权威模型。
    decision_code: DecisionCode | str = DecisionCode.DENY
    # legacy aliases for existing tests/callers
    decision: DecisionCode | str | None = None
    primary_reason_code: str | None = None
    primary_reason: str | None = None
    secondary_reason_codes: list[str] = field(default_factory=list)
    error_code: str | None = None
    effective_scope: AuthorityScope | str | None = None
    effective_profile_id: str | None = None
    effective_risk_level: int | None = None
    enforced_constraints: list[str] = field(default_factory=list)
    handover_plan: dict[str, Any] | None = None
    policy_trace_id: str = ""
    audit_tags: list[str] = field(default_factory=list)

    # compatibility field
    preempt_target_task_id: str | None = None

    def __post_init__(self) -> None:
        if self.decision is not None:
            self.decision_code = self.decision
        else:
            self.decision = self.decision_code

        if self.primary_reason and not self.primary_reason_code:
            self.primary_reason_code = self.primary_reason
        elif self.primary_reason_code and not self.primary_reason:
            self.primary_reason = self.primary_reason_code


@dataclass(slots=True)
class ActionResult:
    request_id: str = ""
    status: str = "unknown"
    code: str = ""
    message: str = ""
    evidence_ref: str | None = None
    timestamps: dict[str, str] = field(default_factory=dict)

    # legacy compatibility fields
    accepted: bool = False
    detail: str = ""
    adapter: str = ""
