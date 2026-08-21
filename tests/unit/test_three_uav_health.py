"""Unit tests for machine-readable three-UAV simulator health evidence."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

HARNESS_DIR = Path("simulation/px4_gazebo").resolve()
sys.path.insert(0, str(HARNESS_DIR))

import harness  # noqa: E402
import health  # noqa: E402
from simulation.px4_gazebo.scripts import health_three_uav  # noqa: E402


MANIFEST_PATH = HARNESS_DIR / "config" / "three_uav_sitl.json"
RUN_ID = "health-run-001"


def _state(manifest: dict[str, Any]) -> dict[str, Any]:
    processes = []
    for index, vehicle in enumerate(manifest["vehicles"], start=1):
        pid = 5000 + index
        cwd = str((harness.RUNTIME_ROOT / vehicle["node_id"]).resolve())
        identity = harness.ProcessIdentity(
            pid=pid,
            pgid=pid,
            proc_start_time_ticks=100_000 + index,
            executable="/opt/px4/bin/px4",
            cmdline=("/opt/px4/bin/px4", "-i", str(index - 1)),
            cwd=cwd,
            run_id=RUN_ID,
        )
        processes.append(
            {
                "kind": "px4",
                "node_id": vehicle["node_id"],
                "pid": pid,
                "pgid": pid,
                "run_id": RUN_ID,
                "runtime_dir": cwd,
                "process_identity": identity.to_dict(),
            }
        )
    return {"version": "1.2", "run_id": RUN_ID, "processes": processes}


def _identity_reader(state: dict[str, Any]):  # type: ignore[no-untyped-def]
    identities = {
        int(row["pid"]): harness.ProcessIdentity.from_dict(row["process_identity"])
        for row in state["processes"]
    }

    def read(pid: int) -> harness.ProcessIdentityReadResult:
        return harness.ProcessIdentityReadResult(
            code=harness.IDENTITY_OBSERVED,
            identity=identities[pid],
        )

    return read


def _mavlink_probe(manifest: dict[str, Any]):  # type: ignore[no-untyped-def]
    by_endpoint = {
        vehicle["command_endpoint"]: vehicle for vehicle in manifest["vehicles"]
    }

    def probe(endpoint: str, timeout_s: float, stability_window_s: float) -> dict[str, Any]:
        del timeout_s
        vehicle = by_endpoint[endpoint]
        return {
            "heartbeat_fresh": True,
            "telemetry_fresh": True,
            "observed_system_ids": [vehicle["system_id"]],
            "observed_component_ids": [vehicle["component_id"]],
            "last_seen": "2026-08-16T00:00:00+00:00",
            "reason": "ok",
            "evidence": {
                "heartbeat_count": 12,
                "heartbeat_span_s": stability_window_s,
                "local_position_ned_count": 100,
            },
        }

    return probe


def _runtime_telemetry(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "1.0",
        "vehicles": [
            {
                "node_id": vehicle["node_id"],
                "system_id": vehicle["system_id"],
                "component_id": vehicle["component_id"],
                "heartbeat_fresh": True,
                "telemetry_fresh": True,
                "last_seen": "2026-08-16T00:00:00+00:00",
                "reason": "ok",
                "status": "connected",
            }
            for vehicle in manifest["vehicles"]
        ],
    }


def _collect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = "standalone",
    runtime_telemetry: dict[str, Any] | None = None,
    mavlink_probe=None,  # type: ignore[no-untyped-def]
    identity_reader=None,  # type: ignore[no-untyped-def]
) -> dict[str, Any]:
    manifest = harness.load_manifest(MANIFEST_PATH)
    state = _state(manifest)
    state_path = tmp_path / "harness_state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(harness, "STATE_PATH", state_path)
    return health.collect_health(
        manifest,
        timeout_s=0.1,
        stability_window_s=10.0,
        mode=mode,
        runtime_telemetry=runtime_telemetry,
        mavlink_probe=mavlink_probe or _mavlink_probe(manifest),
        clock_probe=lambda world, timeout: {
            "clock_advancing": True,
            "reason": "ok",
            "evidence": {"world": world, "timeout": timeout},
        },
        model_probe=lambda: {"x500_0", "x500_1", "x500_2"},
        world_probe=lambda: ["simple_recon_v0_1"],
        identity_reader=identity_reader or _identity_reader(state),
    )


def test_health_requires_clock_models_identity_and_continuous_three_node_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _collect(tmp_path, monkeypatch)

    assert payload["status"] == "ready"
    assert payload["mode"] == "standalone"
    assert payload["server_running"] is True
    assert payload["clock_advancing"] is True
    assert payload["world"] == "simple_recon_v0_1"
    assert payload["unique_system_ids"] is True
    assert [row["system_id"] for row in payload["vehicles"]] == [1, 2, 3]
    assert all(row["heartbeat_fresh"] for row in payload["vehicles"])
    assert all(row["telemetry_fresh"] for row in payload["vehicles"])
    assert all(row["process_identity_valid"] for row in payload["vehicles"])


def test_integrated_health_uses_runtime_telemetry_without_binding_mavlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)

    def forbidden_probe(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("integrated health must not open a MAVLink endpoint")

    payload = _collect(
        tmp_path,
        monkeypatch,
        mode="integrated",
        runtime_telemetry=_runtime_telemetry(manifest),
        mavlink_probe=forbidden_probe,
    )

    assert payload["status"] == "ready"
    assert payload["mode"] == "integrated"
    assert payload["evidence"]["telemetry_source"] == "runtime"
    assert payload["evidence"]["runtime_telemetry_contract_version"] == "1.0"
    assert all(
        row["evidence"]["telemetry_source"] == "runtime"
        and row["evidence"]["telemetry"]["source"] == "runtime"
        for row in payload["vehicles"]
    )


def test_integrated_health_fails_closed_when_runtime_omits_one_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    runtime_telemetry = _runtime_telemetry(manifest)
    runtime_telemetry["vehicles"] = runtime_telemetry["vehicles"][:2]

    payload = _collect(
        tmp_path,
        monkeypatch,
        mode="integrated",
        runtime_telemetry=runtime_telemetry,
        mavlink_probe=lambda *args: pytest.fail("MAVLink probe was called"),
    )

    assert payload["ready"] is False
    assert "runtime_telemetry_missing" in payload["vehicles"][2]["reason"]


def test_health_rejects_one_px4_stream_reused_as_another_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    valid_probe = _mavlink_probe(manifest)

    def duplicate_probe(endpoint: str, timeout_s: float, stability_window_s: float):  # type: ignore[no-untyped-def]
        result = valid_probe(endpoint, timeout_s, stability_window_s)
        if endpoint.endswith(":14542"):
            result["observed_system_ids"] = [2]
        return result

    payload = _collect(
        tmp_path,
        monkeypatch,
        mavlink_probe=duplicate_probe,
    )

    assert payload["ready"] is False
    assert payload["unique_system_ids"] is False
    assert "system_id_mismatch" in payload["vehicles"][2]["reason"]


def test_health_rejects_stale_local_position(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    valid_probe = _mavlink_probe(manifest)

    def stale_probe(endpoint: str, timeout_s: float, stability_window_s: float):  # type: ignore[no-untyped-def]
        result = valid_probe(endpoint, timeout_s, stability_window_s)
        if endpoint.endswith(":14541"):
            result["telemetry_fresh"] = False
            result["reason"] = "telemetry_stale"
        return result

    payload = _collect(tmp_path, monkeypatch, mavlink_probe=stale_probe)

    assert payload["ready"] is False
    assert payload["vehicles"][1]["telemetry_fresh"] is False
    assert "telemetry_stale" in payload["vehicles"][1]["reason"]


def test_health_rejects_process_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    state = _state(manifest)
    valid_reader = _identity_reader(state)

    def mismatched_reader(pid: int) -> harness.ProcessIdentityReadResult:
        result = valid_reader(pid)
        assert result.identity is not None
        if pid == 5002:
            identity = harness.ProcessIdentity(
                **(
                    result.identity.to_dict()
                    | {"proc_start_time_ticks": 999_999}
                )
            )
            return harness.ProcessIdentityReadResult(
                code=harness.IDENTITY_OBSERVED,
                identity=identity,
            )
        return result

    payload = _collect(
        tmp_path,
        monkeypatch,
        identity_reader=mismatched_reader,
    )

    assert payload["ready"] is False
    assert payload["vehicles"][1]["process_identity_valid"] is False
    assert "process_identity_mismatch" in payload["vehicles"][1]["reason"]


def test_parse_gazebo_clock_samples_and_detect_advancement() -> None:
    output = """
sim { sec: 12 nsec: 100000000 }
real { sec: 99 nsec: 0 }
sim { sec: 12 nsec: 300000000 }
"""

    assert health.parse_gazebo_clock_samples(output) == [12.1, 12.3]


def test_health_cli_persists_latest_machine_readable_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "health" / "latest.json"
    payload = {
        "contract_version": "1.0",
        "status": "ready",
        "ready": True,
        "vehicles": [],
    }
    monkeypatch.setattr(health_three_uav, "load_manifest", lambda path: {})
    monkeypatch.setattr(
        health_three_uav,
        "require_standalone_endpoints",
        lambda manifest: None,
    )
    monkeypatch.setattr(
        health_three_uav,
        "collect_health",
        lambda *args, **kwargs: payload,
    )

    assert health_three_uav.main(["--output", str(output_path)]) == 0
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_integrated_health_cli_never_checks_or_binds_standalone_endpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "health" / "integrated.json"
    telemetry_path = tmp_path / "runtime-telemetry.json"
    telemetry_path.write_text(
        json.dumps({"contract_version": "1.0", "vehicles": []}),
        encoding="utf-8",
    )
    payload = {
        "contract_version": "1.0",
        "mode": "integrated",
        "status": "ready",
        "ready": True,
        "vehicles": [],
    }
    monkeypatch.setattr(health_three_uav, "load_manifest", lambda path: {})
    monkeypatch.setattr(
        health_three_uav,
        "require_standalone_endpoints",
        lambda manifest: pytest.fail("integrated mode checked a MAVLink endpoint"),
    )

    def collect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["mode"] == "integrated"
        assert kwargs["runtime_telemetry"]["contract_version"] == "1.0"
        return payload

    monkeypatch.setattr(health_three_uav, "collect_health", collect)

    assert health_three_uav.main(
        [
            "--mode",
            "integrated",
            "--runtime-telemetry",
            str(telemetry_path),
            "--output",
            str(output_path),
        ]
    ) == 0
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload
