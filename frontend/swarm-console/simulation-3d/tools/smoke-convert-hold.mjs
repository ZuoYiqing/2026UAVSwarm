#!/usr/bin/env node
/**
 * 冒烟：验证 HOLD 在**真实 context** 下的两条路径 —— 给了时长能展开、没给则拒绝。
 *
 * 为什么单独做：算法侧真实的 required_actions 是
 * TAKEOFF/GOTO/OBSERVE/RETURN_HOME/LAND —— **不含 HOLD**。因此 HOLD 的展开
 * 只在单元测试里覆盖过。这里用同一份真实 context 补上 HOLD 的端到端验证。
 *
 * 只做离线转换，不提交、不执行、不飞。
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { proposalToPlan, ProposalRejected } from "../tools/proposal-to-plan.mjs";

const ALGO = process.env.UAV_ALGO_REPO ||
  "D:/2026UAVSwarm-worktrees/algorithm-lab-local-llm-poc/algorithm_lab/mission_llm_poc";

const context = JSON.parse(
  readFileSync(resolve(ALGO, "src/uavswarm_llm_lab/benchmarks/base_context.json"), "utf8"),
);

function build(actions) {
  return {
    schema_version: "0.1",
    mission_id: context.mission_id,
    scene_id: context.scene_id,
    map_version: context.map_version,
    status: "proposed",
    reason_code: "MISSION_PROPOSED",
    execution_authorized: false,
    assignments: context.tasks.map((task, i) => ({
      task_id: task.task_id,
      node_id: `UAV-0${i + 1}`,
      actions: [...actions],
      waypoint_ids: [...task.waypoint_ids],
      reason_code: "ASSIGNED",
      explanation: "smoke",
    })),
  };
}

// 巡检的实际形态：飞到航点后停住让相机采集，再返航降落。
const WITH_HOLD = ["TAKEOFF", "GOTO", "HOLD", "RETURN_HOME", "LAND"];

console.log("=".repeat(72));
console.log("HOLD 端到端（真实 context）:", JSON.stringify(WITH_HOLD));
console.log("=".repeat(72));

console.log("\n① 给 holdDurationS=8：");
try {
  const { plan, notes } = proposalToPlan(build(WITH_HOLD), context, {
    takeoffAltitudeM: 20,
    holdDurationS: 8,
  });
  const holds = plan.steps.filter((s) => s.action_type === "hold_position");
  console.log(`   ✅ 展开成功：${plan.steps.length} 步，其中 hold_position ${holds.length} 个`);
  for (const step of holds) {
    console.log(`     ${step.step_id}  →  hold_position ${JSON.stringify(step.params)}`);
  }
  console.log("\n   UAV-01 完整序列：");
  for (const step of plan.steps.filter((s) => s.node_id === "UAV-01")) {
    console.log(`     ${step.action_type.padEnd(14)} ${JSON.stringify(step.params)}`);
  }
  console.log("\n   HOLD 相关 note:");
  for (const note of notes.filter((n) => n.includes("HOLD"))) console.log(`     · ${note}`);
} catch (error) {
  if (!(error instanceof ProposalRejected)) throw error;
  console.log(`   ❌ 意外被拒: ${error.code} ${JSON.stringify(error.violations)}`);
}

console.log("\n② 不给 holdDurationS（应拒绝整份，不能自己编一个秒数）：");
try {
  proposalToPlan(build(WITH_HOLD), context, { takeoffAltitudeM: 20 });
  console.log("   ❌ 竟然通过了 —— 说明展开器自己填了默认时长，这正是要避免的");
} catch (error) {
  if (!(error instanceof ProposalRejected)) throw error;
  console.log(`   ✅ 拒绝（预期）code=${error.code}`);
  console.log(`   message: ${error.message}`);
  console.log(`   violations: ${JSON.stringify(error.violations)}`);
}

console.log("\n③ 提案不含 HOLD 时，不给 holdDurationS 也应正常展开：");
try {
  const noHold = ["TAKEOFF", "GOTO", "RETURN_HOME", "LAND"];
  const { plan } = proposalToPlan(build(noHold), context, { takeoffAltitudeM: 20 });
  console.log(`   ✅ 展开成功：${plan.steps.length} 步（不该被 HOLD 的规则牵连）`);
} catch (error) {
  if (!(error instanceof ProposalRejected)) throw error;
  console.log(`   ❌ 意外被拒: ${error.code}`);
}

console.log("\n" + "=".repeat(72));
console.log("只做离线转换：未提交任何计划、未连接 Runtime、未起飞。");
