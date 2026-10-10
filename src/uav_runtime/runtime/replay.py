"""读取最近审计事件的回放存储骨架。"""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Callable


def replay_last(path: str, n: int = 10) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines[-n:]]


def replay_recent_unique_actions(
    path: str, n: int, *, is_action_result: Callable[[dict], bool]
) -> list[dict]:
    """Read the last distinct actions without counting audit stages as extra actions."""
    if n <= 0:
        return []
    source = Path(path)
    if not source.exists():
        return []
    actions: OrderedDict[str, dict] = OrderedDict()
    with source.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if not line.strip():
                continue
            event = json.loads(line)
            if not is_action_result(event):
                continue
            key = str(event.get("action_id") or f"legacy:{index}")
            previous = actions.get(key)
            if previous is not None and previous.get("type") == "action_result" and event.get("type") != "action_result":
                continue
            actions.pop(key, None)
            actions[key] = event
    return list(actions.values())[-n:]
