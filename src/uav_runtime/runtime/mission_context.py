"""Mission runtime context models for minimal takeover/defer handling."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from uav_runtime.protocol.enums import CommandSource
from uav_runtime.protocol.schema import ActionRequest


@dataclass(slots=True)
class MissionContext:
    mission_id: str
    status: str = "created"
    active_tasks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunningAction:
    request_id: str
    action_type: str
    source: CommandSource = CommandSource.SELF_LOCAL
    priority: int = 50
    non_preemptible: bool = False


@dataclass(slots=True)
class PendingTakeover:
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
        return now - self.created_at > self.ttl_s

    def to_audit_event(self) -> dict[str, Any]:
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
