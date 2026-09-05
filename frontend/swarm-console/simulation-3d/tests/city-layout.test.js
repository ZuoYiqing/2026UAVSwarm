import test from "node:test";
import assert from "node:assert/strict";
import {
  CITY,
  CITY_VIEWS,
  bridgeDeckHeight,
  createCityLayout,
  createInterchangeRamp,
  riverNorth,
  terrainHeight,
} from "../src/city-layout.js";
import { buildCityGeometry } from "../src/city-geometry.js";

test("city layout is deterministic and preserves the mission footprint and river", () => {
  const layout = createCityLayout();
  assert.deepEqual(layout, createCityLayout());
  assert.ok(layout.buildings.length > 200);
  for (const b of layout.buildings) {
    const outsideCampus =
      Math.abs(b.x) - b.width / 2 > 210 || Math.abs(b.y) - b.depth / 2 > 155;
    assert.ok(outsideCampus, `${b.id} intersects the mission footprint`);
    assert.ok(
      Math.abs(b.y - riverNorth(b.x)) > b.depth / 2 + 74,
      `${b.id} intersects water`,
    );
    assert.ok(terrainHeight(b.x, b.y) < 10, `${b.id} intersects hills`);
  }
  assert.ok(terrainHeight(0, 0) === 0);
  assert.ok(terrainHeight(-1100, 880) > 200);
});

test("all named views stay inside the city and retain the campus origin", () => {
  assert.deepEqual(CITY_VIEWS.campus.target, [0, 0, 0]);
  for (const view of Object.values(CITY_VIEWS)) {
    assert.ok(
      view.target[0] >= CITY.bounds[0] && view.target[0] <= CITY.bounds[2],
    );
    assert.ok(
      view.target[1] >= CITY.bounds[1] && view.target[1] <= CITY.bounds[3],
    );
    assert.ok(view.range > 0 && view.pitch < 0);
  }
});

test("render geometry has finite positions, valid indices and bounded batching", () => {
  const { geometries, stats } = buildCityGeometry();
  assert.ok(stats.trees > 1000);
  assert.ok(geometries.length < 60);
  assert.deepEqual(
    new Set(geometries.map((b) => b.layer)),
    new Set(["terrain", "transport", "vegetation", "buildings"]),
  );
  for (const { geometry } of geometries) {
    const positions = geometry.attributes.position;
    assert.ok(positions.count > 0);
    assert.equal(geometry.attributes.normal.count, positions.count);
    assert.ok(positions.array.every(Number.isFinite));
    assert.ok(geometry.attributes.normal.array.every(Number.isFinite));
    assert.ok(geometry.index.array.every((i) => i < positions.count));
    geometry.dispose();
  }
});

test("both interchange ramps meet the expressway and bridge at matching elevations", () => {
  for (const side of [-1, 1]) {
    const ramp = createInterchangeRamp(side);
    assert.deepEqual(ramp[0], [260 + side * 115, -775, 24]);
    const [x, y, z] = ramp.at(-1);
    assert.ok(Math.abs(x - 260) < 1e-8);
    assert.ok(Math.abs(y + 660) < 1e-8);
    assert.ok(Math.abs(z - bridgeDeckHeight(x, y)) < 1e-8);
    for (let i = 1; i < ramp.length; i++) {
      assert.ok(Math.abs(ramp[i][2] - ramp[i - 1][2]) < 0.2);
    }
  }
});
