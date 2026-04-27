"""FakeAdapter command-driven execution semantics contract tests."""
from __future__ import annotations

from uav_runtime.adapters.fake_adapter import FakeAdapter


def test_fake_adapter_success_default() -> None:
    out = FakeAdapter().execute({"command": "hover", "arguments": {}, "meta": {}})
    assert out["accepted"] is True
    assert out["code"] == "exec_ok"
    assert out["detail"] == "simulated"


def test_fake_adapter_deterministic_failure() -> None:
    out = FakeAdapter().execute(
        {"command": "hover", "arguments": {}, "meta": {}, "_simulate": {"fail": True}}
    )
    assert out["accepted"] is False
    assert out["code"] == "exec_failed"
    assert out["message"] == "simulated failure"


def test_fake_adapter_timeout_semantics() -> None:
    out = FakeAdapter().execute(
        {"command": "hover", "arguments": {}, "meta": {}, "_simulate": {"timeout": True}}
    )
    assert out["accepted"] is False
    assert out["code"] == "exec_timeout"
    assert out["message"] == "simulated timeout"


def test_fake_adapter_delay_calls_sleep(monkeypatch) -> None:
    called = {"seconds": None}

    def _fake_sleep(seconds: float) -> None:
        called["seconds"] = seconds

    monkeypatch.setattr("uav_runtime.adapters.fake_adapter.time.sleep", _fake_sleep)
    out = FakeAdapter().execute(
        {"command": "hover", "arguments": {}, "meta": {}, "_simulate": {"delay_ms": 7}}
    )

    assert called["seconds"] == 0.007
    assert out["accepted"] is True
    assert out["execution_trace"]["delay_ms"] == 7
