"""Read-only runtime state API and managed telemetry collector tests."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import pytest

from uav_runtime.adapters.px4_telemetry import apply_mavlink_message, new_snapshot
from uav_runtime.adapters.px4_telemetry_collector import Px4TelemetryCollector
from uav_runtime.agent.lifecycle import PlanExecutionController
from uav_runtime.agent.planner import MissionIntent, TemplateAgentPlanner
from uav_runtime.http import routes
from uav_runtime.http.routes import dispatch
from uav_runtime.runtime.audit_log import AuditLog
from uav_runtime.http.state_store import RuntimeStateStore


class FakeHeader:
    srcSystem = 1
    srcComponent = 1


class FakeMsg:
    def __init__(self, msg_type: str, **fields: Any) -> None:
        self._msg_type = msg_type
        self._header = FakeHeader()
        for key, value in fields.items():
            setattr(self, key, value)

    def get_type(self) -> str:
        return self._msg_type


def populated_snapshot() -> Any:
    snapshot = new_snapshot(endpoint="udpin:127.0.0.1:14030")
    apply_mavlink_message(
        snapshot,
        FakeMsg("HEARTBEAT", type=2, autopilot=12, base_mode=128, custom_mode=4, system_status=4),
        flight_mode="AUTO.LOITER",
    )
    apply_mavlink_message(snapshot, FakeMsg("LOCAL_POSITION_NED", x=12.4, y=-3.1, z=-2.5, vx=5.2, vy=0.4, vz=0.1))
    apply_mavlink_message(snapshot, FakeMsg("ATTITUDE", roll=math.radians(1.2), pitch=math.radians(-2.1), yaw=math.radians(86)))
    apply_mavlink_message(snapshot, FakeMsg("GLOBAL_POSITION_INT", lat=312300000, lon=1214700000, relative_alt=2500, hdg=8600))
    apply_mavlink_message(
        snapshot,
        FakeMsg(
            "SYS_STATUS", voltage_battery=22800, current_battery=1260,
            battery_remaining=78, onboard_control_sensors_present=1,
            onboard_control_sensors_enabled=1, onboard_control_sensors_health=1,
        ),
    )
    apply_mavlink_message(snapshot, FakeMsg("COMMAND_ACK", command=22, result=0))
    return snapshot


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> RuntimeStateStore:
    state = RuntimeStateStore()
    monkeypatch.setattr(routes, "RUNTIME_STATE_STORE", state)
    return state


def test_unavailable_state_is_stable_without_px4_or_gazebo(store: RuntimeStateStore) -> None:
    status, telemetry = dispatch("GET", "/api/telemetry/latest")
    _, simulation = dispatch("GET", "/api/simulation/status")

    assert status == 200
    assert telemetry["status"] == "unavailable"
    assert telemetry["nodes"] == []
    assert telemetry["reason"] == "telemetry_not_started"
    assert simulation["status"] == "unknown"
    assert simulation["evidence"] == []
    assert simulation["px4_sitl_connected"] is False


def test_fake_mavlink_messages_map_to_latest_telemetry(store: RuntimeStateStore) -> None:
    store.update_telemetry(populated_snapshot())

    status, payload = dispatch("GET", "/api/telemetry/latest")
    node = payload["nodes"][0]

    assert status == 200
    assert payload["fresh"] is True
    assert node["connected"] is True
    assert node["armed"] is True
    assert node["flight_mode"] == "AUTO.LOITER"
    assert node["system_id"] == 1
    assert node["component_id"] == 1
    assert node["vehicle_type"] == "multirotor"
    assert node["local_position"]["z_down_m"] == pytest.approx(-2.5)
    assert node["local_position"]["altitude_m"] == pytest.approx(2.5)
    assert node["attitude_deg"]["yaw"] == pytest.approx(86)
    assert node["battery"]["percent"] == 78
    assert node["last_command_ack"]["command_name"] == "MAV_CMD_NAV_TAKEOFF"
    assert node["last_command_ack"]["result_name"] == "MAV_RESULT_ACCEPTED"


def test_non_finite_values_are_normalized_to_null(store: RuntimeStateStore) -> None:
    snapshot = new_snapshot(endpoint="udpin:127.0.0.1:14030", connected=True)
    apply_mavlink_message(snapshot, FakeMsg("LOCAL_POSITION_NED", x=float("nan"), y=float("inf"), z=float("nan"), vx=0, vy=0, vz=0))
    apply_mavlink_message(snapshot, FakeMsg("ATTITUDE", roll=float("nan"), pitch=0, yaw=float("inf")))
    store.update_telemetry(snapshot)

    payload = store.telemetry_latest()
    node = payload["nodes"][0]
    assert node["local_position"]["x_m"] is None
    assert node["local_position"]["y_m"] is None
    assert node["local_position"]["z_down_m"] is None
    assert node["local_position"]["altitude_m"] is None
    assert node["attitude_deg"]["roll"] is None
    assert node["attitude_deg"]["yaw"] is None
    assert "NaN" not in json.dumps(payload)
    assert "Infinity" not in json.dumps(payload)


def test_stale_detection_reports_age_and_disconnects_node() -> None:
    now = [100.0]
    store = RuntimeStateStore(stale_after_ms=2000, clock=lambda: now[0])
    store.update_telemetry(populated_snapshot(), received_at=100.0)
    now[0] = 102.5

    payload = store.telemetry_latest()

    assert payload["status"] == "stale"
    assert payload["fresh"] is False
    assert payload["age_ms"] == 2500
    assert payload["nodes"][0]["connected"] is False
    assert payload["reason"] == "telemetry_stale"


def test_required_read_only_routes_dispatch(store: RuntimeStateStore) -> None:
    store.update_telemetry(populated_snapshot())

    for path in ("/api/telemetry/latest", "/api/snapshot", "/api/vehicle-snapshot", "/api/agent/status", "/api/simulation/status"):
        status, payload = dispatch("GET", path)
        assert status == 200
        assert payload["version"] == "1.0"
        assert payload["timestamp"]


def test_runtime_snapshot_is_truthful_about_agent_and_gazebo(store: RuntimeStateStore) -> None:
    store.update_telemetry(populated_snapshot())

    payload = store.runtime_snapshot()

    assert payload["runtime_status"]["status"] == "ok"
    assert payload["simulation_status"]["status"] == "unknown"
    assert payload["simulation_status"]["evidence"] == []
    assert payload["agent_runtime"]["planner_kind"] == "template_agent_planner"
    assert payload["agent_runtime"]["llm_enabled"] is False
    assert payload["agent_runtime"]["real_execution_enabled"] is False
    assert payload["agent_runtime"]["supported_execution_modes"] == ["dry_run", "fake"]
    assert payload["agent_runtime"]["queue"] == {"supported": False, "depth": None}


def test_active_actions_only_contains_running_actions(store: RuntimeStateStore) -> None:
    action_id = store.begin_action("takeoff", backend="px4_sitl", backend_mode="sitl")
    running = store.runtime_snapshot()["active_actions"]
    assert [action["action_id"] for action in running] == [action_id]

    store.finish_action(action_id, {"result": "pass"})
    assert store.runtime_snapshot()["active_actions"] == []


def test_vehicle_snapshot_matches_supplied_cesium_contract_shape(store: RuntimeStateStore) -> None:
    store.update_telemetry(populated_snapshot())

    payload = store.vehicle_snapshot()
    vehicle = payload["vehicles"][0]

    assert payload["version"] == "1.0"
    assert payload["full_state"] is True
    assert payload["source"]["kind"] == "simulation"
    assert payload["frame"] == {"type": "NED"}
    assert vehicle["id"] == "UAV-01"
    assert vehicle["vehicle_type"] in {"multirotor", "fixed_wing", "vtol", "ugv", "usv", "uuv", "unknown"}
    assert vehicle["pose"]["frame"] == "NED"
    assert vehicle["pose"]["position_m"]["z"] == pytest.approx(-2.5)
    assert vehicle["velocity_mps"]["up"] == pytest.approx(-0.1)
    assert "agent" not in vehicle

    # Validate against the actual frontend schema when that separately uploaded
    # artifact exists.  This checkout currently does not contain frontend/.
    schema_path = Path("frontend/swarm-console/simulation-3d/public/contracts/vehicle-snapshot.schema.json")
    if schema_path.exists():
        import jsonschema  # type: ignore

        jsonschema.validate(payload, json.loads(schema_path.read_text(encoding="utf-8")))


def test_plan_is_saved_and_lifecycle_updates_are_visible(store: RuntimeStateStore, tmp_path: Path) -> None:
    planner = TemplateAgentPlanner(audit=AuditLog(str(tmp_path / "planner.jsonl")))
    result = planner.plan(MissionIntent(intent_id="intent-state", mission_type="status_only"))
    result_dict = result.to_dict()
    store.record_plan_result(result_dict)
    assert store.agent_status()["latest_plan"]["validation_summary"]["step_count"] == 3

    assert result.plan is not None
    controller = PlanExecutionController(audit=AuditLog(str(tmp_path / "lifecycle.jsonl")))
    controller.load_plan(result.plan)
    store.update_plan(result.plan)

    latest = store.agent_status()["latest_plan"]
    assert latest["plan_id"] == result.plan.plan_id
    assert latest["status"] == "validated"
    assert all(step["final_policy_check_required"] is True for step in latest["steps"])


class FakeConnection:
    def __init__(self, messages: list[Any]) -> None:
        self.messages = messages
        self.flightmode = "AUTO.LOITER"

    def recv_match(self, **_: Any) -> Any:
        if self.messages:
            return self.messages.pop(0)
        time.sleep(0.01)
        return None


class FakeSession:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.closed = False
        self.control_calls: list[str] = []
        self.target_system = 1
        self.target_component = 1
        self.running = False
        self.callbacks: dict[int, Any] = {}
        self.thread_name: str | None = None

    def connect(self, *, timeout_s: float) -> FakeConnection:
        return self.connection

    def close(self) -> None:
        self.closed = True

    def subscribe(self, callback: Any) -> int:
        token = len(self.callbacks) + 1
        self.callbacks[token] = callback
        return token

    def unsubscribe(self, token: int) -> None:
        self.callbacks.pop(token, None)

    def start_receive_loop(self, *, thread_name: str) -> bool:
        self.thread_name = thread_name
        self.running = True
        while self.connection.messages:
            message = self.connection.recv_match()
            for callback in list(self.callbacks.values()):
                callback(message)
        return True

    def receive_thread_alive(self) -> bool:
        return self.running

    def arm(self, **_: Any) -> None:
        self.control_calls.append("arm")

    def takeoff(self, **_: Any) -> None:
        self.control_calls.append("takeoff")

    def land(self, **_: Any) -> None:
        self.control_calls.append("land")


def test_collector_start_stop_updates_store_and_never_controls_vehicle() -> None:
    messages = [
        FakeMsg("HEARTBEAT", type=2, autopilot=12, base_mode=0, custom_mode=4, system_status=4),
        FakeMsg("LOCAL_POSITION_NED", x=0, y=0, z=-2.5, vx=0, vy=0, vz=0),
    ]
    session = FakeSession(FakeConnection(messages))
    store = RuntimeStateStore()
    collector = Px4TelemetryCollector(
        store,
        session=session,  # type: ignore[arg-type]
        endpoint="udpin:127.0.0.1:14540",
    )

    assert collector.start() is True
    collector.stop()

    assert session.closed is False
    assert session.control_calls == []
    assert collector.is_running() is False
    assert store.telemetry_latest()["nodes"][0]["local_position"]["altitude_m"] == pytest.approx(2.5)


def test_node_specific_collector_names_shared_receive_owner() -> None:
    session = FakeSession(FakeConnection([]))
    class Store:
        def mark_collector_started(self, **_: Any) -> None: pass
        def mark_collector_stopped(self, *args: Any, **kwargs: Any) -> None: pass
        def update_telemetry(self, *args: Any, **kwargs: Any) -> None: pass

    store = Store()
    collector = Px4TelemetryCollector(
        store,  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
        node_id="UAV-02",
        endpoint="udp:2",
    )
    assert collector.start()
    assert session.thread_name == "mavlink-rx-UAV-02"


def test_collector_cleans_up_after_receive_exception() -> None:
    class FailingSession(FakeSession):
        def start_receive_loop(self, *, thread_name: str) -> bool:
            del thread_name
            raise OSError("closed")

    session = FailingSession(FakeConnection([]))
    store = RuntimeStateStore()
    collector = Px4TelemetryCollector(
        store,
        session=session,  # type: ignore[arg-type]
        endpoint="udp:1",
    )
    with pytest.raises(OSError, match="closed"):
        collector.start()
    collector.stop()

    assert session.closed is False
    assert session.callbacks == {}
    assert collector.is_running() is False


def test_read_only_routes_do_not_invoke_flight_control(monkeypatch: pytest.MonkeyPatch, store: RuntimeStateStore) -> None:
    def forbidden(*_: Any, **__: Any) -> None:
        raise AssertionError("read-only route invoked flight control")

    monkeypatch.setattr("uav_runtime.adapters.mavlink_backend_session.MavlinkBackendSession.arm", forbidden)
    monkeypatch.setattr("uav_runtime.adapters.mavlink_backend_session.MavlinkBackendSession.takeoff", forbidden)
    monkeypatch.setattr("uav_runtime.adapters.mavlink_backend_session.MavlinkBackendSession.land", forbidden)

    for path in ("/api/telemetry/latest", "/api/snapshot", "/api/vehicle-snapshot", "/api/agent/status", "/api/simulation/status"):
        assert dispatch("GET", path)[0] == 200
