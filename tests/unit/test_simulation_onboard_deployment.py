"""Deployment guards never signal a SITL Agent without landed evidence."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SIM_DIR = Path("simulation/px4_gazebo").resolve()
sys.path.insert(0, str(SIM_DIR))

import onboard_deployment  # noqa: E402


def test_agent_cli_passes_simulation_run_id_and_runtime_config(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    command = onboard_deployment._agent_command(token_file, "simulation-run-123")
    assert command[command.index("--run-id") + 1] == "simulation-run-123"
    assert command[command.index("--execution-mode") + 1] == "fake"
    assert command[command.index("--vehicle-config") + 1] == str(
        onboard_deployment.RUNTIME_VEHICLE_CONFIG.resolve()
    )
    sitl = onboard_deployment._agent_command(token_file, "simulation-run-123", "sitl")
    assert sitl[sitl.index("--execution-mode") + 1] == "sitl"
    assert sitl[sitl.index("--run-id") + 1] == "simulation-run-123"
    assert "--candidate-url" not in sitl
    with_model = onboard_deployment._agent_command(
        token_file, "simulation-run-123", "sitl", "http://127.0.0.1:8872/candidate")
    assert with_model[with_model.index("--candidate-url") + 1] == "http://127.0.0.1:8872/candidate"


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8872/candidate", "http://localhost:8872/candidate",
    "http://example.org:8872/candidate", "http://user:pass@127.0.0.1:8872/candidate",
    "http://127.0.0.1:8872/candidate?token=secret", "http://127.0.0.1:8872/candidate#frag",
    "http://127.0.0.1/candidate", "http://127.0.0.1:0/candidate",
    "http://127.0.0.1:8872/candidate\n",
])
def test_candidate_url_rejects_non_loopback_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(onboard_deployment.DeploymentError,
                       match="candidate_url_requires_explicit_loopback"):
        onboard_deployment._agent_command(Path("token"), "run", "sitl", url)
    with pytest.raises(onboard_deployment.DeploymentError, match="candidate_url_requires_sitl"):
        onboard_deployment._agent_command(Path("token"), "run", "fake",
                                           "http://127.0.0.1:8872/candidate")


@pytest.mark.parametrize("token", ["short", "a" * 31, "a" * 31 + " b"])
def test_token_preflight_matches_runtime_contract(tmp_path: Path, token: str) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(token, encoding="utf-8")
    with pytest.raises(onboard_deployment.DeploymentError,
                       match="platform_token_file_missing_or_invalid"):
        onboard_deployment._validate_token_file(token_file)
    token_file.write_text("a" * 32 + "\n", encoding="utf-8")
    onboard_deployment._validate_token_file(token_file)


def test_start_requires_managed_simulation_before_any_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("test-only", encoding="utf-8")
    monkeypatch.setattr(onboard_deployment.harness, "read_state", lambda: None)
    monkeypatch.setattr(onboard_deployment, "_spawn", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(onboard_deployment.DeploymentError, match="managed_simulation_run_missing"):
        onboard_deployment.start_fake(token_file=token_file, state_path=tmp_path / "deployment.json")
    with pytest.raises(onboard_deployment.DeploymentError, match="managed_simulation_run_missing"):
        onboard_deployment.start_sitl(token_file=token_file, state_path=tmp_path / "deployment.json")


def test_sitl_start_uses_managed_run_without_flight_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("a" * 32, encoding="utf-8")
    runtime_module = tmp_path / "src/uav_runtime/platform/server.py"
    runtime_module.parent.mkdir(parents=True)
    runtime_module.write_text("", encoding="utf-8")
    monkeypatch.setattr(onboard_deployment.harness, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(onboard_deployment, "_managed_harness",
                        lambda: ({"run_id": "managed-run"}, {}))
    monkeypatch.setattr(onboard_deployment, "_available_tcp", lambda port: True)
    monkeypatch.setattr(onboard_deployment.app_link_proxy, "set_state", lambda *a, **k: None)
    monkeypatch.setattr(onboard_deployment, "_wait_for_ports", lambda *a, **k: None)
    monkeypatch.setattr(onboard_deployment, "inspect", lambda path: {"status": "process_ready"})
    commands: list[list[str]] = []

    def spawn(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(pid=5000 + len(commands), poll=lambda: None)

    monkeypatch.setattr(onboard_deployment, "_spawn", spawn)
    monkeypatch.setattr(onboard_deployment, "_entry",
                        lambda kind, process, runtime_dir, run_id: {"kind": kind, "node_id": f"UAV-02-{kind}"})
    state_path = tmp_path / "deployment.json"
    assert onboard_deployment.start_sitl(token_file=token_file,
        candidate_url="http://127.0.0.1:8872/candidate", state_path=state_path)["status"] == "process_ready"
    assert commands[0][commands[0].index("--execution-mode") + 1] == "sitl"
    assert commands[0][commands[0].index("--run-id") + 1] == "managed-run"
    assert commands[0][commands[0].index("--candidate-url") + 1] == "http://127.0.0.1:8872/candidate"
    assert len(commands) == 2
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["execution_mode"] == "sitl"
    assert state["candidate_url"] == "http://127.0.0.1:8872/candidate"


def test_sitl_start_failure_preserves_identity_without_signalling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("a" * 32, encoding="utf-8")
    runtime_module = tmp_path / "src/uav_runtime/platform/server.py"
    runtime_module.parent.mkdir(parents=True)
    runtime_module.write_text("", encoding="utf-8")
    monkeypatch.setattr(onboard_deployment.harness, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(onboard_deployment, "_managed_harness", lambda: ({"run_id": "managed-run"}, {}))
    monkeypatch.setattr(onboard_deployment, "_available_tcp", lambda port: True)
    monkeypatch.setattr(onboard_deployment.app_link_proxy, "set_state", lambda *a, **k: None)
    counter = iter((5001, 5002))
    monkeypatch.setattr(onboard_deployment, "_spawn",
                        lambda *a, **k: SimpleNamespace(pid=next(counter), poll=lambda: None))
    monkeypatch.setattr(onboard_deployment, "_entry",
                        lambda kind, process, runtime_dir, run_id: {"kind": kind, "node_id": f"UAV-02-{kind}"})
    monkeypatch.setattr(onboard_deployment, "_wait_for_ports",
                        lambda *a, **k: (_ for _ in ()).throw(onboard_deployment.DeploymentError("port_not_ready")))
    monkeypatch.setattr(onboard_deployment.harness, "_terminate_process_groups",
                        lambda *a, **k: pytest.fail("startup failure must not signal SITL"))
    state_path = tmp_path / "deployment.json"
    with pytest.raises(onboard_deployment.DeploymentError, match="sitl_startup_failed_manual_intervention"):
        onboard_deployment.start_sitl(token_file=token_file, state_path=state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["execution_mode"] == "sitl"
    assert len(state["processes"]) == 2


def test_sitl_stop_refuses_without_fresh_landed_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "deployment.json"
    state_path.write_text(json.dumps({"execution_mode": "sitl", "run_id": "test-run",
                                      "processes": []}), encoding="utf-8")
    monkeypatch.setattr(onboard_deployment.harness, "_terminate_process_groups",
                        lambda *a, **k: pytest.fail("must not signal"))
    with pytest.raises(onboard_deployment.DeploymentError,
                       match="sitl_stop_requires_fresh_landed_disarmed_evidence"):
        onboard_deployment.stop_fake(state_path)


def test_fake_stop_is_identity_checked_and_repeatable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "deployment.json"
    state_path.write_text(json.dumps({"execution_mode": "fake", "run_id": "test-run",
                                      "processes": [{"node_id": "UAV-02-agent"}]}), encoding="utf-8")
    calls: list[str] = []

    def fake_terminate(processes, *, run_id):
        calls.append(run_id)
        return [SimpleNamespace(code=onboard_deployment.harness.PROCESS_EXITED)]

    monkeypatch.setattr(onboard_deployment.harness, "_terminate_process_groups", fake_terminate)
    assert onboard_deployment.stop_fake(state_path)["status"] == "stopped"
    assert calls == ["test-run"]
    assert onboard_deployment.stop_fake(state_path) == {"status": "stopped", "idempotent": True}


def test_fake_stop_refuses_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "deployment.json"
    state_path.write_text(json.dumps({"execution_mode": "fake", "run_id": "test-run",
                                      "processes": [{"node_id": "UAV-02-agent"}]}), encoding="utf-8")
    monkeypatch.setattr(onboard_deployment.harness, "_terminate_process_groups",
                        lambda *a, **k: [SimpleNamespace(code="process_identity_mismatch")])
    with pytest.raises(onboard_deployment.DeploymentError,
                       match="stop_refused_process_identity_or_exit_failure"):
        onboard_deployment.stop_fake(state_path)
    assert state_path.is_file()


@pytest.mark.parametrize("bad_field", ["safe_to_stop", "active_task", "ground_link", "armed", "sample_timestamp"])
def test_sitl_stop_requires_quiesced_link_and_fresh_landed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_field: str,
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("a" * 32, encoding="utf-8")
    run_id = "test-run"
    link_path = onboard_deployment.PROXY_DIR / f"link_state.{run_id}.json"
    state = {"execution_mode": "sitl", "run_id": run_id,
             "token_file": str(token_file), "link_state_path": str(link_path),
             "processes": [{"node_id": "UAV-02-agent", "kind": "agent"},
                           {"node_id": "UAV-02-link", "kind": "link"}]}
    state_path = tmp_path / "deployment.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(onboard_deployment.harness, "read_state", lambda: {"run_id": run_id})
    monkeypatch.setattr(onboard_deployment.harness, "_validate_processes",
                        lambda *a, **k: [SimpleNamespace(code=onboard_deployment.harness.IDENTITY_MATCH)] * 2)
    events: list[str] = []
    monkeypatch.setattr(onboard_deployment.app_link_proxy, "set_state",
                        lambda *a, **k: events.append("link_down"))
    observation = {"source": "px4_telemetry", "sample_timestamp": onboard_deployment.harness.utc_now(),
                   "stale": False, "landed_fresh": True, "armed": False, "landed_state": 1}
    status = {"contract_version": "1.0", "node_id": "UAV-02", "run_id": run_id,
              "execution_mode": "sitl", "ground_link": {"state": "lost"},
              "active_task": None, "platform_observation": observation, "safe_to_stop": True}
    if bad_field == "safe_to_stop":
        status[bad_field] = False
    elif bad_field == "active_task":
        status[bad_field] = {"task_id": "busy"}
    elif bad_field == "ground_link":
        status[bad_field] = {"state": "healthy"}
    elif bad_field == "armed":
        observation[bad_field] = True
    else:
        observation[bad_field] = "2020-01-01T00:00:00Z"
    monkeypatch.setattr(onboard_deployment, "_read_agent_status",
                        lambda token: (events.append("status") or (200, status)))
    monkeypatch.setattr(onboard_deployment.harness, "_terminate_process_groups",
                        lambda *a, **k: pytest.fail("unsafe SITL stop sent a signal"))
    with pytest.raises(onboard_deployment.DeploymentError,
                       match="sitl_stop_requires_fresh_landed_disarmed_evidence"):
        onboard_deployment.stop_sitl(state_path, sleep=lambda seconds: events.append("lease_wait"))
    assert events == ["link_down", "lease_wait", "status"]
    assert state_path.is_file()


def test_sitl_stop_signals_only_after_quiescence_and_fresh_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "test-run"
    token_file = tmp_path / "token"
    token_file.write_text("a" * 32, encoding="utf-8")
    state_path = tmp_path / "deployment.json"
    state_path.write_text(json.dumps({
        "execution_mode": "sitl", "run_id": run_id,
        "token_file": str(token_file),
        "link_state_path": str(onboard_deployment.PROXY_DIR / f"link_state.{run_id}.json"),
        "processes": [{"node_id": "UAV-02-agent", "kind": "agent"},
                      {"node_id": "UAV-02-link", "kind": "link"}],
    }), encoding="utf-8")
    monkeypatch.setattr(onboard_deployment.harness, "read_state", lambda: {"run_id": run_id})
    monkeypatch.setattr(onboard_deployment.harness, "_validate_processes",
                        lambda *a, **k: [SimpleNamespace(code=onboard_deployment.harness.IDENTITY_MATCH)] * 2)
    events: list[str] = []
    monkeypatch.setattr(onboard_deployment.app_link_proxy, "set_state",
                        lambda *a, **k: events.append("link_down"))
    status = {"contract_version": "1.0", "node_id": "UAV-02", "run_id": run_id,
              "execution_mode": "sitl", "ground_link": {"state": "lost"},
              "active_task": None, "safe_to_stop": True,
              "platform_observation": {"source": "px4_telemetry", "stale": False,
                                       "landed_fresh": True, "armed": False, "landed_state": 1,
                                       "sample_timestamp": onboard_deployment.harness.utc_now()}}
    monkeypatch.setattr(onboard_deployment, "_read_agent_status",
                        lambda token: (events.append("status") or (200, status)))

    def terminate(processes, *, run_id):
        events.append("terminate")
        return [SimpleNamespace(code=onboard_deployment.harness.PROCESS_EXITED)] * 2

    monkeypatch.setattr(onboard_deployment.harness, "_terminate_process_groups", terminate)
    result = onboard_deployment.stop_sitl(state_path, sleep=lambda seconds: events.append("lease_wait"))
    assert result == {"status": "stopped", "idempotent": False, "run_id": run_id}
    assert events == ["link_down", "lease_wait", "status", "terminate"]
    assert not state_path.exists()
    assert onboard_deployment.stop_sitl(state_path) == {"status": "stopped", "idempotent": True}
