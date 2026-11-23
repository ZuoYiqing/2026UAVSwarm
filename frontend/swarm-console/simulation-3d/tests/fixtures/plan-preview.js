import { readFileSync } from "node:fs";

export const { plan } = JSON.parse(readFileSync(new URL(
  "../../../tests/fixtures/equipment-inspection-lifecycle.json", import.meta.url,
), "utf8"));

// Mirrors the parent projection of a validated Fake plan; no execution fields leave the parent.
export function planPreview(expiresAtMs) {
  return {
    version: "1.0",
    plan_id: plan.plan_id,
    scene_id: plan.scene_id,
    map_version: plan.map_version,
    frame: "scene_ned",
    expires_at_ms: expiresAtMs,
    waypoints: plan.steps.filter(step => step.action_type === "goto").map(({ step_id, node_id, params }) => ({
      step_id, node_id, north_m: params.north_m, east_m: params.east_m, down_m: params.down_m,
    })),
  };
}
