#!/usr/bin/env node
/**
 * 冒烟：用算法侧真实巡检样例跑一次转换器，确认 HOLD / RETURN_HOME 能展开。
 *
 * 为什么需要这一步：单元测试用的是本文件构造的提案。这里用的是算法侧
 * base_context.json 里**真实的 required_actions**，因此能验证"真实巡检序列
 * 现在能展开到哪一步" —— 这正是算法负责人指出的那条链路缺口。
 *
 * 只做离线转换，不提交、不执行、不飞。
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { proposalToPlan, ProposalRejected } from
  "../tools/proposal-to-plan.mjs";

const ALGO = process.env.UAV_ALGO_REPO ||
  "D:/2026UAVSwarm-worktrees/algorithm-lab-local-llm-poc/algorithm_lab/mission_llm_poc";

const context = JSON.parse(
  readFileSync(resolve(ALGO, "src/uavswarm_llm_lab/benchmarks/base_context.json"), "utf8"),
);

/** 按 required_actions 构造提案（模拟算法侧的真实产出） */
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

const required = [...new Set(context.tasks.flatMap((t) => t.required_actions || []))];
console.log("=".repeat(72));
console.log("算法侧真实 required_actions:", JSON.stringify(required));
console.log("=".repeat(72));

// ① 原样（含 OBSERVE）—— 预期仍被拒，且只应因 OBSERVE
console.log("\n① 按原始 required_actions 转换：");
try {
  proposalToPlan(build(required), context, { takeoffAltitudeM: 20, holdDurationS: 5 });
  console.log("   ⚠️ 竟然通过了 —— 说明 OBSERVE 被误当成可展开，需要检查");
} catch (error) {
  if (!(error instanceof ProposalRejected)) throw error;
  const kinds = error.violations.map((v) => `${v.kind}/${v.action || v.field || ""}`);
  console.log(`   ❌ 拒绝（预期）code=${error.code}`);
  console.log(`   违规: ${JSON.stringify(kinds)}`);
  const nonObserve = error.violations.filter((v) => v.action !== "OBSERVE");
  console.log(
    nonObserve.length === 0
      ? "   ✅ 唯一原因是 OBSERVE —— 说明 HOLD / RETURN_HOME 不再是链路缺口"
      : `   ❌ 仍有非 OBSERVE 的缺口: ${JSON.stringify(nonObserve)}`,
  );
}

// ② 去掉 OBSERVE（模拟"OBSERVE 端点已实现"之后的形态）
const withoutObserve = required.filter((a) => a !== "OBSERVE");
console.log(`\n② 去掉 OBSERVE 后转换（${JSON.stringify(withoutObserve)}）：`);
try {
  const { plan, notes } = proposalToPlan(build(withoutObserve), context, {
    takeoffAltitudeM: 20,
    holdDurationS: 5,
  });
  console.log(`   ✅ 展开成功：${plan.steps.length} 步`);
  const byType = {};
  for (const step of plan.steps) byType[step.action_type] = (byType[step.action_type] || 0) + 1;
  console.log(`   动作分布: ${JSON.stringify(byType)}`);
  console.log(`   scene_id: ${plan.scene_id}  map_version: ${plan.map_version}`);
  console.log("\n   每台机第一步之后的动作序列（取 UAV-01）：");
  for (const step of plan.steps.filter((s) => s.node_id === "UAV-01")) {
    console.log(`     ${step.step_id}  →  ${step.action_type} ${JSON.stringify(step.params)}`);
  }
  console.log("\n   notes:");
  for (const note of notes) console.log(`     · ${note}`);
  console.log("\n   explanation:");
  console.log(`     ${plan.explanation}`);
} catch (error) {
  if (!(error instanceof ProposalRejected)) throw error;
  console.log(`   ❌ 仍被拒: code=${error.code}`);
  console.log(`   ${JSON.stringify(error.violations, null, 2)}`);
}

console.log("\n" + "=".repeat(72));
console.log("本冒烟只做离线转换：未提交任何计划、未连接 Runtime、未起飞。");
