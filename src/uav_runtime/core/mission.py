from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Mission:
    name: str
    goals: list[str]

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("mission name cannot be empty")
        if not self.goals:
            raise ValueError("mission requires at least one goal")
