from __future__ import annotations

from dataclasses import dataclass, field

from .base import AdapterResult


@dataclass(slots=True)
class FakeAdapter:
    name: str = "fake"
    sent: list[dict] = field(default_factory=list)

    def send(self, payload: dict) -> AdapterResult:
        self.sent.append(payload)
        return AdapterResult(accepted=True, detail=f"{self.name}:ok")
