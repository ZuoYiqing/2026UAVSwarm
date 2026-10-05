"use strict";

// 观察复核（L2）页面的测试。
//
// 页面逻辑与校验逻辑是两件事，所以分两个文件测：
//   · `observation-review.test.js` 测校验规则（纯函数，与 Python 侧对照）
//   · 本文件测**页面**：渲染、空态、提交路径、校验失败时展示什么
//
// 页面测试里最要紧的两条：
//   1. **校验不通过时不得渲染出记录 JSON** —— 否则操作者可能复制走一份不合法的记录
//   2. 页面上**不能出现"置信度"输入框**，且必须写明本阶段记录不能当验收证据

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const model = require("../console-model.js");

function harness() {
  const storage = new Map();
  const app = { innerHTML: "", addEventListener() {} };
  const context = vm.createContext({
    console,
    URL,
    crypto: require("node:crypto").webcrypto,
    localStorage: {
      getItem: (key) => storage.get(key),
      setItem: (key, value) => storage.set(key, value),
    },
    document: {
      getElementById: (id) => (id === "app" ? app : null),
      querySelector: () => null,
      activeElement: null,
    },
    window: {
      SwarmConsoleModel: model,
      location: { href: "http://127.0.0.1:5178/" },
      setTimeout() {},
      addEventListener() {},
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

function validDraft() {
  return {
    taskId: "TASK-1",
    targetId: "target-001",
    captureId: "cap-0123456789abcdef",
    criterionVersion: "l2-criterion-v0.1",
    reviewer: "human:zyq",
    vehicleId: "UAV-01",
    cameraId: "front_rgb",
    capturedAt: "2026-10-05T11:59:30Z",
    width: "1280",
    height: "960",
    encoding: "RGB8",
    imageRef: "sha256:" + "a".repeat(64),
    outcome: "observed",
    note: "目标位于画面中央偏右",
  };
}

// --- 渲染 ---------------------------------------------------------------------

test("observation page: 渲染空态且不抛出", () => {
  const h = harness();
  const html = h.run("observationPage()");
  assert.match(html, /观察复核/);
  assert.match(html, /尚未校验/);
});

test("observation page: 导航里有这一页，且路由已注册", () => {
  const h = harness();
  const nav = h.run("navItems.map(i => i[0]).join(',')");
  assert.ok(nav.includes("observation"), nav);
  assert.equal(h.run("typeof route"), "function");
  h.run("state.page = 'observation'");
  assert.match(h.run("route()"), /观察复核/);
});

test("observation page: 页面明确写出本阶段不能当验收证据", () => {
  const h = harness();
  const html = h.run("observationPage()");
  // 这条是必须的：不写清楚，操作者会把演练记录当验收证据。
  assert.match(html, /不能当验收证据/);
  assert.match(html, /CAPTURE/);
});

test("observation page: 没有置信度输入框", () => {
  const h = harness();
  const html = h.run("observationPage()");
  // 人工结论不伪造数值置信度 —— 界面上就不该给它入口。
  assert.ok(!/id="review-confidence"/.test(html), "不该有置信度输入框");
  assert.match(html, /不提供"置信度"输入框|不伪造数值置信度/);
});

test("observation page: 三个结论选项都在，且注明 not_observed 的含义", () => {
  const h = harness();
  const html = h.run("observationPage()");
  assert.match(html, /observed ——/);
  assert.match(html, /not_observed ——/);
  assert.match(html, /undetermined ——/);
  // 关键语义：否定不证明不存在
  assert.match(html, /不证明目标不存在/);
});

test("observation page: 提示 not_observed/undetermined 必须给依据", () => {
  const h = harness();
  const html = h.run("observationPage()");
  assert.match(html, /必须填写文字说明|必须给出 region 或 note/);
});

// --- 提交路径 -----------------------------------------------------------------

test("observation page: 合法草稿提交后生成记录并显示 JSON", () => {
  const h = harness();
  h.run(`state.reviewDraft = ${JSON.stringify(validDraft())}`);
  h.run("submitObservationReview()");
  assert.equal(h.run("state.reviewResult.ok"), true);
  assert.match(h.run("state.reviewResult.record.review_id"), /^rev-/);
  const html = h.run("observationPage()");
  assert.match(html, /校验通过/);
  assert.match(html, /review_id/);
});

test("observation page: 非法草稿不生成记录，且不渲染记录 JSON", () => {
  const h = harness();
  const draft = validDraft();
  draft.reviewer = "detector:yolo-v8"; // 本阶段只接受人工复核
  h.run(`state.reviewDraft = ${JSON.stringify(draft)}`);
  h.run("submitObservationReview()");
  assert.equal(h.run("state.reviewResult.ok"), false);

  const html = h.run("observationPage()");
  assert.match(html, /reviewer_not_human/);
  // 关键：不能给出可复制的记录 JSON —— 否则操作者会复制走一份不合法的记录
  assert.ok(!/"review_id"\s*:/.test(html), "校验失败时不得渲染记录 JSON");
  assert.match(html, /校验通过后在此显示记录 JSON/);
});

test("observation page: 校验失败时列出全部违规，不是只报第一条", () => {
  const h = harness();
  const draft = validDraft();
  draft.reviewer = "";
  draft.captureId = "";
  draft.imageRef = "sha256:" + "b".repeat(63);
  h.run(`state.reviewDraft = ${JSON.stringify(draft)}`);
  h.run("submitObservationReview()");
  const html = h.run("observationPage()");
  const count = h.run("state.reviewResult.violations.length");
  assert.ok(count >= 3, `应至少 3 条违规，实际 ${count}`);
  assert.match(html, /处不合法/);
});

test("observation page: not_observed 但没写依据会被拦", () => {
  const h = harness();
  const draft = validDraft();
  draft.outcome = "not_observed";
  draft.note = "";
  h.run(`state.reviewDraft = ${JSON.stringify(draft)}`);
  h.run("submitObservationReview()");
  assert.equal(h.run("state.reviewResult.ok"), false);
  assert.match(h.run("observationPage()"), /missing_negative_evidence/);
});

test("observation page: 构建出的记录 confidence 为 null", () => {
  const h = harness();
  h.run(`state.reviewDraft = ${JSON.stringify(validDraft())}`);
  h.run("submitObservationReview()");
  assert.equal(h.run("state.reviewResult.record.confidence"), null);
  assert.equal(h.run("state.reviewResult.record.linked_task_completion"), "not_asserted");
});

test("observation page: 草稿编辑不整页重渲染（避免丢光标）", () => {
  const h = harness();
  h.run("setReviewDraft('note', '正在输入')");
  assert.equal(h.run("state.reviewDraft.note"), "正在输入");
});

test("observation page: 页面里不出现 markdown 星号（pageTitle 不解析 markdown）", () => {
  const h = harness();
  const html = h.run("observationPage()");
  // 回归：副标题最初写成"对采集图像的**人工**判定记录"，而 `pageTitle()` 用
  // `esc()` 输出纯文本 —— 星号**原样显示**在页面上（浏览器验证时看到的）。
  // 这类缺陷单测抓不到（HTML 里确实有那句话），只有真看页面才发现。
  assert.ok(!html.includes("**"), `页面里不该有 markdown 星号：${html.slice(0, 200)}`);
});

test("observation page: 所有 pageTitle 的文本参数都不含 markdown 星号", () => {
  const source = fs.readFileSync(path.join(__dirname, "../app.js"), "utf8");
  const pattern = /pageTitle\(\s*"([^"]*)"\s*,\s*"([^"]*)"/g;
  const offenders = [];
  let match = pattern.exec(source);
  while (match) {
    if (match[1].includes("**") || match[2].includes("**")) offenders.push(match[0].slice(0, 80));
    match = pattern.exec(source);
  }
  assert.deepEqual(offenders, [], "pageTitle 用 esc() 输出纯文本，参数里不能有 markdown 星号");
});

test("observation page: 清空会清掉草稿与结果", () => {
  const h = harness();
  h.run(`state.reviewDraft = ${JSON.stringify(validDraft())}`);
  h.run("submitObservationReview()");
  h.run("clearObservationReview()");
  assert.equal(h.run("JSON.stringify(state.reviewDraft)"), "{}");
  assert.equal(h.run("state.reviewResult"), null);
});

// --- 导入校验 -----------------------------------------------------------------

test("observation page: 导入非法 JSON 给出可读错误", () => {
  const h = harness();
  h.run("state.reviewImportRaw = '{ not json'");
  h.run("validateImportedObservationReview()");
  assert.equal(h.run("state.reviewImportResult.ok"), false);
  assert.match(h.run("state.reviewImportResult.violations[0].code"), /invalid_json/);
});

test("observation page: 导入空输入被提示", () => {
  const h = harness();
  h.run("state.reviewImportRaw = '   '");
  h.run("validateImportedObservationReview()");
  assert.equal(h.run("state.reviewImportResult.violations[0].code"), "empty_input");
});

test("observation page: 导入被篡改的记录（事后补置信度）会被拒", () => {
  const h = harness();
  const built = model.buildObservationReview({
    taskId: "TASK-1", targetId: "target-001", captureId: "cap-0123456789abcdef",
    image: {
      ref: "sha256:" + "a".repeat(64), sha256: "a".repeat(64), width: 1280, height: 960,
      encoding: "RGB8", captured_at: "2026-10-05T11:59:30Z",
      vehicle_id: "UAV-01", camera_id: "front_rgb",
    },
    criterionVersion: "l2-criterion-v0.1", reviewer: "human:zyq",
    reviewedAt: "2026-10-05T12:00:00Z", outcome: "observed", note: "x",
  });
  assert.equal(built.ok, true);
  const tampered = { ...built.record, confidence: 0.99 };
  h.run(`state.reviewImportRaw = ${JSON.stringify(JSON.stringify(tampered))}`);
  h.run("validateImportedObservationReview()");
  assert.equal(h.run("state.reviewImportResult.ok"), false);
  assert.match(h.run("observationPage()"), /confidence_must_be_null/);
});
