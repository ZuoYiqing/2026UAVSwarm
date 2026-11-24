"""Estimate horizontal area covered by observed footprints in scene NED."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

MAX_GRID_CELLS = 1_000_000
MIN_DISPLAY_CELL_SIZE_M = 10
MAX_DISPLAY_CELL_SIZE_M = 50
MAX_DISPLAY_GRID_CELLS = 25_000
Point = tuple[float, float]


def _finite(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("coverage coordinates and dimensions must be finite numbers")
    return float(value)


def _cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, p: Point) -> bool:
    return _cross(a, b, p) == 0 and all(
        min(start, end) <= value <= max(start, end)
        for start, end, value in zip(a, b, p)
    )


def _intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    ab_c, ab_d = _cross(a, b, c), _cross(a, b, d)
    cd_a, cd_b = _cross(c, d, a), _cross(c, d, b)
    return (
        (ab_c * ab_d < 0 and cd_a * cd_b < 0)
        or _on_segment(a, b, c) or _on_segment(a, b, d)
        or _on_segment(c, d, a) or _on_segment(c, d, b)
    )


def _inside(point: Point, edges: Sequence[tuple[Point, Point]]) -> bool:
    north, east = point
    inside = False
    for a, b in edges:
        if _on_segment(a, b, point):
            return True
        if ((a[1] > east) != (b[1] > east)
                and north < a[0] + (b[0] - a[0]) * (east - a[1]) / (b[1] - a[1])):
            inside = not inside
    return inside


class AreaCoverage:
    """Accumulate a union of footprints over a fixed grid for one mission.

    Callers supply calibrated scene NED observations from their existing owner.
    Use a separate accumulator for each mission and serialize calls to it.
    """

    def __init__(
        self,
        scene: dict[str, Any],
        area_id: str,
        *,
        footprint_radius_m: float,
    ) -> None:
        areas = [area for area in scene.get("coverage_areas", []) if area["area_id"] == area_id]
        if len(areas) != 1 or areas[0].get("frame") != "scene_ned":
            raise ValueError(f"coverage area {area_id!r} must uniquely identify a scene_ned polygon")
        area = areas[0]
        self.scene_id = scene["scene_id"]
        self.map_version = scene["map_version"]
        self.area_id = area_id
        self.cell_size_m = _finite(area["cell_size_m"])
        self.footprint_radius_m = _finite(footprint_radius_m)
        if self.cell_size_m <= 0 or self.footprint_radius_m <= 0:
            raise ValueError("coverage cell size and footprint radius must be positive")

        vertices = [(_finite(p["north_m"]), _finite(p["east_m"])) for p in area["polygon"]]
        if len(vertices) < 3 or len(set(vertices)) != len(vertices):
            raise ValueError("coverage polygon requires distinct vertices")
        edges = list(zip(vertices, vertices[1:] + vertices[:1]))
        for i, (a, b) in enumerate(edges):
            for j in range(i + 2, len(edges)):
                if i == 0 and j == len(edges) - 1:
                    continue
                if _intersects(a, b, *edges[j]):
                    raise ValueError("coverage polygon intersects itself")
        if math.fsum(_cross(vertices[0], a, b) for a, b in edges) == 0:
            raise ValueError("coverage polygon has zero area")

        north, east = zip(*vertices)
        self._north0, self._east0 = min(north), min(east)
        self._north_span = max(north) - self._north0
        self._east_span = max(east) - self._east0
        origin = scene.get("origin")
        self._scene_origin = (
            {key: origin.get(key) for key in ("lat_deg", "lon_deg", "alt_m")}
            if isinstance(origin, dict) else {}
        )
        self._rows = math.ceil(self._north_span / self.cell_size_m)
        self._columns = math.ceil(self._east_span / self.cell_size_m)
        if self._rows * self._columns > MAX_GRID_CELLS:
            raise ValueError("coverage grid exceeds maximum cell count")
        self._area = {
            (row, col)
            for row in range(self._rows)
            for col in range(self._columns)
            if _inside(self._center(row, col), edges)
        }
        if not self._area:
            raise ValueError("coverage polygon has no grid cell centers")
        self._covered: set[tuple[int, int]] = set()
        self._samples = 0
        self._display_cache: tuple[float, int, list[tuple[int, int, int]]] | None = None

    def _center(self, row: int, col: int) -> Point:
        return (
            self._north0 + (row + 0.5) * self.cell_size_m,
            self._east0 + (col + 0.5) * self.cell_size_m,
        )

    def observe(self, *, north_m: float, east_m: float) -> None:
        """Credit cells whose centers lie within a horizontal footprint."""
        north, east = _finite(north_m), _finite(east_m)
        radius, cell = self.footprint_radius_m, self.cell_size_m
        row0 = max(0, math.floor((north - radius - self._north0) / cell))
        row1 = min(self._rows, math.floor((north + radius - self._north0) / cell) + 1)
        col0 = max(0, math.floor((east - radius - self._east0) / cell))
        col1 = min(self._columns, math.floor((east + radius - self._east0) / cell) + 1)
        for row in range(row0, row1):
            for col in range(col0, col1):
                if (row, col) in self._area and math.dist((north, east), self._center(row, col)) <= radius:
                    self._covered.add((row, col))
        self._samples += 1

    def _display_grid(self, cell_size_m: float) -> dict[str, Any] | None:
        cell_size_m = _finite(cell_size_m)
        if not MIN_DISPLAY_CELL_SIZE_M <= cell_size_m <= MAX_DISPLAY_CELL_SIZE_M:
            raise ValueError("display grid cell size must be between 10 and 50 m")
        if self._samples == 0 or cell_size_m < self.cell_size_m:
            return None
        try:
            lat, lon, alt = (_finite(self._scene_origin.get(key)) for key in ("lat_deg", "lon_deg", "alt_m"))
        except ValueError:
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None

        rows = math.ceil(self._north_span / cell_size_m)
        columns = math.ceil(self._east_span / cell_size_m)
        if rows * columns > MAX_DISPLAY_GRID_CELLS:
            return None

        covered_count = len(self._covered)
        cache = self._display_cache
        if cache is None or cache[:2] != (cell_size_m, covered_count):
            counts: dict[tuple[int, int], int] = {}
            for row, col in self._covered:
                # Assign source centers on the outer edge to the last cell.
                coarse_row = min(rows - 1, int((row + 0.5) * self.cell_size_m / cell_size_m))
                coarse_col = min(columns - 1, int((col + 0.5) * self.cell_size_m / cell_size_m))
                key = (coarse_row, coarse_col)
                counts[key] = counts.get(key, 0) + 1
            cells = [(row, col, count) for (row, col), count in sorted(counts.items())]
            self._display_cache = (cell_size_m, covered_count, cells)
        else:
            cells = cache[2]
        return {
            "version": "1.0",
            "frame": "scene_ned",
            "units": "m",
            "scene_id": self.scene_id,
            "map_version": self.map_version,
            "area_id": self.area_id,
            "scene_origin": {"reference": "scene_json.origin", "lat_deg": lat, "lon_deg": lon, "alt_m": alt},
            "grid_origin_ned_m": {"north_m": self._north0, "east_m": self._east0},
            "cell_size_m": cell_size_m,
            "rows": rows,
            "columns": columns,
            "source_cell_size_m": self.cell_size_m,
            "cell_fields": ["north_index", "east_index", "covered_source_cells"],
            "covered_cells": [list(cell) for cell in cells],
        }

    def report(self, *, grid_cell_size_m: float | None = None) -> dict[str, Any]:
        """Return area metrics and, when requested, a sparse display grid."""
        cell_km2 = self.cell_size_m ** 2 / 1_000_000
        result = {
            "method": "scene_ned_grid_cell_center_v1",
            "scene_id": self.scene_id,
            "map_version": self.map_version,
            "area_id": self.area_id,
            "frame": "scene_ned",
            "cell_size_m": self.cell_size_m,
            "footprint_radius_m": self.footprint_radius_m,
            "sample_count": self._samples,
            "area_total_km2": len(self._area) * cell_km2,
            "area_covered_km2": len(self._covered) * cell_km2,
            "completion_pct": 100 * len(self._covered) / len(self._area),
        }
        if grid_cell_size_m is not None:
            result["grid"] = self._display_grid(grid_cell_size_m)
        return result
