from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CanonicalMessage:
    msg_type: str
    source: str
    target: str
    body: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "msg_type": self.msg_type,
            "source": self.source,
            "target": self.target,
            "body": self.body,
        }
