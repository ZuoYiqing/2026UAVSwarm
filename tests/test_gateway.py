"""Gateway skeleton tests aligned with current AdapterGateway public API."""
from __future__ import annotations

from uav_runtime.adapters.fake_adapter import FakeAdapter
from uav_runtime.adapters.gateway import AdapterGateway
from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest


def _req(action: str = "hover") -> ActionRequest:
    return ActionRequest(
        action=action,
        params={},
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


def test_execute_with_missing_adapter_returns_rejected_result() -> None:
    gateway = AdapterGateway()

    out = gateway.execute("missing", _req("hover"))

    assert out["accepted"] is False
    assert out["status"] == "rejected"
    assert out["code"] == "adapter_not_found"
    assert out["adapter"] == "missing"
