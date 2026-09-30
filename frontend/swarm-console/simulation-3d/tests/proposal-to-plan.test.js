/**
 * 提案 → 计划 转换器的测试。
 *
 * 重点在**拒绝语义**：转换器最危险的失败模式不是"转不出来"，而是"悄悄少做
 * 一件事" —— 跳过不认识的动作、给查不到的航点补默认值、给没写目标的步骤
 * 拿一台飞机顶上。这些都会产生"计划显示完成、实际少做了事"的假成功。
 *
 * 因此每个拒绝路径都有用例，并且断言**拒绝整份提案**（而不是返回子集）。
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  EXPANDABLE_ACTIONS,
  KNOWN_NOT_EXPANDABLE,
  ProposalRejected,
  proposalToPlan,
} from "../tools/proposal-to-plan.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));

/** 算法侧的真实飞行验证输入（三机 TAKEOFF/GOTO/LAND）。 */
function flightValidationContext() {
  const path = resolve(
    process.env.UAV_ALGO_REPO ||
      "D:/2026UAVSwarm-worktrees/algorithm-lab-local-llm-poc/algorithm_lab/mission_llm_poc",
    "examples/flight_validation_only.json",
  );
  return { path, context: JSON.parse(readFileSync(path, "utf8")) };
}

function proposalFrom(context, { actions = ["TAKEOFF", "GOTO", "LAND"] } = {}) {
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
      explanation: "test",
    })),
  };
}

// --- 正常展开 ---------------------------------------------------------------

test("三机飞行验证提案展开为每机 TAKEOFF/GOTO/LAND", (t) => {
  let ctx;
  try {
    ({ context: ctx } = flightValidationContext());
  } catch {
    t.skip("未找到算法侧样例（可用 UAV_ALGO_REPO 指定）");
    return;
  }

  const { plan, notes } = proposalToPlan(proposalFrom(ctx), ctx, { takeoffAltitudeM: 3 });

  assert.equal(plan.steps.length, 9, "3 机 × 3 动作");
  assert.equal(plan.scene_id, ctx.scene_id);
  assert.equal(plan.map_version, ctx.map_version);

  // 每台的动作顺序必须保持
  for (let i = 0; i < 3; i += 1) {
    const node = `UAV-0${i + 1}`;
    const own = plan.steps.filter((s) => s.node_id === node);
    assert.deepEqual(own.map((s) => s.action_type), ["takeoff", "goto", "land"], `${node} 动作顺序`);
  }

  // takeoff 高度必须来自显式配置
  for (const step of plan.steps.filter((s) => s.action_type === "takeoff")) {
    assert.equal(step.params.altitude_m, 3);
  }

  // goto 坐标必须原样来自 context 的 waypoints（不做任何换算）
  const gotoByNode = Object.fromEntries(
    plan.steps.filter((s) => s.action_type === "goto").map((s) => [s.node_id, s.params]),
  );
  for (const waypoint of ctx.waypoints) {
    const expected = {
      north_m: waypoint.position_m.north_m,
      east_m: waypoint.position_m.east_m,
      down_m: waypoint.position_m.down_m,
    };
    assert.ok(
      Object.values(gotoByNode).some(
        (p) => p.north_m === expected.north_m && p.east_m === expected.east_m && p.down_m === expected.down_m,
      ),
      `航点 ${waypoint.waypoint_id} 的坐标应原样出现在某个 goto 里`,
    );
  }

  // land 不带参数
  for (const step of plan.steps.filter((s) => s.action_type === "land")) {
    assert.deepEqual(step.params, {});
  }

  // 不得声称完成巡检
  assert.ok(
    notes.some((n) => n.includes("不证明巡检")),
    "应带出不构成巡检完成的声明",
  );
});

test("每个 step 都带目标载具", (t) => {
  let ctx;
  try {
    ({ context: ctx } = flightValidationContext());
  } catch {
    t.skip("未找到算法侧样例");
    return;
  }
  const { plan } = proposalToPlan(proposalFrom(ctx), ctx, { takeoffAltitudeM: 3 });
  for (const step of plan.steps) {
    assert.ok(step.node_id && step.node_id.trim() !== "", `${step.step_id} 缺 node_id`);
  }
});

test("多个 GOTO 时航点按顺序展开为多个 step", () => {
  const ctx = {
    scene_id: "s", map_version: "m", mission_id: "multi-goto",
    waypoints: [
      { waypoint_id: "W1", position_m: { north_m: 10, east_m: 0, down_m: -5 } },
      { waypoint_id: "W2", position_m: { north_m: 20, east_m: 0, down_m: -5 } },
      { waypoint_id: "W3", position_m: { north_m: 30, east_m: 0, down_m: -5 } },
    ],
  };
  const proposal = {
    mission_id: "multi-goto", scene_id: "s", map_version: "m",
    assignments: [{
      task_id: "T1", node_id: "UAV-01",
      actions: ["TAKEOFF", "GOTO", "GOTO", "LAND"],
      waypoint_ids: ["W1", "W2", "W3"],
    }],
  };

  const { plan, notes } = proposalToPlan(proposal, ctx, { takeoffAltitudeM: 5 });
  const gotos = plan.steps.filter((s) => s.action_type === "goto");
  assert.equal(gotos.length, 3, "3 个航点应展开为 3 个 goto step");
  assert.deepEqual(gotos.map((s) => s.params.north_m), [10, 20, 30], "顺序必须保持");
  assert.ok(notes.some((n) => n.includes("多个 GOTO") || n.includes("2 个 GOTO")), "应说明分段方式");
});

// --- 拒绝路径 ---------------------------------------------------------------

test("缺少显式起飞高度时拒绝：不从 constraints 推断", () => {
  const ctx = {
    scene_id: "s", map_version: "m", mission_id: "x",
    constraints: { min_altitude_m: 3, max_altitude_m: 15 },
    waypoints: [{ waypoint_id: "W1", position_m: { north_m: 1, east_m: 0, down_m: -3 } }],
  };
  const proposal = {
    mission_id: "x", scene_id: "s", map_version: "m",
    assignments: [{ task_id: "T1", node_id: "UAV-01", actions: ["TAKEOFF"], waypoint_ids: [] }],
  };
  // 即使 context 里有 min_altitude_m: 3，也不能拿它当任务高度
  assert.throws(
    () => proposalToPlan(proposal, ctx),
    (e) => e instanceof ProposalRejected && e.code === "takeoff_altitude_required",
  );
  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 0 }),
    (e) => e.code === "takeoff_altitude_required",
  );
});

test("不可执行的动作拒绝整份提案，并给出 task/action/原因", () => {
  const ctx = {
    scene_id: "s", map_version: "m", mission_id: "x",
    waypoints: [{ waypoint_id: "W1", position_m: { north_m: 1, east_m: 0, down_m: -3 } }],
  };
  const proposal = {
    mission_id: "x", scene_id: "s", map_version: "m",
    assignments: [
      { task_id: "T1", node_id: "UAV-01", actions: ["TAKEOFF", "GOTO", "LAND"], waypoint_ids: ["W1"] },
      // 第二个 task 含不可执行动作 —— 整份提案都要被拒
      { task_id: "T2", node_id: "UAV-02", actions: ["TAKEOFF", "OBSERVE", "LAND"], waypoint_ids: [] },
    ],
  };

  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 3 }),
    (e) => {
      assert.equal(e.code, "proposal_not_executable");
      const v = e.violations.find((x) => x.kind === "action_not_expandable");
      assert.ok(v, "应指出是哪个动作不可展开");
      assert.equal(v.task_id, "T2");
      assert.equal(v.action, "OBSERVE");
      assert.equal(v.reason_code, "action_endpoint_not_implemented");
      assert.ok(v.reason_code !== "unknown_action", "OBSERVE 是已声明动作，不该报成拼写错误");
      return true;
    },
  );
});

test("高风险载荷动作报 action_not_supported 而不是「尚未实现」", () => {
  const ctx = { scene_id: "s", map_version: "m", mission_id: "x", waypoints: [] };
  const proposal = {
    mission_id: "x", scene_id: "s", map_version: "m",
    assignments: [{ task_id: "T1", node_id: "UAV-01", actions: ["ATTACK"], waypoint_ids: [] }],
  };
  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 3 }),
    (e) => e.violations.some(
      (v) => v.action === "ATTACK" && v.reason_code === "action_not_supported",
    ),
  );
});

test("缺失目标载具拒绝整份提案", () => {
  const ctx = { scene_id: "s", map_version: "m", mission_id: "x", waypoints: [] };
  const proposal = {
    mission_id: "x", scene_id: "s", map_version: "m",
    assignments: [{ task_id: "T1", node_id: "", actions: ["TAKEOFF"], waypoint_ids: [] }],
  };
  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 3 }),
    (e) => e.violations.some((v) => v.kind === "missing_target_vehicle"),
  );
});

test("航点 ID 查不到时拒绝，并指出是哪个航点", () => {
  const ctx = {
    scene_id: "s", map_version: "m", mission_id: "x",
    waypoints: [{ waypoint_id: "W1", position_m: { north_m: 1, east_m: 0, down_m: -3 } }],
  };
  const proposal = {
    mission_id: "x", scene_id: "s", map_version: "m",
    assignments: [{ task_id: "T1", node_id: "UAV-01", actions: ["GOTO"], waypoint_ids: ["W1", "W-NOPE"] }],
  };
  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 3 }),
    (e) => {
      const v = e.violations.find((x) => x.kind === "waypoint_not_found");
      assert.ok(v);
      assert.equal(v.waypoint_id, "W-NOPE");
      return true;
    },
  );
});

test("GOTO 但没有航点时拒绝", () => {
  const ctx = { scene_id: "s", map_version: "m", mission_id: "x", waypoints: [] };
  const proposal = {
    mission_id: "x", scene_id: "s", map_version: "m",
    assignments: [{ task_id: "T1", node_id: "UAV-01", actions: ["TAKEOFF", "GOTO"], waypoint_ids: [] }],
  };
  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 3 }),
    (e) => e.violations.some((v) => v.kind === "goto_without_waypoint"),
  );
});

test("场景身份在提案与 context 之间不一致时拒绝", () => {
  const ctx = {
    scene_id: "scene-A", map_version: "map-A", mission_id: "x",
    waypoints: [{ waypoint_id: "W1", position_m: { north_m: 1, east_m: 0, down_m: -3 } }],
  };
  const proposal = {
    mission_id: "x", scene_id: "scene-B", map_version: "map-A",
    assignments: [{ task_id: "T1", node_id: "UAV-01", actions: ["TAKEOFF"], waypoint_ids: [] }],
  };
  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 3 }),
    (e) => {
      const v = e.violations.find((x) => x.kind === "scene_identity_conflict");
      assert.ok(v, "应指出场景身份冲突");
      assert.equal(v.field, "scene_id");
      assert.equal(v.proposal_value, "scene-B");
      assert.equal(v.context_value, "scene-A");
      return true;
    },
  );
});

test("场景身份缺失时拒绝", () => {
  const ctx = { scene_id: "", map_version: "map-A", mission_id: "x", waypoints: [] };
  const proposal = {
    mission_id: "x", scene_id: "", map_version: "map-A",
    assignments: [{ task_id: "T1", node_id: "UAV-01", actions: ["TAKEOFF"], waypoint_ids: [] }],
  };
  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 3 }),
    (e) => e.violations.some((v) => v.kind === "scene_identity_missing" && v.field === "scene_id"),
  );
});

test("没有 assignments 时拒绝", () => {
  const ctx = { scene_id: "s", map_version: "m", mission_id: "x", waypoints: [] };
  assert.throws(
    () => proposalToPlan({ mission_id: "x", scene_id: "s", map_version: "m", assignments: [] }, ctx, {
      takeoffAltitudeM: 3,
    }),
    (e) => e.violations.some((v) => v.kind === "no_assignments"),
  );
});

test("拒绝时返回可解析的响应体，且不含任何可执行步骤", () => {
  const ctx = { scene_id: "s", map_version: "m", mission_id: "x", waypoints: [] };
  const proposal = {
    mission_id: "x", scene_id: "s", map_version: "m",
    assignments: [{ task_id: "T1", node_id: "UAV-01", actions: ["OBSERVE"], waypoint_ids: [] }],
  };
  try {
    proposalToPlan(proposal, ctx, { takeoffAltitudeM: 3 });
    assert.fail("应当抛出");
  } catch (error) {
    const body = error.toResponse();
    assert.equal(body.result, "blocked");
    assert.equal(body.failure_reason, "proposal_not_executable");
    assert.ok(Array.isArray(body.detail.violations) && body.detail.violations.length > 0);
    assert.ok(!("plan" in body), "拒绝响应里不应带可执行计划");
  }
});

// --- 用算法侧的真实巡检样例验证「整份拒绝」 -------------------------------

test("现有巡检样例被整份拒绝：它要求 OBSERVE 与 RETURN_HOME", (t) => {
  // 交接说明明确写着：现有研究巡检任务需要 OBSERVE 与 RETURN_HOME，
  // 因此不得转换成"已完成巡检"的执行计划。
  let ctx;
  try {
    const path = resolve(
      process.env.UAV_ALGO_REPO ||
        "D:/2026UAVSwarm-worktrees/algorithm-lab-local-llm-poc/algorithm_lab/mission_llm_poc",
      "src/uavswarm_llm_lab/benchmarks/base_context.json",
    );
    ctx = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    t.skip("未找到算法侧 base_context.json（可用 UAV_ALGO_REPO 指定）");
    return;
  }

  // 前置：确认这份样例确实要求了那两个动作，否则这个测试证明不了什么
  const required = new Set(ctx.tasks.flatMap((task) => task.required_actions || []));
  assert.ok(required.has("OBSERVE"), "样例应要求 OBSERVE，否则测试前提不成立");
  assert.ok(required.has("RETURN_HOME"), "样例应要求 RETURN_HOME，否则测试前提不成立");

  // 算法侧会产出与 required_actions 一致的提案
  const proposal = {
    schema_version: "0.1",
    mission_id: ctx.mission_id,
    scene_id: ctx.scene_id,
    map_version: ctx.map_version,
    status: "proposed",
    reason_code: "MISSION_PROPOSED",
    execution_authorized: false,
    assignments: ctx.tasks.map((task, i) => ({
      task_id: task.task_id,
      node_id: `UAV-0${i + 1}`,
      actions: task.required_actions.map((a) => String(a).toUpperCase()),
      waypoint_ids: task.waypoint_ids,
      reason_code: "ASSIGNED",
      explanation: "inspection",
    })),
  };

  assert.throws(
    () => proposalToPlan(proposal, ctx, { takeoffAltitudeM: 5 }),
    (error) => {
      assert.equal(error.name, "ProposalRejected");
      assert.equal(error.code, "proposal_not_executable");

      const actions = error.violations
        .filter((v) => v.kind === "action_not_expandable")
        .map((v) => v.action);
      assert.ok(actions.includes("OBSERVE"), `应指出 OBSERVE 不可展开，实际 ${JSON.stringify(actions)}`);
      assert.ok(actions.includes("RETURN_HOME"), `应指出 RETURN_HOME 不可展开，实际 ${JSON.stringify(actions)}`);

      // 拒绝必须是整份的：不能返回"去掉这两个动作后剩下的可执行子集"
      const body = error.toResponse();
      assert.ok(!("plan" in body), "拒绝时不得给出任何可执行计划");
      assert.ok(
        error.violations.every((v) => v.task_id),
        "每条违规都应指明是哪个 task",
      );
      return true;
    },
  );
});

// --- 常量一致性 -------------------------------------------------------------

test("可展开动作与 Runtime 端点一一对应，且与不可展开列表不重叠", () => {
  assert.deepEqual(Object.keys(EXPANDABLE_ACTIONS).sort(), ["GOTO", "LAND", "TAKEOFF"]);
  for (const [name, endpoint] of Object.entries(EXPANDABLE_ACTIONS)) {
    assert.ok(["takeoff", "goto", "land"].includes(endpoint), `${name} 的端点名异常`);
  }
  const overlap = Object.keys(EXPANDABLE_ACTIONS).filter((a) => KNOWN_NOT_EXPANDABLE.includes(a));
  assert.deepEqual(overlap, [], "两个列表不应有交集");
});
