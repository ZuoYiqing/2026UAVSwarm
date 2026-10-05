'use strict';

// 澄清请求（clarification）的规范化与重提交测试。
//
// 背景：算法侧遇到目标歧义时不猜，而是返回一个澄清请求，要求操作者补全。
// 算法侧的交接说明写得很明确：
//
//   > `resolution=resubmit_objective_without_tasks`。调用方应在现有控制台把问题
//   > 呈现给操作者。
//
// 两个真实形状（都在算法侧代码里，不是设想）：
//
//   ① intent_grounder.derive_proposal —— 请求里带了 `tasks`：
//      {audience, mission_id, conflicting_fields, question, resolution}
//      reason_code = EXTERNAL_TASKS_FORBIDDEN
//
//   ② scene_binding —— 目标歧义，带候选：
//      {status:"clarification_required", reason_code, candidates[], clarification_question,
//       matched_text?}
//      reason_code 如 AMBIGUOUS_HIGHEST_BUILDING / MULTIPLE_BUILDING_REFERENCES
//
// **最要紧的一条约束**：`resubmit_objective_without_tasks` 要求重提交时**不能带 tasks**。
// 带回去会再次触发 EXTERNAL_TASKS_FORBIDDEN —— 操作者会陷入"提交→被拒→再提交"的循环，
// 而且看不出原因。所以构建重提交时，**带 tasks 的输入必须被拒绝，不是静默丢弃**。

const test = require("node:test");
const assert = require("node:assert/strict");
const model = require("../console-model.js");

// 形状 ①：算法侧 derive_proposal 在请求带 tasks 时返回
const EXTERNAL_TASKS = {
  reason_code: "EXTERNAL_TASKS_FORBIDDEN",
  clarification_request: {
    audience: "originating_operator",
    mission_id: "mission-1",
    conflicting_fields: ["objective", "tasks"],
    question: "请确认原始任务目标并重新提交；任务清单将由目标派生。",
    resolution: "resubmit_objective_without_tasks",
  },
};

// 形状 ②：算法侧 scene_binding 在目标歧义时返回
const AMBIGUOUS_HIGHEST = {
  status: "clarification_required",
  accepted: false,
  reason_code: "AMBIGUOUS_HIGHEST_BUILDING",
  matched_text: "最高的那栋楼",
  candidates: [
    { target_id: "link-block-4-3-2-1", height_m: 52.0, center_north_m: 350.0, center_east_m: 53.2 },
    { target_id: "link-block-4-3-3-2", height_m: 52.0, center_north_m: 432.0, center_east_m: 179.8 },
  ],
  clarification_question: "最高建筑并列；请指定目标建筑 ID。",
};

// --- 规范化 -------------------------------------------------------------------

test("clarification: 形状① 被识别为「必须去掉 tasks」", () => {
  const result = model.normalizeClarification(EXTERNAL_TASKS);
  assert.equal(result.ok, true, JSON.stringify(result.violations));
  assert.equal(result.clarification.kind, "external_tasks_forbidden");
  assert.equal(result.clarification.question, EXTERNAL_TASKS.clarification_request.question);
  assert.equal(result.clarification.resolution, "resubmit_objective_without_tasks");
  assert.ok(result.clarification.conflictingFields.includes("tasks"));
  assert.deepEqual(result.clarification.candidates, []);
});

test("clarification: 形状② 被识别为「目标歧义」，并带出候选", () => {
  const result = model.normalizeClarification(AMBIGUOUS_HIGHEST);
  assert.equal(result.ok, true);
  assert.equal(result.clarification.kind, "ambiguous_target");
  assert.equal(result.clarification.reasonCode, "AMBIGUOUS_HIGHEST_BUILDING");
  assert.equal(result.clarification.matchedText, "最高的那栋楼");
  assert.equal(result.clarification.candidates.length, 2);
  assert.equal(result.clarification.candidates[0].targetId, "link-block-4-3-2-1");
  // 候选的几何信息要保留 —— 操作者需要它来区分两栋"并列最高"的楼
  assert.equal(result.clarification.candidates[0].heightM, 52.0);
  assert.equal(result.clarification.candidates[0].centerNorthM, 350.0);
});

test("clarification: status=clarification_required 但没有问题时也要能呈现", () => {
  const result = model.normalizeClarification({
    status: "clarification_required", reason_code: "UNKNOWN_TARGET",
    candidates: [{ target_id: "a" }],
  });
  assert.equal(result.ok, true);
  assert.equal(result.clarification.kind, "ambiguous_target");
  // 没有 question 时**不要编一句** —— 界面显示原始 reason_code 让操作者判断
  assert.equal(result.clarification.question, null);
  assert.equal(result.clarification.reasonCode, "UNKNOWN_TARGET");
});

test("clarification: 不带澄清的普通拒绝不会被误当成澄清", () => {
  const result = model.normalizeClarification({
    status: "rejected", accepted: false, reason_code: "REQUEST_REJECTED",
  });
  assert.equal(result.ok, false);
  assert.ok(result.violations.some((v) => v.code === "not_a_clarification"));
});

test("clarification: 空值/非对象被拒而不是抛异常", () => {
  for (const bad of [null, undefined, "x", 42, []]) {
    const result = model.normalizeClarification(bad);
    assert.equal(result.ok, false, JSON.stringify(bad));
  }
});

test("clarification: 候选没有 target_id 时跳过该候选，但不整体失败", () => {
  const result = model.normalizeClarification({
    status: "clarification_required", reason_code: "X",
    candidates: [{ target_id: "good" }, { height_m: 1 }, { target_id: "" }],
  });
  assert.equal(result.ok, true);
  assert.deepEqual(result.clarification.candidates.map((c) => c.targetId), ["good"]);
});

// --- 重提交构建 ---------------------------------------------------------------

test("clarification: 重提交只带 objective，不带 tasks", () => {
  const result = model.buildClarificationResubmission({
    missionId: "mission-1",
    objective: "对 verified-flight-route-001 做飞行验证，起飞后前往航点并降落",
    resolution: "resubmit_objective_without_tasks",
  });
  assert.equal(result.ok, true, JSON.stringify(result.violations));
  assert.equal(result.request.mission_id, "mission-1");
  assert.ok(result.request.objective.length > 0);
  // **关键**：绝不能带 tasks。带回去会再次触发 EXTERNAL_TASKS_FORBIDDEN。
  assert.ok(!("tasks" in result.request), `不该带 tasks：${JSON.stringify(result.request)}`);
});

test("clarification: 构建重提交时带 tasks 必须被拒，不能静默丢弃", () => {
  const result = model.buildClarificationResubmission({
    missionId: "mission-1",
    objective: "目标 A",
    resolution: "resubmit_objective_without_tasks",
    tasks: [{ task_id: "T1" }],
  });
  assert.equal(result.ok, false);
  assert.ok(result.violations.some((v) => v.code === "tasks_forbidden"));
});

test("clarification: objective 为空被拒", () => {
  for (const objective of ["", "   ", undefined, null]) {
    const result = model.buildClarificationResubmission({
      missionId: "mission-1", objective,
      resolution: "resubmit_objective_without_tasks",
    });
    assert.equal(result.ok, false, JSON.stringify(objective));
    assert.ok(result.violations.some((v) => v.code === "objective_required"));
  }
});

test("clarification: 不在 resolution 白名单里的解析方式被拒", () => {
  const result = model.buildClarificationResubmission({
    missionId: "mission-1", objective: "目标 A", resolution: "just_retry",
  });
  assert.equal(result.ok, false);
  assert.ok(result.violations.some((v) => v.code === "unsupported_resolution"));
});

test("clarification: 缺 mission_id 被拒（无法关联回原任务）", () => {
  const result = model.buildClarificationResubmission({
    missionId: "", objective: "目标 A", resolution: "resubmit_objective_without_tasks",
  });
  assert.equal(result.ok, false);
  assert.ok(result.violations.some((v) => v.code === "mission_id_required"));
});

// --- 把候选拼进 objective 的辅助 -------------------------------------------------

test("clarification: 选定候选可以拼出新的 objective，且带上实体 ID", () => {
  // 操作者点了"link-block-4-3-2-1"，界面据此生成一句明确的目标。
  // 关键在于**句子里必须出现实体 ID** —— 算法侧是按显式标签匹配的，
  // 拼一句"就是那栋高的"仍然会是歧义。
  const text = model.composeClarifiedObjective({
    originalObjective: "到最高的那栋楼旁边",
    selectedTargetId: "link-block-4-3-2-1",
  });
  assert.ok(text.includes("link-block-4-3-2-1"), text);
});

test("clarification: 没选候选时返回原句，不擅自改写", () => {
  const text = model.composeClarifiedObjective({
    originalObjective: "到最高的那栋楼旁边", selectedTargetId: "",
  });
  assert.equal(text, "到最高的那栋楼旁边");
});

test("clarification: 导出常量与算法侧的解析方式同名", () => {
  assert.equal(model.CLARIFICATION_RESOLUTIONS.resubmit_objective_without_tasks,
    "resubmit_objective_without_tasks");
});
