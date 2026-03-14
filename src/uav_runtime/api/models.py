from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PlanRequest:
    mission_name: str
    goals: list[str]
    area: tuple[int, int]
    agents: int


@dataclass(slots=True)
class SimRequest:
    mission_name: str
    goals: list[str]
    area: tuple[int, int]
    agents: int
    steps: int = 20
