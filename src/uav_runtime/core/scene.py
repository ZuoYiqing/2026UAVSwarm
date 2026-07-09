from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Scene:
    area: tuple[int, int]
    agents: int
    obstacles: list[tuple[int, int]]

    def validate(self) -> None:
        w, h = self.area
        if w <= 0 or h <= 0:
            raise ValueError("scene area must be positive")
        if self.agents <= 0:
            raise ValueError("scene agents must be positive")
