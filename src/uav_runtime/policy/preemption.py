"""优先级表与抢占规则容器。"""
from __future__ import annotations

from dataclasses import dataclass


PRIORITY_LEVELS: dict[str, int] = {
    "ground_station": 100,
    "higher_command": 95,
    "cluster_head": 80,
    "delegated_peer": 60,
    "self_local": 50,
}


@dataclass(slots=True)
class PreemptionRule:
    allow_preempt: bool
    non_preemptible_phases: tuple[str, ...] = ()
