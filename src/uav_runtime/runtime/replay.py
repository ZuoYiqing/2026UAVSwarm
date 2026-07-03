"""读取最近审计事件的回放存储骨架。"""
from __future__ import annotations

import json
from pathlib import Path


def replay_last(path: str, n: int = 10) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines[-n:]]
