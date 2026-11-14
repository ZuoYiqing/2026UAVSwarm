(function attachCoverageGrid(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SwarmCoverageGrid = api;
})(typeof window === "undefined" ? null : window, function coverageGridModule() {
  const finite = Number.isFinite;
  const close = (left, right) => Math.abs(left - right) <= 1e-9;

  function parse(coverage, mission) {
    const grid = coverage?.grid;
    if (grid?.version !== "1.0" || grid.frame !== "scene_ned" || grid.units !== "m"
      || coverage.frame !== grid.frame || !Number.isSafeInteger(coverage.sample_count)
      || coverage.sample_count <= 0) return null;

    for (const field of ["scene_id", "map_version", "area_id"]) {
      if (typeof grid[field] !== "string" || !grid[field] || grid[field] !== coverage[field]
        || (mission[field] != null && mission[field] !== grid[field])) return null;
    }
    const anchor = grid.scene_origin;
    if (anchor?.reference !== "scene_json.origin"
      || !finite(anchor.lat_deg) || Math.abs(anchor.lat_deg) > 90
      || !finite(anchor.lon_deg) || Math.abs(anchor.lon_deg) > 180
      || !finite(anchor.alt_m)) return null;

    const size = grid.cell_size_m;
    const sourceSize = grid.source_cell_size_m;
    const origin = grid.grid_origin_ned_m;
    const fields = grid.cell_fields;
    if (!finite(size) || size < 10 || size > 50
      || !finite(sourceSize) || sourceSize <= 0 || sourceSize > size
      || !finite(origin?.north_m) || !finite(origin?.east_m)
      || !Number.isSafeInteger(grid.rows) || !Number.isSafeInteger(grid.columns)
      || grid.rows <= 0 || grid.columns <= 0 || grid.rows * grid.columns > 25000
      || !Array.isArray(fields) || fields.length !== 3 || fields[0] !== "north_index"
      || fields[1] !== "east_index" || fields[2] !== "covered_source_cells"
      || !Array.isArray(grid.covered_cells) || grid.covered_cells.length > grid.rows * grid.columns) return null;

    if (!Array.isArray(coverage.polygon) || coverage.polygon.length < 3) return null;
    const polygon = [];
    let minNorth = Infinity, maxNorth = -Infinity, minEast = Infinity, maxEast = -Infinity;
    for (const vertex of coverage.polygon) {
      const north = vertex?.north_m;
      const east = vertex?.east_m;
      if (!finite(north) || !finite(east)) return null;
      polygon.push({ north, east });
      minNorth = Math.min(minNorth, north);
      maxNorth = Math.max(maxNorth, north);
      minEast = Math.min(minEast, east);
      maxEast = Math.max(maxEast, east);
    }
    if (!close(minNorth, origin.north_m) || !close(minEast, origin.east_m)
      || Math.ceil((maxNorth - minNorth) / size) !== grid.rows
      || Math.ceil((maxEast - minEast) / size) !== grid.columns) return null;

    const seen = new Set();
    let sourceCount = 0;
    for (const cell of grid.covered_cells) {
      if (!Array.isArray(cell) || cell.length !== 3 || !cell.every(Number.isSafeInteger)) return null;
      const [row, column, count] = cell;
      const index = row * grid.columns + column;
      if (row < 0 || row >= grid.rows || column < 0 || column >= grid.columns
        || count <= 0 || seen.has(index)) return null;
      seen.add(index);
      sourceCount += count;
      if (!Number.isSafeInteger(sourceCount)) return null;
    }
    const coveredArea = coverage.area_covered_km2;
    const cellArea = sourceSize ** 2 / 1e6;
    if (!finite(coveredArea) || coveredArea < 0 || !finite(cellArea) || cellArea <= 0
      || Math.abs(sourceCount * cellArea - coveredArea) > cellArea / 2
      || (mission.area_covered_km2 != null &&
        (!finite(mission.area_covered_km2) || !close(mission.area_covered_km2, coveredArea)))) return null;

    return {
      size, north: origin.north_m, east: origin.east_m, polygon, cells: grid.covered_cells,
      sceneId: grid.scene_id, mapVersion: grid.map_version, areaId: grid.area_id,
    };
  }

  function project(grid, transform) {
    const southwest = transform({ north: grid.north, east: grid.east });
    const northeast = transform({ north: grid.north + grid.size, east: grid.east + grid.size });
    return {
      size: grid.size,
      areaId: grid.areaId,
      southwest,
      cellWidth: northeast.x - southwest.x,
      cellHeight: southwest.y - northeast.y,
      polygon: grid.polygon.map(transform),
      cells: grid.cells,
    };
  }

  function draw(canvas, grid) {
    const ctx = canvas?.getContext?.("2d");
    if (!ctx || !grid) return;
    const x = value => value * canvas.width / 100;
    const y = value => value * canvas.height / 100;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.beginPath();
    for (const [index, point] of grid.polygon.entries()) {
      if (index === 0) ctx.moveTo(x(point.x), y(point.y));
      else ctx.lineTo(x(point.x), y(point.y));
    }
    ctx.closePath();
    ctx.clip();
    ctx.fillStyle = "#208e82";
    const width = x(grid.cellWidth);
    const height = y(grid.cellHeight);
    for (const [row, column] of grid.cells) {
      ctx.fillRect(x(grid.southwest.x) + column * width,
        y(grid.southwest.y) - (row + 1) * height, width, height);
    }
    ctx.restore();
  }

  return { parse, project, draw };
});
