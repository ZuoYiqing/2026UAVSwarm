from __future__ import annotations

import json

from uav_runtime.runtime.audit_log import AuditLog
from uav_runtime.runtime.orchestrator import RuntimeOrchestrator


def test_default_audit_path_honors_pytest_isolation_environment(
    isolate_runtime_audit,
) -> None:
    AuditLog().append({"type": "isolated"})
    RuntimeOrchestrator().audit.append({"type": "orchestrator_isolated"})

    rows = [
        json.loads(line)
        for line in isolate_runtime_audit.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["type"] for row in rows] == [
        "isolated",
        "orchestrator_isolated",
    ]
