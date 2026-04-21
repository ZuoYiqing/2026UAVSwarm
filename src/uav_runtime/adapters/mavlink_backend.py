"""Future MAVLink backend interface (adapter-internal abstraction).

This interface is intentionally minimal for v0.1/v0.2-prep:
- backend availability/status
- backend self-description
- execution of already-mapped actions

It does NOT include policy decisions, control-plane schema shaping, or
connection lifecycle state machines.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MavlinkBackend(Protocol):
    """Minimal backend interface for future MAVLink implementations."""

    name: str

    def status(self) -> str:
        ...

    def describe(self) -> dict[str, Any]:
        ...

    def execute_mapped_action(
        self,
        action: str,
        mapping: dict[str, Any],
        args: dict[str, Any],
    ) -> dict[str, Any]:
        ...
