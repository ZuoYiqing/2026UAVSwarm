import { ArcType, Color, PolylineDashMaterialProperty } from "cesium";

const PREVIEW_COLOR = Color.fromCssColorString("#a34e10");
// Opposite directions on the same segment must leave the same gaps.
const DASH_PATTERN = 0b0000111111110000;
const MAX_WAYPOINTS = 500;
const isId = value => typeof value === "string" && value.trim().length > 0 && value.length <= 128;

function previewGroups(payload, scene, nowMs) {
  if (!scene || payload?.version !== "1.0" || !isId(payload.plan_id)
    || payload.scene_id !== scene.scene_id || payload.map_version !== scene.map_version
    || payload.frame !== "scene_ned" || !Number.isSafeInteger(payload.expires_at_ms)
    || payload.expires_at_ms <= nowMs || !Array.isArray(payload.waypoints)
    || payload.waypoints.length < 1 || payload.waypoints.length > MAX_WAYPOINTS) return null;

  const groups = new Map();
  const steps = new Set();
  for (const point of payload.waypoints) {
    if (!isId(point?.step_id) || !isId(point.node_id) || steps.has(point.step_id)
      || ![point.north_m, point.east_m, point.down_m].every(Number.isFinite)) return null;
    steps.add(point.step_id);
    if (!groups.has(point.node_id)) groups.set(point.node_id, []);
    groups.get(point.node_id).push(point);
  }
  return groups;
}

export class PlanPreviewLayer {
  constructor(entities, enuToWorld, onChange = () => {}) {
    this.entities = entities;
    this.enuToWorld = enuToWorld;
    this.onChange = onChange;
    this.scene = null;
    this.drawn = [];
    this.summary = null;
  }

  setScene(scene) {
    if (this.scene === scene) return;
    this.scene = scene;
    this.clear();
  }

  apply(payload, nowMs = Date.now()) {
    const groups = previewGroups(payload, this.scene, nowMs);
    if (!groups) {
      this.clear();
      return payload === null;
    }
    const projected = [...groups].map(([nodeId, points]) => ({
      nodeId, points, positions: points.map(p => this.enuToWorld(p.east_m, p.north_m, -p.down_m)),
    }));
    if (projected.some(group => group.positions.some(p => ![p.x, p.y, p.z].every(Number.isFinite)))) {
      this.clear();
      return false;
    }

    this.#removeEntities();
    for (const { nodeId, points, positions } of projected) {
      const properties = { semantic: "plan_preview", plan_id: payload.plan_id, node_id: nodeId };
      if (positions.length > 1) {
        this.drawn.push(this.entities.add({
          properties,
          polyline: {
            positions,
            arcType: ArcType.NONE,
            width: 3,
            material: new PolylineDashMaterialProperty({
              color: PREVIEW_COLOR, dashLength: 14, dashPattern: DASH_PATTERN,
            }),
          },
        }));
      }
      for (const [i, position] of positions.entries()) {
        this.drawn.push(this.entities.add({
          properties: { ...properties, step_id: points[i].step_id },
          position,
          point: { color: Color.WHITE, outlineColor: PREVIEW_COLOR, outlineWidth: 2, pixelSize: 8 },
        }));
      }
    }
    this.summary = Object.freeze({
      planId: payload.plan_id, expiresAtMs: payload.expires_at_ms, waypointCount: payload.waypoints.length,
    });
    this.onChange(this.summary);
    return true;
  }

  expire(nowMs = Date.now()) {
    if (this.summary && nowMs >= this.summary.expiresAtMs) this.clear();
  }

  clear() {
    if (!this.summary) return;
    this.#removeEntities();
    this.summary = null;
    this.onChange(null);
  }

  #removeEntities() {
    for (const entity of this.drawn) this.entities.remove(entity);
    this.drawn.length = 0;
  }
}
