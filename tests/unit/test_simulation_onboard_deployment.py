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
