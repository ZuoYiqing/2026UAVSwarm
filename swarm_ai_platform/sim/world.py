from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np


@dataclass
class Target:
    target_id: int
    x_km: float
    y_km: float
    speed: float
    heading_deg: float
    threat_level: int


class World2D:
    def __init__(
        self,
        area: Dict,
        *,
        grid_res_km: float = 1.0,
        coverage_radius_km: float = 3.0,
        rng_seed: int = 42,
    ) -> None:
        self.x_min = float(area.get("x_min_km", 0))
        self.x_max = float(area.get("x_max_km", 100))
        self.y_min = float(area.get("y_min_km", 0))
        self.y_max = float(area.get("y_max_km", 100))

        self.grid_res_km = float(grid_res_km)
        self.coverage_radius_km = float(coverage_radius_km)
        self.nx = int(max(1, round((self.x_max - self.x_min) / self.grid_res_km)))
        self.ny = int(max(1, round((self.y_max - self.y_min) / self.grid_res_km)))
        self.cover = np.zeros((self.nx, self.ny), dtype=np.int8)

        self._rng = random.Random(rng_seed)
        self.targets: List[Target] = []

    def reset(self) -> None:
        self.cover[:, :] = 0
        self.targets = []

    def add_random_targets(self, n: int = 3) -> None:
        self.targets = []
        for i in range(n):
            x = self._rng.uniform(self.x_min, self.x_max)
            y = self._rng.uniform(self.y_min, self.y_max)
            # Ensure the demo always contains at least one "high" target
            # so the GS response path can be exercised.
            threat = 2 if i == 0 else self._rng.choice([0, 1, 2])
            self.targets.append(
                Target(
                    target_id=100 + i,
                    x_km=x,
                    y_km=y,
                    speed=self._rng.uniform(0, 30),
                    heading_deg=self._rng.uniform(0, 360),
                    threat_level=int(threat),
                )
            )

    def mark_coverage(self, x_km: float, y_km: float) -> None:
        """Mark coverage with a simple sensor footprint.

        To make the demo more meaningful, we mark a small neighborhood around the UAV position,
        approximating a sensor/coverage footprint.
        """
        ix = int((x_km - self.x_min) / self.grid_res_km)
        iy = int((y_km - self.y_min) / self.grid_res_km)
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            return

        r_cells = max(0, int(self.coverage_radius_km / max(1e-6, self.grid_res_km)))
        for dx in range(-r_cells, r_cells + 1):
            for dy in range(-r_cells, r_cells + 1):
                nx = ix + dx
                ny = iy + dy
                if 0 <= nx < self.nx and 0 <= ny < self.ny:
                    self.cover[nx, ny] = 1

    def coverage_ratio(self) -> float:
        return float(self.cover.mean())

    def clamp_position(self, x_km: float, y_km: float) -> Tuple[float, float]:
        x_km = max(self.x_min, min(self.x_max, x_km))
        y_km = max(self.y_min, min(self.y_max, y_km))
        return x_km, y_km
