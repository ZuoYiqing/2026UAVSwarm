import assert from "node:assert/strict";
import test from "node:test";
import {
  BoundingSphere, Camera, Cartesian3, Color, EntityCollection, GeographicProjection, HeadingPitchRange,
  Intersect, Math as CesiumMath, Matrix4, PrimitiveCollection, SceneMode, Transforms,
} from "cesium";
import entityCatalog from "../../../../scenarios/simple_recon_v0_1/entity_catalog.json" with { type: "json" };
import { createReferenceScene, REFERENCE_VIEW } from "../src/reference-scene.js";

test("reference scene draws the five catalog markers at their ENU locations", () => {
  const entities = new EntityCollection();
  const primitives = new PrimitiveCollection();
  const scene = createReferenceScene({ entities, scene: { primitives } }, point => new Cartesian3(...point));
  scene.setVisible(true);

  const west = entities.getById("recon-demo-anchor-001");
  const east = entities.getById("recon-demo-anchor-002");
  assert.equal(west.label.text.getValue(), "001");
  assert.equal(east.label.text.getValue(), "002");
  assert.deepEqual(west.position.getValue(), new Cartesian3(-15, 4, 1.8));
  assert.deepEqual(east.position.getValue(), new Cartesian3(16, 4, 1.8));
  assert(!Color.equals(west.point.color.getValue(), east.point.color.getValue()));

  const area = entities.getById("recon-demo-area-001-fill");
  assert.deepEqual(area.polygon.hierarchy.getValue().positions, [
    new Cartesian3(-22, 24, 0.045), new Cartesian3(-10, 24, 0.045),
    new Cartesian3(-10, 42, 0.045), new Cartesian3(-22, 42, 0.045),
  ]);
  const outlines = primitives.get(0);
  const [nw, sw, se] = outlines.geometryInstances;
  assert.deepEqual([nw.id, sw.id, se.id], ["recon-demo-area-001", "recon-demo-sector-001", "recon-demo-sector-002"]);
  assert.deepEqual(sw.attributes.color.value, se.attributes.color.value);
  assert([west, east, area, outlines].every(entity => entity.show));

  scene.setVisible(false);
  assert([west, east, area, outlines].every(entity => !entity.show));
});

test("the default recon camera frames the new markers", () => {
  const origin = entityCatalog.origin;
  const center = Cartesian3.fromDegrees(origin.lon_deg, origin.lat_deg, origin.alt_m);
  const enu = Transforms.eastNorthUpToFixedFrame(center);
  const entities = new EntityCollection();
  const toWorld = point => Matrix4.multiplyByPoint(enu, new Cartesian3(...point), new Cartesian3());
  createReferenceScene({ entities, scene: { primitives: new PrimitiveCollection() } }, toWorld).setVisible(true);
  for (const [width, height] of [[1440, 1000], [1280, 720]]) {
    const camera = new Camera({
      drawingBufferWidth: width, drawingBufferHeight: height,
      mapProjection: new GeographicProjection(), mode: SceneMode.SCENE3D,
    });
    camera.lookAt(center, new HeadingPitchRange(
      CesiumMath.toRadians(REFERENCE_VIEW.headingDeg),
      CesiumMath.toRadians(REFERENCE_VIEW.pitchDeg),
      REFERENCE_VIEW.rangeM,
    ));
    const frustum = camera.frustum.computeCullingVolume(camera.positionWC, camera.directionWC, camera.upWC);
    for (const id of ["demo-area-001", "demo-sector-001", "demo-sector-002", "demo-anchor-001", "demo-anchor-002"]) {
      const marker = entities.getById(`recon-${id}`) ?? entities.getById(`recon-${id}-fill`);
      const points = marker.polygon ? marker.polygon.hierarchy.getValue().positions : [marker.position.getValue()];
      for (const point of points) {
        assert.notEqual(frustum.computeVisibility(new BoundingSphere(point, 0)), Intersect.OUTSIDE, id);
      }
    }
  }
});
