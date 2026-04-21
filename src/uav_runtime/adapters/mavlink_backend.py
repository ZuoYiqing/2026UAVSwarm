"""Future MAVLink backend interface (adapter-internal abstraction)."""
from __future__ import annotations

from typing import Any, Protocol


class MavlinkBackend(Protocol):
    """Minimal backend interface for future MAVLink implementations."""

    name: str

    def status(self) -> str:
        ...

    def describe(self) -> dict[str, Any]:
        ...

    def execute_mapped_action(self, action: str, mapping: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
        ...
