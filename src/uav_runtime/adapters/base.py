from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class AdapterResult:
    accepted: bool
    detail: str


class Adapter(Protocol):
    name: str

    def send(self, payload: dict) -> AdapterResult:
        """Send one canonical payload to external execution plane."""
