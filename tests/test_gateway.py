"""Gateway skeleton tests aligned with current AdapterGateway public API."""
from __future__ import annotations

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest


def _req(action: str = "hover", params: dict | None = None) -> ActionRequest:
    return ActionRequest(
        action=action,
        params=params or {},
        source=CommandSource.SELF_LOCAL,
        scope=AuthorityScope.SELF_ONLY,
    )


def test_execute_with_registered_fake_adapter_succeeds() -> None:
    gateway = AdapterGateway()
    gateway.register(FakeAdapter())

    out = gateway.execute("fake", _req("hover"))

    assert out["accepted"] is True
    assert out["status"] == "accepted"
    assert out["adapter"] == "fake"
    assert out["code"] == "exec_ok"


def test_execute_with_missing_adapter_returns_rejected_result() -> None:
    gateway = AdapterGateway()

    out = gateway.execute("missing", _req("hover"))

    assert out["accepted"] is False
    assert out["status"] == "rejected"
    assert out["code"] == "adapter_not_found"
    assert out["adapter"] == "missing"


def test_execute_with_simulated_failure_returns_deterministic_failure() -> None:
    gateway = AdapterGateway()
    gateway.register(FakeAdapter())

    out = gateway.execute("fake", _req("hover", params={"__simulate_fail": True}))

    assert out["accepted"] is False
    assert out["status"] == "rejected"
    assert out["code"] == "exec_failed"
    assert out["message"] == "simulated failure"


def test_execute_with_simulated_timeout_returns_timeout_failure() -> None:
    gateway = AdapterGateway()
    gateway.register(FakeAdapter())

    out = gateway.execute("fake", _req("hover", params={"__simulate_timeout": True}))

    assert out["accepted"] is False
    assert out["status"] == "rejected"
    assert out["code"] == "exec_timeout"
    assert out["message"] == "simulated timeout"


def test_px4_adapter_exception_is_never_reported_as_success() -> None:
    class RaisingAdapter:
        name = "mavlink"
        def execute(self, command: dict) -> dict:
            raise RuntimeError("private backend detail")

    gateway = AdapterGateway()
    gateway.register(RaisingAdapter())
    out = gateway.execute("mavlink", _req("land"))
    assert out["accepted"] is False
    assert out["status"] != "accepted"
    assert out["code"] == "adapter_execution_exception"
    assert out["detail"] == "adapter_execution_exception"
    assert out["error_class"] == "RuntimeError"
    assert "private backend detail" not in str(out)
