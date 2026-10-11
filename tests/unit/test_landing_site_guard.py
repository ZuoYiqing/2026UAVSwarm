"""Ordinary actions do not require a validated named landing pad."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import uav_runtime.http.routes as routes
from tests.unit.test_runtime_action_lifecycle import action_body, install_registry, successful_land


FIXTURE = Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "runtime_landing_site_candidate_v1.json"


def test_return_home_checks_actual_home_without_validated_site(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))

    def home_unverified(backend, **kwargs):
        backend.session.calls.append("return_home")
        assert "landing_site_id" not in kwargs
        return {"result": "fail", "failure_reason": "home_position_unverified",
                "completion_state": "unknown", "autonomous_execution_may_continue": False}

    monkeypatch.setattr(routes.Px4SitlBackend, "execute_return_home_action", home_unverified)

    status, result = routes.dispatch("POST", "/api/actions/return-home",
                                     body=action_body("UAV-01", key="return-without-site"))

    assert status == 200
    assert result["status"] == "failed"
    assert result["failure_reason"] == "home_position_unverified"
    assert result["execution_admitted"] is True
    assert registry.get_vehicle("UAV-01").session.calls == ["return_home"]
    assert store.runtime_snapshot()["active_actions"] == []


def test_operator_land_sends_command_but_cannot_claim_ground_without_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(routes.Px4SitlBackend, "execute_land_action", successful_land)

    status, result = routes.dispatch("POST", "/api/actions/land",
                                     body=action_body("UAV-01", key="land-without-site"))

    assert status == 200
    assert registry.get_vehicle("UAV-01").session.calls == ["land"]
    assert result["status"] == "failed"
    assert result["failure_reason"] == "ground_reference_unavailable"
    assert store.runtime_snapshot()["active_actions"] == []


def test_self_reported_validation_cannot_make_landing_site_authoritative() -> None:
    from uav_runtime.http.state_store import RuntimeStateStore

    now = [100.0]
    store = RuntimeStateStore(monotonic=lambda: now[0])
    evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "valid_for_ms" not in evidence
    assert store.update_landing_site_evidence(evidence)["status"] == "candidate"
    assert store.landing_site("UAV-01")[1] == "candidate"
    now[0] += 365 * 24 * 60 * 60
    assert store.landing_site("UAV-01")[1] == "candidate"
    with pytest.raises(ValueError, match="landing_site_ttl_not_supported"):
        store.update_landing_site_evidence({**evidence, "valid_for_ms": 60000})
    evidence["status"] = "validated"
    evidence["validation"] = {"real_landing": True, "run_id": "claimed-run"}

    with pytest.raises(ValueError, match="trusted_landing_site_producer_unavailable"):
        store.update_landing_site_evidence(evidence)
    assert store.landing_site("UAV-01")[1] == "candidate"
