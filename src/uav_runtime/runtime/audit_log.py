"""本地 JSONL 审计写入器。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        resolved = path or os.environ.get(
            "UAV_RUNTIME_AUDIT_PATH", "audit/runtime.audit.jsonl"
        )
        self.path = Path(resolved)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
