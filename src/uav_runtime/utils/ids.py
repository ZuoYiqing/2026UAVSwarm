from __future__ import annotations


def make_agent_id(index: int) -> str:
    if index <= 0:
        raise ValueError("index must be positive")
    return f"uav-{index}"
