"""最小 runtime 集成链路测试骨架。"""
from __future__ import annotations

from uav_runtime.protocol.enums import AuthorityScope, CommandSource
from uav_runtime.protocol.schema import ActionRequest
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator


def test_minimal_runtime_flow(tmp_path) -> None:
    audit = tmp_path / "runtime.audit.jsonl"
    rt = RuntimeOrchestrator(str(audit))
    req = ActionRequest("hover", {"duration_s": 3}, CommandSource.SELF_LOCAL, AuthorityScope.SELF_ONLY)
    res = rt.handle_action_request(req)
    assert res["accepted"] is True
    assert audit.exists()
