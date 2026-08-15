"""Deterministic tests for the standalone three-UAV patrol validator."""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

HARNESS_DIR = Path("simulation/px4_gazebo").resolve()
sys.path.insert(0, str(HARNESS_DIR))

import harness  # noqa: E402
import patrol  # noqa: E402


MANIFEST_PATH = HARNESS_DIR / "config" / "three_uav_sitl.json"
PATROL_PATH = Path(
    "scenarios/simple_recon_v0_1/missions/three_uav_patrol_v0_1.json"
)


def _inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = harness.load_manifest(MANIFEST_PATH)
    scene = harness.load_json(harness.resolve_repo_path(str(manifest["scene_path"])))
    plan = harness.load_json(PATROL_PATH)
    return manifest, scene, plan


def test_patrol_plan_has_three_separated_safe_ned_routes() -> None:
    manifest, scene, _ = _inputs()

    plan = patrol.load_patrol_plan(
        PATROL_PATH,
        manifest=manifest,
        scene=scene,
    )

    assert plan["frame"] == "local_ned"
    assert [row["node_id"] for row in plan["vehicles"]] == [
        "UAV-01",
        "UAV-02",
        "UAV-03",
    ]
    assert [row["takeoff_altitude_m"] for row in plan["vehicles"]] == [8.0, 10.0, 12.0]
    assert all(row["entry_waypoints"] for row in plan["vehicles"])
    assert all(len(row["waypoints"]) >= 3 for row in plan["vehicles"])
    assert all(
        waypoint["z_m"] < 0
        for row in plan["vehicles"]
        for waypoint in row["waypoints"]
    )


def test_enu_ned_round_trip_and_positive_altitude() -> None:
    ned = patrol.enu_to_ned(east_m=4.0, north_m=12.0, up_m=8.0)

    assert ned == patrol.PositionNED(x_m=12.0, y_m=4.0, z_m=-8.0)
    assert ned.altitude_m == 8.0
    assert patrol.ned_to_enu(ned) == {
        "east_m": 4.0,
        "north_m": 12.0,
        "up_m": 8.0,
    }


def test_waypoint_arrival_uses_three_dimensional_two_meter_radius() -> None:
    target = patrol.PositionNED(10.0, 20.0, -8.0)

    reached, error = patrol.waypoint_reached(
        patrol.PositionNED(11.0, 21.0, -9.0),
        target,
        radius_m=2.0,
    )
    missed, miss_error = patrol.waypoint_reached(
        patrol.PositionNED(12.0, 22.0, -8.0),
        target,
        radius_m=2.0,
    )

    assert reached is True
    assert error == pytest.approx(3**0.5)
    assert missed is False
    assert miss_error == pytest.approx(8**0.5)


def test_minimum_three_uav_spacing_reports_pair() -> None:
    minimum, pair = patrol.minimum_pairwise_distance(
        {
            "UAV-01": patrol.PositionNED(0.0, 0.0, -8.0),
            "UAV-02": patrol.PositionNED(0.0, 8.0, -10.0),
            "UAV-03": patrol.PositionNED(0.0, -8.0, -12.0),
        }
    )

    assert minimum == pytest.approx((8**2 + 2**2) ** 0.5)
    assert pair == ("UAV-01", "UAV-02")


def test_patrol_plan_rejects_route_through_no_fly_zone(tmp_path: Path) -> None:
    manifest, scene, plan = _inputs()
    unsafe = copy.deepcopy(plan)
    unsafe["vehicles"][2]["entry_waypoints"][-1] = {
        "x_m": -10.0,
        "y_m": 10.0,
        "z_m": -12.0,
    }
    unsafe["vehicles"][2]["waypoints"] = [
        {"x_m": 10.0, "y_m": 10.0, "z_m": -12.0},
        {"x_m": 25.0, "y_m": 10.0, "z_m": -12.0},
        {"x_m": 40.0, "y_m": 10.0, "z_m": -12.0},
    ]
    path = tmp_path / "unsafe-patrol.json"
    path.write_text(json.dumps(unsafe), encoding="utf-8")

    with pytest.raises(patrol.PatrolError, match="no_fly_zone:nfz-001"):
        patrol.load_patrol_plan(path, manifest=manifest, scene=scene)


def test_patrol_plan_rejects_unsafe_ordered_corridor_entry(tmp_path: Path) -> None:
    manifest, scene, plan = _inputs()
    unsafe = copy.deepcopy(plan)
    unsafe["vehicles"][0]["entry_waypoints"] = [
        {"x_m": 0.0, "y_m": -8.0, "z_m": -8.0},
        {"x_m": 0.0, "y_m": -20.0, "z_m": -8.0},
    ]
    path = tmp_path / "unsafe-entry-patrol.json"
    path.write_text(json.dumps(unsafe), encoding="utf-8")

    with pytest.raises(patrol.PatrolError, match="entry separation below"):
        patrol.load_patrol_plan(path, manifest=manifest, scene=scene)


def test_standalone_patrol_refuses_runtime_owned_endpoint() -> None:
    manifest, _, _ = _inputs()

    with pytest.raises(
        patrol.PatrolError,
        match="runtime_session_active:endpoint_in_use",
    ):
        patrol.require_standalone_endpoints(
            manifest,
            availability_probe=lambda endpoint: not endpoint.endswith(":14541"),
        )


class _FakeController:
    def __init__(
        self,
        node_id: str,
        position: patrol.PositionNED,
        events: list[str] | None = None,
    ) -> None:
        self.node_id = node_id
        self._position = position
        self._events = events if events is not None else []
        self.max_altitude_m = position.altitude_m
        self.connected = False
        self.recovery_land_calls = 0

    def position(self) -> patrol.PositionNED:
        return self._position

    def connect(self, *, timeout_s: float) -> dict[str, Any]:
        assert timeout_s > 0
        self.connected = True
        return {"result": 0, "timeout": False}

    def arm(self, *, timeout_s: float) -> dict[str, Any]:
        assert timeout_s > 0
        return {"result": 0, "timeout": False}

    def takeoff(self, *, altitude_m: float, timeout_s: float) -> dict[str, Any]:
        self._events.append(f"takeoff:{self.node_id}")
        self.max_altitude_m = altitude_m
        self._position = patrol.PositionNED(
            self._position.x_m,
            self._position.y_m,
            -altitude_m,
        )
        return {"result": 0, "timeout": False}

    def wait_for_altitude(self, *, threshold_m: float, timeout_s: float) -> dict[str, Any]:
        self._events.append(f"wait_altitude:{self.node_id}")
        return {
            "threshold_reached": self.max_altitude_m >= threshold_m,
            "max_altitude_m": self.max_altitude_m,
        }

    def start_offboard(self, target: patrol.PositionNED, *, timeout_s: float) -> dict[str, Any]:
        self._position = target
        return {"offboard_observed": True, "custom_main_mode": 6}

    def goto(self, waypoint: patrol.PositionNED, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        self._position = waypoint
        time.sleep(0.04)
        return {
            "reached": True,
            "target": waypoint.to_dict(),
            "observed": waypoint.to_dict(),
            "arrival_error_m": 0.0,
        }

    def land(self, *, timeout_s: float) -> dict[str, Any]:
        self.recovery_land_calls += 1
        return {"result": 0, "timeout": False}

    def wait_landed_disarmed(self, *, timeout_s: float) -> dict[str, Any]:
        self._position = patrol.PositionNED(
            self._position.x_m,
            self._position.y_m,
            0.0,
        )
        return {"landed": True, "disarmed": True, "position": self._position.to_dict()}

    def close(self) -> None:
        self.connected = False


def _fake_controllers(
    manifest: dict[str, Any],
    events: list[str] | None = None,
) -> list[_FakeController]:
    return [
        _FakeController(
            str(row["node_id"]),
            patrol.PositionNED(
                float(row["spawn_ned"]["x_m"]),
                float(row["spawn_ned"]["y_m"]),
                float(row["spawn_ned"]["z_m"]),
            ),
            events,
        )
        for row in manifest["vehicles"]
    ]


def test_run_patrol_reports_ack_waypoints_altitude_and_separation() -> None:
    manifest, scene, _ = _inputs()
    plan = patrol.load_patrol_plan(PATROL_PATH, manifest=manifest, scene=scene)
    events: list[str] = []

    report = patrol.run_patrol(
        plan,
        _fake_controllers(manifest, events),  # type: ignore[arg-type]
        sleep=lambda delay: None,
    )

    assert report["status"] == "PASS"
    assert report["separation"]["threshold_met"] is True
    assert report["separation"]["minimum_distance_m"] >= 7.0
    assert all(patrol.ack_accepted(row["arm_ack"]) for row in report["vehicles"])
    assert all(patrol.ack_accepted(row["takeoff_ack"]) for row in report["vehicles"])
    assert all(patrol.ack_accepted(row["land_ack"]) for row in report["vehicles"])
    assert [row["max_altitude_m"] for row in report["vehicles"]] == [8.0, 10.0, 12.0]
    assert all(len(row["waypoints"]) == 3 for row in report["vehicles"])
    assert [len(row["entry_waypoints"]) for row in report["vehicles"]] == [2, 1, 2]
    assert events[:3] == ["takeoff:UAV-01", "takeoff:UAV-02", "takeoff:UAV-03"]
    assert all(event.startswith("wait_altitude:") for event in events[3:6])


def test_run_patrol_timeout_produces_failure_and_recovery_report() -> None:
    manifest, scene, _ = _inputs()
    plan = patrol.load_patrol_plan(PATROL_PATH, manifest=manifest, scene=scene)
    controllers = _fake_controllers(manifest)

    goto_calls = 0

    def fail_goto(waypoint: patrol.PositionNED, **kwargs: Any) -> dict[str, Any]:
        nonlocal goto_calls
        del kwargs
        goto_calls += 1
        if goto_calls == 1:
            controllers[1]._position = waypoint
            return {
                "reached": True,
                "target": waypoint.to_dict(),
                "observed": waypoint.to_dict(),
                "arrival_error_m": 0.0,
            }
        return {
            "reached": False,
            "target": waypoint.to_dict(),
            "reason": "waypoint_timeout",
        }

    controllers[1].goto = fail_goto  # type: ignore[method-assign]

    report = patrol.run_patrol(
        plan,
        controllers,  # type: ignore[arg-type]
        sleep=lambda delay: None,
    )

    assert report["status"] == "FAIL"
    assert "UAV-02 waypoint 1 timeout" in report["error"]
    assert all("recovery_land_ack" in row for row in report["vehicles"])
