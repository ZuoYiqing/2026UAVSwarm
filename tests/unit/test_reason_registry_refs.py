"""decision/reason/error 注册表引用一致性测试。"""
from __future__ import annotations

from uav_runtime.policy.registry_refs import DECISION_REGISTRY_REF, ERROR_REGISTRY_REF, REASON_REGISTRY_REF


def test_registry_refs_are_non_empty_and_distinct() -> None:
    refs = [DECISION_REGISTRY_REF, REASON_REGISTRY_REF, ERROR_REGISTRY_REF]
    assert all(isinstance(r, str) and r.strip() for r in refs)
    assert len(set(refs)) == 3


def test_registry_refs_namespace_and_resource_type() -> None:
    assert DECISION_REGISTRY_REF.startswith("registry://decision/")
    assert REASON_REGISTRY_REF.startswith("registry://reason/")
    assert ERROR_REGISTRY_REF.startswith("registry://error/")
