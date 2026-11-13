"""Passive progress for an existing Runtime-owned plan; no execution authority."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import os
from threading import Lock
from typing import Any
from uuid import uuid4


def unavailable_progress() -> dict[str, Any]:
    return {
        "contract_version": "1.0", "status": "unavailable", "mode": "LIVE",
        "source": "runtime_plan_executor", "mission_id": None, "run_id": None,
        "scene_id": None, "map_version": None, "source_timestamp": None,
        "completion_basis": None, "completion_pct": None,
        "waypoints_reached": None, "waypoints_total": None,
        "area_total_km2": None, "area_covered_km2": None, "coverage_pct": None,
        "targets_found": None, "targets_total": None, "degraded": None,
        "vehicles_active": None, "vehicles": [], "coverage": None, "coverage_reason": None,
        "reason": "no_runtime_plan_execution",
    }


def configured_coverage(scene: dict[str, Any] | None, map_version: str) -> tuple[Any, str | None, list | None]:
    area = os.environ.get("UAV_RUNTIME_COVERAGE_AREA_ID")
    footprint = os.environ.get("UAV_RUNTIME_COVERAGE_FOOTPRINT_M")
    if not area or not footprint:
        return None, "coverage_not_configured", None
    if not scene or scene.get("map_version") != map_version:
        return None, "coverage_map_mismatch", None
    try:
        radius = float(footprint)
        if not math.isfinite(radius) or radius <= 0:
            raise ValueError("invalid footprint")
        # Optional checkout-owned Simulation dependency; no patrol is started.
        from simulation.px4_gazebo.area_coverage import AreaCoverage
        provider = AreaCoverage(scene, area, footprint_radius_m=radius)
        polygon = next(item["polygon"] for item in scene["coverage_areas"] if item["area_id"] == area)
        return provider, None, deepcopy(polygon)
    except ImportError:
        return None, "coverage_provider_unavailable", None
    except (ValueError, TypeError, KeyError, OverflowError, StopIteration):
        return None, "coverage_configuration_invalid", None


class MissionProgress:
    """Wrap the existing executor without altering any action or success result."""

    def __init__(self, executor: Any, plan: Any, *, scene_id: str, map_version: str,
                 coverage: Any = None,
                 coverage_reason: str | None = None, coverage_polygon: list | None = None) -> None:
        self.executor = executor
        self.mission_id, self.run_id = plan.plan_id, uuid4().hex
        self.scene_id, self.map_version = scene_id, map_version
        self._lock = Lock()
        self._waypoints: dict[str, int] = {}
        self._reached: dict[str, set[int]] = {}
        self._counted_steps: set[int] = set()
        for step in plan.steps:
            if step.node_id:
                self._waypoints.setdefault(step.node_id, 0)
                self._reached.setdefault(step.node_id, set())
                if step.action_type.strip().lower() == "goto":
                    self._waypoints[step.node_id] += 1
        # Here "active" means assigned to the plan, not armed or airborne.
        self._active = set(self._waypoints)
        self._status = "running"
        self._degraded = False
        self._timestamp = self._now()
        self._coverage, self._coverage_reason = coverage, coverage_reason
        self._coverage_polygon = coverage_polygon
        self._last_samples: dict[str, tuple[int, int]] = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def execute_step(self, step: Any) -> Any:
        outcome = self.executor.execute_step(step)
        action, node = outcome.action_type, outcome.node_id
        with self._lock:
            if node in self._waypoints and node == step.node_id:
                raw = outcome.raw or {}
                if (outcome.ok and step.action_type.strip().lower() == "goto" and action == "goto"
                        and raw.get("result") == "pass"
                        and raw.get("arrival_observed") is True and id(step) not in self._counted_steps):
                    self._counted_steps.add(id(step))
                    self._reached[node].add(id(step))
                    if self._coverage is not None:
                        self._observe_coverage(node, raw)
                if outcome.ok and raw.get("result") == "pass" and action in {"land", "return_home"}:
                    self._active.discard(node)
                    self._degraded |= action == "return_home"
            self._timestamp = self._now()
        return outcome

    def _observe_coverage(self, node: str, raw: dict[str, Any]) -> None:
        try:
            arrival = raw.get("completion_evidence") or {}
            sample = arrival.get("position_sample")
            calibration = raw.get("arrival_calibration")
            if not isinstance(sample, dict) or not isinstance(calibration, dict):
                return
            if (calibration.get("scene_id") != self.scene_id or calibration.get("map_version") != self.map_version
                    or calibration.get("session_position_epoch") != sample["position_epoch"]):
                return
            start = arrival.get("start_sequence")
            if type(start) is not int or sample["sequence"] <= start:
                return
            key = sample["position_epoch"], sample["sequence"]
            if key <= self._last_samples.get(node, (-1, -1)):
                return
            offset = calibration["translation_scene_ned_m"]
            self._coverage.observe(north_m=sample["north"] + offset["north"],
                                   east_m=sample["east"] + offset["east"])
            self._last_samples[node] = key
        except Exception:
            # Optional display evidence must not interrupt or reinterpret an action.
            self._coverage_reason = "coverage_observation_unavailable"

    def finish(self, result: str | None) -> None:
        with self._lock:
            self._status = result if result in {"completed", "failed", "blocked"} else "failed"
            self._active.clear()
            self._timestamp = self._now()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = sum(self._waypoints.values())
            reached = sum(map(len, self._reached.values()))
            try:
                coverage = self._coverage.report() if self._coverage is not None else {}
            except (TypeError, ValueError, OverflowError):
                coverage = {}
            if coverage and self._coverage_polygon is not None:
                coverage = {**coverage, "polygon": deepcopy(self._coverage_polygon)}
            return {
                **unavailable_progress(), "status": self._status, "mission_id": self.mission_id,
                "run_id": self.run_id, "scene_id": self.scene_id, "map_version": self.map_version,
                "source_timestamp": self._timestamp, "reason": None,
                "completion_basis": "verified_waypoints" if total else None,
                "completion_pct": round(100 * reached / total, 2) if total else None,
                "waypoints_reached": reached, "waypoints_total": total,
                "vehicles_active": len(self._active), "degraded": self._degraded,
                "vehicles": [{"node_id": node, "active": node in self._active,
                              "waypoints_reached": len(self._reached[node]), "waypoints_total": count}
                             for node, count in sorted(self._waypoints.items())],
                "coverage": coverage or None, "coverage_reason": self._coverage_reason,
                "area_total_km2": coverage.get("area_total_km2"),
                "area_covered_km2": coverage.get("area_covered_km2"),
                "coverage_pct": coverage.get("completion_pct"),
            }
