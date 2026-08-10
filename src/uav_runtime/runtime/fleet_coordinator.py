"""Deterministic fleet assignment proposals; this module never executes actions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class FleetAssignment:
    """A node-explicit candidate intent that still requires Runtime and Policy."""

    node_id: str
    action_type: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class FleetCoordinator:
    """Create testable assignments without direct adapter or MAVLink access.

    Inputs are mission/scene state, vehicle states, capabilities, constraints and
    policy context. Outputs are proposals only; execution must re-enter Runtime,
    Policy Gate, VehicleRegistry and the selected adapter.
    """

    def __init__(self) -> None:
        self._round_robin_cursor = 0

    def propose(
        self,
        *,
        action_type: str,
        vehicle_states: list[dict[str, Any]],
        strategy: str = "first_available",
        explicit_node_id: str | None = None,
        capabilities: dict[str, list[str]] | None = None,
        mission: dict[str, Any] | None = None,
        scene: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        policy_context: dict[str, Any] | None = None,
    ) -> list[FleetAssignment]:
        del mission, scene, constraints, policy_context
        eligible = [
            row for row in vehicle_states
            if row.get("enabled", True) and row.get("connected") and not row.get("stale", False)
            and (capabilities is None or action_type in capabilities.get(str(row.get("node_id")), []))
        ]
        if strategy == "explicit_node":
            selected = next((row for row in eligible if row.get("node_id") == explicit_node_id), None)
            return [] if selected is None else [FleetAssignment(str(explicit_node_id), action_type, "explicit_node")]
        if not eligible:
            return []
        if strategy == "round_robin":
            selected = eligible[self._round_robin_cursor % len(eligible)]
            self._round_robin_cursor += 1
            reason = "round_robin"
        elif strategy == "first_available":
            selected, reason = eligible[0], "selected_available_vehicle"
        else:
            raise ValueError("unsupported_fleet_strategy")
        return [FleetAssignment(str(selected["node_id"]), action_type, reason)]
