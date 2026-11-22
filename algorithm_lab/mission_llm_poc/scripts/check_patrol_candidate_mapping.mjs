/** Fixture shape check only. Does not start a server, send requests or generate an approval. */
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { proposalToPlan } from "../../../frontend/swarm-console/simulation-3d/tools/proposal-to-plan.mjs";

const [filename, outputPath] = process.argv.slice(2);
if (!filename || !outputPath || process.argv.length !== 4) {
  throw new Error("Provide the generated fixture report JSON and a new proof output path");
}
const report = JSON.parse(readFileSync(filename, "utf8"));
assert.equal(report.scope, "fake_adapter_only");
assert.equal(report.execution_authorized, false);

const checked = [];
for (const { result } of report.cases) {
  assert.equal(result.scope, "fake_adapter_only");
  assert.equal(result.execution_authorized, false);
  assert.equal(result.runtime_submission_allowed, false);
  if (result.status !== "candidate") {
    assert.equal(result.proposal, null);
    checked.push({ candidate_status: result.status, reason_code: result.reason_code, handed_to_converter: false });
    continue;
  }
  assert.equal(result.completion_expectation.inspection_completed, false);
  assert.equal(result.proposal.execution_authorized, false);
  const fakePlanId = "fake-plan-" + result.candidate_id;
  const options = { takeoffAltitudeM: 6, planId: fakePlanId };
  if (result.purpose === "fake_equipment_inspection") {
    assert.throws(() => proposalToPlan(result.proposal, result.context, options), err => {
      assert.equal(err.code, "proposal_not_executable");
      assert.equal(err.violations.length, result.proposal.assignments.length);
      assert(err.violations.every(v => v.action === "OBSERVE" && v.reason_code === "action_endpoint_not_implemented"));
      checked.push({ candidate_id: result.candidate_id, converter_status: "blocked",
        failure_reason: err.code, violations: err.violations, omitted_steps: true });
      return true;
    });
  } else {
    assert.equal(result.purpose, "fake_motion_only");
    const { plan } = proposalToPlan(result.proposal, result.context, options);
    assert.equal(plan.plan_id, fakePlanId);
    assert.equal(plan.mission_type, "flight_validation");
    assert.equal(plan.scene_id, result.context.scene_id);
    assert.equal(plan.map_version, result.context.map_version);
    assert.equal(plan.steps.length, 2);
    assert.equal(new Set(plan.steps.map(step => step.step_id)).size, plan.steps.length);
    assert(plan.steps.every(step => step.node_id === "UAV-02" && step.action_type === "goto"));
    for (const [i, step] of plan.steps.entries()) {
      assert.deepEqual(step.params, result.context.waypoints[i].position_m);
    }
    checked.push({ candidate_id: result.candidate_id, converter_status: "fake_motion_shape_only",
      fixture_shape: { ...plan, explanation: "Fake Adapter 的移动形状检查；不含起降或观察、不得提交运行。",
        execution_authorized: false, scope: "fake_adapter_only" } });
  }
}
const proof = { baseline: report.baseline, scope: "fake_adapter_only",
  requests_sent: 0, execution_authorized: false, checked };
writeFileSync(outputPath, JSON.stringify(proof, null, 2) + "\n", {encoding: "utf8", flag: "wx"});
console.log(JSON.stringify(checked.map(row => row.converter_status || row.reason_code)));
