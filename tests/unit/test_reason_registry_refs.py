"""decision/reason/error 注册表引用一致性测试。"""
from __future__ import annotations

from uav_runtime.policy.registry_refs import DECISION_REGISTRY_REF, ERROR_REGISTRY_REF, REASON_REGISTRY_REF


def test_registry_refs_prefix() -> None:
    assert DECISION_REGISTRY_REF.startswith("registry://")
    assert REASON_REGISTRY_REF.startswith("registry://")
    assert ERROR_REGISTRY_REF.startswith("registry://")
