"""Deterministic tests for the manifest-driven three-UAV simulation harness."""
from __future__ import annotations

import copy
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

HARNESS_DIR = Path("simulation/px4_gazebo").resolve()
sys.path.insert(0, str(HARNESS_DIR))

import harness


MANIFEST_PATH = HARNESS_DIR / "config" / "three_uav_sitl.json"
SCENE_PATH = Path("scenarios/simple_recon_v0_1/scene.json")
WORLD_PATH = Path("scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf")


def _manifest() -> dict[str, object]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _scene() -> dict[str, object]:
    return json.loads(SCENE_PATH.read_text(encoding="utf-8"))


def test_manifest_has_stable_three_vehicle_mapping() -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    rows = harness.mapping_rows(manifest)

    assert [row["node_id"] for row in rows] == ["UAV-01", "UAV-02", "UAV-03"]
    assert [row["px4_instance"] for row in rows] == [0, 1, 2]
    assert [row["system_id"] for row in rows] == [1, 2, 3]
    assert [vehicle["component_id"] for vehicle in manifest["vehicles"]] == [1, 1, 1]
    assert [row["gazebo_model_name"] for row in rows] == [
        "x500_0",
        "x500_1",
        "x500_2",
    ]
    assert [row["command_endpoint"] for row in rows] == [
        "udpin:127.0.0.1:14540",
        "udpin:127.0.0.1:14541",
        "udpin:127.0.0.1:14542",
    ]
    assert [vehicle["px4_mavlink_local_port"] for vehicle in manifest["vehicles"]] == [
        14580,
        14581,
        14582,
    ]
    assert [vehicle["gcs_local_port"] for vehicle in manifest["vehicles"]] == [
        18570,
        18571,
        18572,
    ]


def test_retained_runtime_mapping_matches_manifest_truth() -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    runtime_config = json.loads(
        Path("config/vehicles.sitl.json").read_text(encoding="utf-8")
    )

    harness.validate_runtime_mapping(manifest, runtime_config)


def test_runtime_mapping_drift_is_rejected() -> None:
    manifest = harness.load_manifest(MANIFEST_PATH)
    runtime_config = json.loads(
        Path("config/vehicles.sitl.json").read_text(encoding="utf-8")
    )
    runtime_config["vehicles"][1]["endpoint"] = "udpin:127.0.0.1:14031"

    with pytest.raises(harness.HarnessError, match="shared_config_mismatch"):
        harness.validate_runtime_mapping(manifest, runtime_config)


def test_ned_to_gazebo_conversion_includes_yaw() -> None:
    pose = harness.ned_to_gazebo_pose(
        {"x_m": 12, "y_m": -4, "z_m": -3, "yaw_deg": 0}
    )

    assert pose.x_m == -4
    assert pose.y_m == 12
    assert pose.z_m == 3
    assert pose.yaw_rad == pytest.approx(math.pi / 2)

    east_facing = harness.ned_to_gazebo_pose(
        {"x_m": 0, "y_m": 0, "z_m": 0, "yaw_deg": 90}
    )
    assert east_facing.yaw_rad == pytest.approx(0)


def test_manifest_rejects_implicit_or_duplicate_identity() -> None:
    manifest = _manifest()
    manifest["vehicles"][1]["system_id"] = 1  # type: ignore[index]

    with pytest.raises(harness.HarnessError, match="must be unique: system_id"):
        harness.validate_manifest(manifest, scene=_scene())  # type: ignore[arg-type]


def test_manifest_rejects_endpoint_not_matching_px4_instance() -> None:
    manifest = _manifest()
    manifest["vehicles"][2]["command_endpoint"] = "udpin:127.0.0.1:14549"  # type: ignore[index]
    manifest["vehicles"][2]["telemetry_endpoint"] = "udpin:127.0.0.1:14549"  # type: ignore[index]

    with pytest.raises(harness.HarnessError, match="endpoint port must be 14542"):
        harness.validate_manifest(manifest, scene=_scene())  # type: ignore[arg-type]


def test_manifest_and_scene_spawns_must_match() -> None:
    manifest = _manifest()
    scene = copy.deepcopy(_scene())
    scene["vehicles"][1]["initial_pose"]["y_m"] = 9  # type: ignore[index]

    with pytest.raises(harness.HarnessError, match="spawn differs"):
        harness.validate_manifest(manifest, scene=scene)  # type: ignore[arg-type]


def test_world_contains_aligned_pads_but_no_static_x500() -> None:
    root = ET.parse(WORLD_PATH).getroot()
    names = {
        model.attrib["name"]
        for model in root.findall("./world/model")
    }

    assert {
        "landing-pad-UAV-01",
        "landing-pad-UAV-02",
        "landing-pad-UAV-03",
        "building-001",
        "target-001-marker",
        "nfz-001-marker",
    }.issubset(names)
    assert not any(name.startswith("x500") for name in names)


def test_repeated_start_is_rejected_when_owned_process_identity_is_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = harness.ProcessIdentityDecision(
        code=harness.IDENTITY_MATCH,
        node_id="UAV-01",
        pid=4242,
        signal_allowed=True,
    )
    monkeypatch.setattr(harness, "_validate_processes", lambda *args, **kwargs: [decision])

    with pytest.raises(harness.HarnessError, match="already running"):
        harness._validate_start_state(
            {"run_id": RUN_ID, "processes": [_process_row()]}
        )


RUN_ID = "run-test-001"


def _identity(**overrides: object) -> harness.ProcessIdentity:
    values: dict[str, object] = {
        "pid": 4242,
        "pgid": 4242,
        "proc_start_time_ticks": 123456,
        "executable": "/opt/px4/bin/px4",
        "cmdline": ("/opt/px4/bin/px4", "-i", "1"),
        "cwd": str((harness.RUNTIME_ROOT / "UAV-02").resolve()),
        "run_id": RUN_ID,
    }
    values.update(overrides)
    return harness.ProcessIdentity(**values)


def _observed(**overrides: object) -> harness.ProcessIdentityReadResult:
    return harness.ProcessIdentityReadResult(
        code=harness.IDENTITY_OBSERVED,
        identity=_identity(**overrides),
    )


def _exited() -> harness.ProcessIdentityReadResult:
    return harness.ProcessIdentityReadResult(code=harness.PROCESS_EXITED)


def _process_row(**identity_overrides: object) -> dict[str, object]:
    identity = _identity(**identity_overrides)
    return {
        "kind": "px4",
        "node_id": "UAV-02",
        "pid": identity.pid,
        "pgid": identity.pgid,
        "run_id": RUN_ID,
        "runtime_dir": identity.cwd,
        "process_identity": identity.to_dict(),
    }


def _sequence_reader(
    *results: harness.ProcessIdentityReadResult,
):
    values = iter(results)

    def read(pid: int) -> harness.ProcessIdentityReadResult:
        assert pid == 4242
        return next(values)

    return read


def _write_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    runtime_root = tmp_path / "runtime"
    runtime_dir = runtime_root / "UAV-02"
    runtime_dir.mkdir(parents=True)
    monkeypatch.setattr(harness, "RUNTIME_ROOT", runtime_root)
    state_path = runtime_root / "harness_state.json"
    monkeypatch.setattr(harness, "STATE_PATH", state_path)
    row = _process_row(cwd=str(runtime_dir.resolve()))
    state_path.write_text(
        json.dumps({"version": "1.1", "run_id": RUN_ID, "processes": [row]}),
        encoding="utf-8",
    )
    pid_path = runtime_dir / "px4.pid"
    pid_path.write_text("4242", encoding="ascii")
    return state_path, pid_path


def test_proc_stat_parser_handles_spaces_and_parentheses_in_comm() -> None:
    tail = ["S", *[str(field) for field in range(4, 22)], "123456"]
    stat_text = "4242 (px4 worker (UAV-02)) " + " ".join(tail)

    assert harness._parse_proc_start_time(stat_text) == 123456


def test_process_identity_match_allows_signalling() -> None:
    result = harness.validate_process_identity(
        _process_row(),
        run_id=RUN_ID,
        identity_reader=lambda pid: _observed(pid=pid),
    )

    assert result.signal_allowed is True
    assert result.code == harness.IDENTITY_MATCH


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proc_start_time_ticks", 999999),
        ("executable", "/usr/bin/python"),
        ("cmdline", ("python", "worker.py")),
        ("cwd", "/tmp/not-the-harness"),
        ("run_id", "different-run"),
    ],
)
def test_forged_or_reused_pid_identity_is_rejected_without_signal(
    field: str,
    value: object,
) -> None:
    signals: list[tuple[int, int]] = []
    result = harness._terminate_process_groups(
        [_process_row()],
        run_id=RUN_ID,
        identity_reader=lambda pid: _observed(pid=pid, **{field: value}),
        signal_sender=lambda pgid, sig: signals.append((pgid, sig)),
    )

    assert result[0].code == harness.PROCESS_IDENTITY_MISMATCH
    assert field in result[0].mismatches
    assert signals == []


def test_pgid_mismatch_is_rejected_without_signal() -> None:
    signals: list[tuple[int, int]] = []
    result = harness._terminate_process_groups(
        [_process_row()],
        run_id=RUN_ID,
        identity_reader=lambda pid: _observed(pid=pid, pgid=9000),
        signal_sender=lambda pgid, sig: signals.append((pgid, sig)),
    )

    assert result[0].code == harness.PROCESS_IDENTITY_MISMATCH
    assert result[0].mismatches == ("pgid",)
    assert signals == []


def test_incomplete_legacy_state_is_stale_and_never_signalled() -> None:
    signals: list[tuple[int, int]] = []
    result = harness._terminate_process_groups(
        [{"node_id": "UAV-02", "pid": 4242, "pgid": 4242}],
        run_id=RUN_ID,
        signal_sender=lambda pgid, sig: signals.append((pgid, sig)),
    )

    assert result[0].code == harness.STALE_STATE
    assert signals == []


def test_normal_stop_sends_term_then_cleans_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, pid_path = _write_state(tmp_path, monkeypatch)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        harness,
        "read_process_identity",
        _sequence_reader(_observed(), _exited()),
    )
    monkeypatch.setattr(
        harness.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
        raising=False,
    )

    harness.stop_harness()

    assert signals == [(4242, harness.SIGTERM)]
    assert not state_path.exists()
    assert not pid_path.exists()


def test_repeated_stop_without_state_is_successful(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harness, "RUNTIME_ROOT", tmp_path)
    monkeypatch.setattr(harness, "STATE_PATH", tmp_path / "missing-state.json")
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        harness.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
        raising=False,
    )

    harness.stop_harness()

    assert signals == []


def test_already_exited_process_is_cleaned_without_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, pid_path = _write_state(tmp_path, monkeypatch)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(harness, "read_process_identity", lambda pid: _exited())
    monkeypatch.setattr(
        harness.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
        raising=False,
    )

    harness.stop_harness()

    assert signals == []
    assert not state_path.exists()
    assert not pid_path.exists()


def test_identity_mismatch_preserves_state_and_pid_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, pid_path = _write_state(tmp_path, monkeypatch)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        harness,
        "read_process_identity",
        lambda pid: _observed(pid=pid, proc_start_time_ticks=999999),
    )
    monkeypatch.setattr(
        harness.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
        raising=False,
    )

    with pytest.raises(harness.HarnessError, match="process_identity_mismatch"):
        harness.stop_harness()

    assert signals == []
    assert state_path.exists()
    assert pid_path.exists()


def test_sigterm_timeout_rechecks_identity_then_sends_sigkill() -> None:
    signals: list[tuple[int, int]] = []
    result = harness._terminate_process_groups(
        [_process_row()],
        run_id=RUN_ID,
        term_timeout_s=0,
        kill_timeout_s=0,
        identity_reader=_sequence_reader(
            _observed(),
            _observed(),
            _observed(),
            _exited(),
        ),
        signal_sender=lambda pgid, sig: signals.append((pgid, sig)),
    )

    assert signals == [
        (4242, harness.SIGTERM),
        (4242, harness.SIGKILL),
    ]
    assert result[0].code == harness.PROCESS_EXITED


def test_identity_change_after_sigterm_blocks_sigkill() -> None:
    signals: list[tuple[int, int]] = []
    result = harness._terminate_process_groups(
        [_process_row()],
        run_id=RUN_ID,
        term_timeout_s=0,
        identity_reader=_sequence_reader(
            _observed(),
            _observed(proc_start_time_ticks=999999),
        ),
        signal_sender=lambda pgid, sig: signals.append((pgid, sig)),
    )

    assert signals == [(4242, harness.SIGTERM)]
    assert result[0].code == harness.PROCESS_IDENTITY_MISMATCH


def test_cleanup_evidence_requires_world_exit_and_released_ports() -> None:
    state = {
        "world_name": "simple_recon_v0_1",
        "required_udp_ports": [
            {"host": "127.0.0.1", "port": 14540, "owner": "UAV-01"},
            {"host": "127.0.0.1", "port": 14541, "owner": "UAV-02"},
        ],
    }

    evidence = harness._wait_for_cleanup(
        state,
        timeout_s=0,
        world_probe=lambda: ["simple_recon_v0_1"],
        port_probe=lambda host, port: port == 14540,
    )

    assert evidence["clean"] is False
    assert evidence["world_stopped"] is False
    assert evidence["ports_released"] is False
    assert evidence["ports"][1]["available"] is False


def test_cleanup_incomplete_preserves_state_after_safe_process_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path, pid_path = _write_state(tmp_path, monkeypatch)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        harness,
        "read_process_identity",
        _sequence_reader(_observed(), _exited()),
    )
    monkeypatch.setattr(
        harness.os,
        "killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
        raising=False,
    )
    monkeypatch.setattr(
        harness,
        "_wait_for_cleanup",
        lambda state: {
            "clean": False,
            "world_stopped": False,
            "ports_released": True,
        },
    )

    with pytest.raises(harness.HarnessError, match="cleanup_incomplete"):
        harness.stop_harness()

    assert signals == [(4242, harness.SIGTERM)]
    assert state_path.exists()
    assert pid_path.exists()
