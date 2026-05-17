"""DelegationGrant 模型与有效性判断。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class DelegationGrant:
    source: str
    target: str
    scope: str
    allowed_skill_groups: list[str] = field(default_factory=list)
    denied_skill_groups: list[str] = field(default_factory=list)
    expiry_epoch_s: int = 0
    revoked: bool = False

    def is_valid(self, now_epoch_s: int | None = None) -> bool:
        if self.revoked:
            return False
        if now_epoch_s is None:
            now_epoch_s = int(datetime.now(tz=timezone.utc).timestamp())
        return now_epoch_s <= self.expiry_epoch_s
