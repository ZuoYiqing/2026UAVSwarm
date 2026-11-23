import assert from "node:assert/strict";
import test from "node:test";
import { Cartesian3, Color, EntityCollection } from "cesium";
import { createReferenceScene } from "../src/reference-scene.js";

test("reference scene draws the five catalog markers at their ENU locations", () => {
  const entities = new EntityCollection();
  const scene = createReferenceScene({ entities }, point => new Cartesian3(...point));
  scene.setVisible(true);

  const west = entities.getById("recon-demo-anchor-001");
  const east = entities.getById("recon-demo-anchor-002");
  assert.equal(west.label.text.getValue(), "001");
  assert.equal(east.label.text.getValue(), "002");
  assert.deepEqual(west.position.getValue(), new Cartesian3(-15, 4, 1.8));
  assert.deepEqual(east.position.getValue(), new Cartesian3(16, 4, 1.8));
  assert(!Color.equals(west.point.color.getValue(), east.point.color.getValue()));

  const area = entities.getById("recon-demo-area-001");
  assert.deepEqual(area.polyline.positions.getValue(), [
    new Cartesian3(-22, 24, 0.045), new Cartesian3(-10, 24, 0.045),
    new Cartesian3(-10, 42, 0.045), new Cartesian3(-22, 42, 0.045),
    new Cartesian3(-22, 24, 0.045),
  ]);
  const sw = entities.getById("recon-demo-sector-001");
  const se = entities.getById("recon-demo-sector-002");
  assert(Color.equals(sw.polyline.material.color.getValue(), se.polyline.material.color.getValue()));
  assert([west, east, area, sw, se].every(entity => entity.show));

  scene.setVisible(false);
  assert([west, east, area, sw, se].every(entity => !entity.show));
});
