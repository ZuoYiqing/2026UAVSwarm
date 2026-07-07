"""Mission runtime context models for minimal takeover/defer handling."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from uav_runtime.protocol.enums import CommandSource
from uav_runtime.protocol.schema import ActionRequest


@dataclass(slots=True)
class MissionContext:
    """Minimal mission-level state placeholder.

    当前项目主要测试 ActionRequest 流程；MissionContext 只保留最小字段，避免过早引入复杂任务树。
    """

    mission_id: str
    status: str = "created"
    active_tasks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunningAction:
    """Runtime view of an action that is considered active.

    non_preemptible=True 表示当前阶段不能立即被抢占；高优先级请求会被 Policy Gate DEFER，
    然后 RuntimeOrchestrator 记录 PendingTakeover 等待 phase_exit。
    """

    request_id: str
    action_type: str
    source: CommandSource = CommandSource.SELF_LOCAL
    priority: int = 50
    non_preemptible: bool = False


@dataclass(slots=True)
class PendingTakeover:
    """Deferred high-priority takeover request.

    pending_takeover 是 runtime control-plane 状态，不是飞控动作：
    - pending: 等待 phase_exit 或 TTL；
    - admitted/activated: phase_exit 后重评估通过；
    - expired/dropped: 超时或重评估失败。
    """

    takeover_id: str
    request_id: str
    mission_id: str
    action_type: str
    source: CommandSource
    priority: int
    created_at: float
    ttl_s: float
    status: str = "pending"
    reason_code: str = ""
    request: ActionRequest | None = None

    def is_expired(self, now: float) -> bool:
        # Strict greater-than keeps exact boundary deterministic in tests.
        return now - self.created_at > self.ttl_s

    def to_audit_event(self) -> dict[str, Any]:
        # Keep audit fields small and JSON-serializable for replay_last().
        return {
            "takeover_id": self.takeover_id,
            "request_id": self.request_id,
            "mission_id": self.mission_id,
            "action_type": self.action_type,
            "source": self.source.value,
            "priority": self.priority,
            "created_at": self.created_at,
            "ttl_s": self.ttl_s,
            "status": self.status,
            "reason_code": self.reason_code,
        }
