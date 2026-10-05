"use strict";

// 澄清待办页面的测试。
//
// 分两个文件测：`clarification.test.js` 测纯逻辑（与算法侧形状对照），
// 本文件测**页面**：渲染、解析、选定候选、生成重提交。
//
// 页面测试里最要紧的三条：
//   1. **每个澄清都必须显式给出"下一步改哪里"** —— 否则操作者会陷入
//      "提交→被拒→再提交"的循环，而且从界面看不出原因
//   2. **不给 tasks 输入口** —— 算法侧要求任务清单由目标派生
//   3. 普通拒绝**不能**被呈现成需要操作者回答的问题

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const model = require("../console-model.js");

function harness() {
  const app = { innerHTML: "", addEventListener() {} };
  const context = vm.createContext({
    console, URL, crypto: require("node:crypto").webcrypto,
    localStorage: { getItem: () => null, setItem() {} },
    document: {
      getElementById: (id) => (id === "app" ? app : null),
      querySelector: () => null, activeElement: null,
    },
    window: {
      SwarmConsoleModel: model, location: { href: "http://127.0.0.1:5178/" },
      setTimeout() {}, addEventListener() {},
    },
    setInterval() {},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../app.js"), "utf8"), context);
  vm.runInContext(`
    syncRuntimeEvents = async () => {};
    syncRuntimeState = async () => {};
    state.apiStatus = "live";
  `, context);
  return { context, app, run: (code) => vm.runInContext(code, context) };
}

const AMBIGUOUS = {
  status: "clarification_required", accepted: false,
  reason_code: "AMBIGUOUS_HIGHEST_BUILDING", matched_text: "最高的那栋楼",
  candidates: [
    { target_id: "link-block-4-3-2-1", height_m: 52.0, center_north_m: 350.0, center_east_m: 53.2 },
    { target_id: "link-block-4-3-3-2", height_m: 52.0, center_north_m: 432.0, center_east_m: 179.8 },
  ],
  clarification_question: "最高建筑并列；请指定目标建筑 ID。",
};

const TASKS_FORBIDDEN = {
  reason_code: "EXTERNAL_TASKS_FORBIDDEN",
  clarification_request: {
    audience: "originating_operator", mission_id: "mission-1",
    conflicting_fields: ["objective", "tasks"],
    question: "请确认原始任务目标并重新提交；任务清单将由目标派生。",
    resolution: "resubmit_objective_without_tasks",
  },
};

// --- 渲染 ---------------------------------------------------------------------

test("clarification page: 渲染空态且不抛出", () => {
  const h = harness();
  const html = h.run("clarificationPage()");
  assert.match(html, /澄清待办/);
  assert.match(html, /尚未解析/);
});

test("clarification page: 导航与路由都已注册", () => {
  const h = harness();
  assert.ok(h.run("navItems.map(i => i[0]).join(',')").includes("clarification"));
  h.run("state.page = 'clarification'");
  assert.match(h.run("route()"), /澄清待办/);
});

test("clarification page: 页面里没有 tasks 输入口", () => {
  const h = harness();
  const html = h.run("clarificationPage()");
  assert.ok(!/id="[^"]*tasks/.test(html), "不该给 tasks 输入口");
  assert.match(html, /重提交不带 tasks/);
});

test("clarification page: 页面说明算法侧为什么不猜", () => {
  const h = harness();
  assert.match(h.run("clarificationPage()"), /算法侧不会猜|猜错等于飞错目标/);
});

test("clarification page: 无 markdown 星号", () => {
  const h = harness();
  assert.ok(!h.run("clarificationPage()").includes("**"));
});

// --- 解析 ---------------------------------------------------------------------

test("clarification page: 解析目标歧义，列出候选与下一步", () => {
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(AMBIGUOUS))}`);
  h.run("parseClarification()");
  assert.equal(h.run("state.clarificationParsed.ok"), true);

  const html = h.run("clarificationPage()");
  assert.match(html, /link-block-4-3-2-1/);
  assert.match(html, /link-block-4-3-3-2/);
  assert.match(html, /目标歧义/);
  // 关键：必须告诉操作者下一步改哪里，否则会陷入提交循环
  assert.match(html, /从下列候选里指定一个目标实体/);
  // 候选几何要显示 —— 操作者靠它区分两栋并列最高的楼
  assert.match(html, /52/);
});

test("clarification page: 解析带 tasks 的请求，指出要去掉 tasks", () => {
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(TASKS_FORBIDDEN))}`);
  h.run("parseClarification()");
  const html = h.run("clarificationPage()");
  assert.match(html, /请求形态不合格/);
  assert.match(html, /去掉 tasks/);
  assert.match(html, /EXTERNAL_TASKS_FORBIDDEN/);
});

test("clarification page: mission_id 从澄清请求里带出来", () => {
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(TASKS_FORBIDDEN))}`);
  h.run("parseClarification()");
  assert.equal(h.run("state.clarifyMissionId"), "mission-1");
});

test("clarification page: 非法 JSON 给出可读错误", () => {
  const h = harness();
  h.run("state.clarificationRaw = '{ not json'");
  h.run("parseClarification()");
  assert.equal(h.run("state.clarificationParsed.violations[0].code"), "invalid_json");
});

test("clarification page: 空输入被提示", () => {
  const h = harness();
  h.run("state.clarificationRaw = '  '");
  h.run("parseClarification()");
  assert.equal(h.run("state.clarificationParsed.violations[0].code"), "empty_input");
});

test("clarification page: 普通拒绝不被当成需要回答的问题", () => {
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify({ status: "rejected", reason_code: "REQUEST_REJECTED" }))}`);
  h.run("parseClarification()");
  assert.equal(h.run("state.clarificationParsed.ok"), false);
  assert.match(h.run("clarificationPage()"), /not_a_clarification/);
});

// --- 选定候选与重提交 -----------------------------------------------------------

test("clarification page: 点候选把实体 ID 写进 objective", () => {
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(AMBIGUOUS))}`);
  h.run("parseClarification()");
  h.run("state.clarifyObjective = '到最高的那栋楼旁边'");
  h.run("selectClarificationCandidate('link-block-4-3-2-1')");
  const objective = h.run("state.clarifyObjective");
  // 句子里必须出现实体 ID —— 算法侧按显式标签匹配
  assert.ok(objective.includes("link-block-4-3-2-1"), objective);
  assert.ok(objective.includes("到最高的那栋楼旁边"), objective);
});

test("clarification page: 生成的重提交请求不含 tasks", () => {
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(AMBIGUOUS))}`);
  h.run("parseClarification()");
  // 目标歧义那条澄清**不带 mission_id**（scene_binding 的返回里没有这个字段），
  // 所以操作者必须自己填 —— 界面上有专门提示（见下一条测试）。
  h.run("state.clarifyMissionId = 'mission-1'");
  h.run("state.clarifyObjective = '前往 link-block-4-3-2-1 做飞行验证并降落'");
  h.run("buildClarificationResubmit()");
  assert.equal(h.run("state.clarificationResubmitResult.ok"), true,
    JSON.stringify(h.run("state.clarificationResubmitResult.violations")));

  const html = h.run("clarificationPage()");
  // JSON 在 HTML 里经 esc() 转义，引号是 &quot; 而不是 "。
  // （第一版断言写成 /"objective"/ 因此永远不匹配 —— 是测试写错，不是实现错。）
  assert.match(html, /&quot;objective&quot;/);
  assert.match(html, /&quot;mission_id&quot;/);
  assert.ok(!/&quot;tasks&quot;\s*:/.test(html), "重提交请求里不该出现 tasks");
});

test("clarification page: 澄清不带 mission_id 时明确提示要自己填", () => {
  // 回归：最初界面对此没有任何提示，操作者填完 objective、点"生成"，
  // 只会看到 mission_id_required，却不知道这个值该从哪来。
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(AMBIGUOUS))}`);
  h.run("parseClarification()");
  assert.equal(h.run("state.clarifyMissionId"), "", "歧义样例本来就不该带 mission_id");

  const html = h.run("clarificationPage()");
  assert.match(html, /需要你填 mission_id/);
  // 并且要说清为什么不替他编一个
  assert.match(html, /不会替你编一个|不存在的任务/);
});

test("clarification page: 澄清自带的 mission_id 会预填，且不再提示", () => {
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(TASKS_FORBIDDEN))}`);
  h.run("parseClarification()");
  assert.equal(h.run("state.clarifyMissionId"), "mission-1");
  assert.ok(!h.run("clarificationPage()").includes("需要你填 mission_id"));
});

test("clarification page: 澄清自带的 objective 会预填，选定候选后保留原句", () => {
  // scene_binding 的返回里带 `objective`（原始那句话）。预填它是为了让"选定候选"
  // 能**在保留原句的前提下**补上实体 ID —— 否则操作者得重新手打一遍，
  // 而句子里往往正是需要保留的上下文（"最高的那栋楼旁边"）。
  const h = harness();
  const withObjective = { ...AMBIGUOUS, objective: "到最高的那栋楼旁边" };
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(withObjective))}`);
  h.run("parseClarification()");
  assert.equal(h.run("state.clarifyObjective"), "到最高的那栋楼旁边");

  h.run("selectClarificationCandidate('link-block-4-3-2-1')");
  const objective = h.run("state.clarifyObjective");
  assert.ok(objective.includes("到最高的那栋楼旁边"), objective);
  assert.ok(objective.includes("link-block-4-3-2-1"), objective);
});

test("clarification page: 非歧义澄清不会用 original objective 覆盖已填内容", () => {
  const h = harness();
  h.run(`state.clarificationRaw = ${JSON.stringify(JSON.stringify(TASKS_FORBIDDEN))}`);
  h.run("parseClarification()");
  // 带 tasks 的那条澄清没有 objective 字段，预填结果应为空串而不是 undefined
  assert.equal(h.run("state.clarifyObjective"), "");
});

test("clarification page: objective 为空时不生成重提交，并给出原因", () => {
  const h = harness();
  h.run("state.clarifyMissionId = 'mission-1'");
  h.run("state.clarifyObjective = ''");
  h.run("buildClarificationResubmit()");
  assert.equal(h.run("state.clarificationResubmitResult.ok"), false);
  assert.match(h.run("clarificationPage()"), /objective_required/);
});

test("clarification page: 示例按钮能填入可用样例", () => {
  const h = harness();
  h.run("useClarificationSample('ambiguous')");
  assert.match(h.run("state.clarificationRaw"), /AMBIGUOUS_HIGHEST_BUILDING/);
  // 示例要贴近 scene_binding 的真实返回：带 objective，不带 mission_id。
  // 否则示例本身就教不出正确的操作流程。
  assert.match(h.run("state.clarificationRaw"), /objective/);
  h.run("parseClarification()");
  assert.equal(h.run("state.clarificationParsed.ok"), true);
  assert.equal(h.run("state.clarifyObjective"), "到最高的那栋楼旁边");
  assert.equal(h.run("state.clarifyMissionId"), "");

  h.run("useClarificationSample('tasks')");
  assert.match(h.run("state.clarificationRaw"), /EXTERNAL_TASKS_FORBIDDEN/);
  h.run("parseClarification()");
  assert.equal(h.run("state.clarificationParsed.ok"), true);
  assert.equal(h.run("state.clarifyMissionId"), "mission-1");
});
