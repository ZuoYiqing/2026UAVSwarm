"""Fail-closed task completion while pad evidence has no trusted producer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import uav_runtime.http.routes as routes
from tests.unit.test_runtime_action_lifecycle import action_body, install_registry, successful_land


FIXTURE = Path(__file__).resolve().parents[2] / "docs" / "fixtures" / "runtime_landing_site_candidate_v1.json"


def test_return_home_does_not_enter_rtl_without_validated_site(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    registry, store = install_registry(monkeypatch)
    monkeypatch.setattr(routes, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))

    status, result = routes.dispatch("POST", "/api/actions/return-home",
                                     body=action_body("UAV-01", key="return-without-site"))

    assert status == 200
    assert result["status"] == "failed"
    assert result["failure_reason"] == "landing_site_unavailable"
    assert registry.get_vehicle("UAV-01").session.calls == []
    assert store.runtime_snapshot()["active_actions"] == []


def test_operator_land_sends_command_but_cannot_claim_pad_without_site(
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
    assert result["failure_reason"] == "landing_site_unavailable"
    assert store.runtime_snapshot()["active_actions"] == []


def test_self_reported_validation_cannot_make_landing_site_authoritative() -> None:
    from uav_runtime.http.state_store import RuntimeStateStore

    store = RuntimeStateStore()
    evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert store.update_landing_site_evidence(evidence)["status"] == "candidate"
    assert store.landing_site("UAV-01")[1] == "candidate"
    evidence["status"] = "validated"
    evidence["validation"] = {"real_landing": True, "run_id": "claimed-run"}

    with pytest.raises(ValueError, match="trusted_landing_site_producer_unavailable"):
        store.update_landing_site_evidence(evidence)
    assert store.landing_site("UAV-01")[1] == "candidate"
