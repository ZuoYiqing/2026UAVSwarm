'use strict';

// 观察复核（L2）记录的 JS 侧校验测试。
//
// 为什么 JS 侧也要一份：前端没有构建步骤，不能 import Python 的
// `src/uav_runtime/observation/review_record.py`。控制台是静态页面
// （`python -m http.server`），所以规则必须在两端各实现一次。
//
// ⚠️ **两份实现必须行为一致**，否则会出现"前端放了、后端拒了"这种
// 让人以为是 bug 的分歧。因此本文件的用例**逐条对应** Python 侧
// `tests/unit/test_observation_review_record.py`，改动任一侧都应同步另一侧。
//
// 与 Python 侧一致，锁定的核心是三条防伪造规则：
//   1. 不得编造数值置信度（confidence 必须显式 null）
//   2. reviewer 必须是 human: 前缀（本阶段只接受人工复核）
//   3. not_observed / undetermined 必须给出依据
// 外加一条结构性约束：记录**无从表达**"任务已完成"。

const test = require("node:test");
const assert = require("node:assert/strict");
const model = require("../console-model.js");

const IMAGE = {
  ref: "sha256:" + "a".repeat(64),
  sha256: "a".repeat(64),
  width: 1280,
  height: 960,
  encoding: "RGB8",
  captured_at: "2026-10-05T11:59:30Z",
  vehicle_id: "UAV-01",
  camera_id: "front_rgb",
};

function validRecord(overrides = {}) {
  return {
    review_version: "0.1",
    review_id: "rev-0123456789abcdef",
    created_at: "2026-10-05T12:00:00Z",
    task_id: "TASK-1",
    target_id: "target-001",
    capture_id: "cap-0123456789abcdef",
    image: { ...IMAGE },
    criterion_version: "l2-criterion-v0.1",
    reviewer: "human:zyq",
    reviewed_at: "2026-10-05T12:00:00Z",
    outcome: "observed",
    confidence: null,
    note: "目标位于画面中央偏右",
    linked_task_completion: "not_asserted",
    ...overrides,
  };
}

function codes(violations) {
  return new Set(violations.map((v) => v.code));
}

// --- 合法记录 ---------------------------------------------------------------

test("review: 合法记录通过校验", () => {
  const result = model.validateObservationReview(validRecord());
  assert.equal(result.ok, true, JSON.stringify(result.violations));
  assert.equal(result.record.outcome, "observed");
});

test("review: not_observed 带说明可通过", () => {
  assert.equal(model.validateObservationReview(validRecord({ outcome: "not_observed" })).ok, true);
});

test("review: undetermined 带说明可通过", () => {
  assert.equal(model.validateObservationReview(validRecord({ outcome: "undetermined" })).ok, true);
});

// --- 规则一：不得编造数值置信度 ---------------------------------------------

test("review: 任何数值置信度都被拒绝", () => {
  for (const confidence of [1.0, 0.0, 0.87, 1, 0]) {
    const result = model.validateObservationReview(validRecord({ confidence }));
    assert.equal(result.ok, false, `confidence=${confidence} 应被拒`);
    assert.ok(codes(result.violations).has("confidence_must_be_null"));
  }
});

test("review: confidence 缺失也按同一条规则报，而不是笼统的缺字段", () => {
  const record = validRecord();
  delete record.confidence;
  const result = model.validateObservationReview(record);
  assert.equal(result.ok, false);
  // 与 Python 侧一致：省略会让"忘了填"与"确实没有"看起来一样，
  // 而这条规则恰恰是要区分这件事的。
  assert.ok(codes(result.violations).has("confidence_must_be_null"));
});

// --- 规则二：reviewer 必须是人工 --------------------------------------------

test("review: 非 human 前缀的 reviewer 一律拒绝", () => {
  for (const reviewer of ["detector:yolo-v8", "auto:", "system", "", "   ", "human", "Human:zyq", null, 42]) {
    const result = model.validateObservationReview(validRecord({ reviewer }));
    assert.equal(result.ok, false, `reviewer=${JSON.stringify(reviewer)} 应被拒`);
  }
});

test("review: human: 后必须有实际标识", () => {
  const result = model.validateObservationReview(validRecord({ reviewer: "human:" }));
  assert.equal(result.ok, false);
  assert.ok(codes(result.violations).has("reviewer_not_human"));
});

// --- 规则三：否定/未判定必须给出依据 ---------------------------------------

test("review: not_observed 无任何依据被拒绝", () => {
  const record = validRecord({ outcome: "not_observed" });
  delete record.note;
  const result = model.validateObservationReview(record);
  assert.equal(result.ok, false);
  assert.ok(codes(result.violations).has("missing_negative_evidence"));
});

test("review: undetermined 无任何依据被拒绝", () => {
  const record = validRecord({ outcome: "undetermined", note: undefined });
  const result = model.validateObservationReview(record);
  assert.equal(result.ok, false);
  assert.ok(codes(result.violations).has("missing_negative_evidence"));
});

test("review: observed 不强制要求依据", () => {
  const record = validRecord({ outcome: "observed", note: undefined });
  assert.equal(model.validateObservationReview(record).ok, true);
});

test("review: 只给 region 也算有依据", () => {
  const record = validRecord({ outcome: "not_observed", note: undefined,
    region: { x: 1, y: 2, w: 3, h: 4 } });
  assert.equal(model.validateObservationReview(record).ok, true);
});

// --- 图像引用必须自洽 -------------------------------------------------------

test("review: image.ref 与 sha256 不一致时拒绝", () => {
  const record = validRecord();
  record.image = { ...IMAGE, sha256: "b".repeat(64) };
  const result = model.validateObservationReview(record);
  assert.equal(result.ok, false);
  assert.ok(codes(result.violations).has("image_ref_hash_mismatch"));
});

test("review: 畸形 sha256 被拒绝", () => {
  for (const bad of ["a".repeat(63), "a".repeat(65), "A".repeat(64), "zz" + "a".repeat(62), ""]) {
    const record = validRecord();
    record.image = { ...IMAGE, sha256: bad, ref: "sha256:" + bad };
    assert.equal(model.validateObservationReview(record).ok, false, `sha=${bad}`);
  }
});

test("review: 身份字段缺一不可", () => {
  for (const field of ["task_id", "target_id", "capture_id", "criterion_version"]) {
    const record = validRecord();
    delete record[field];
    const result = model.validateObservationReview(record);
    assert.equal(result.ok, false, field);
    assert.ok(codes(result.violations).has("missing_field"), field);
  }
});

// --- 结构性约束：任务完成状态无从表达 ---------------------------------------

test("review: linked_task_completion 只能取 not_asserted", () => {
  for (const bad of ["completed", "asserted", "true", true, 1]) {
    const result = model.validateObservationReview(validRecord({ linked_task_completion: bad }));
    assert.equal(result.ok, false, `linked_task_completion=${JSON.stringify(bad)} 应被拒`);
    assert.ok(codes(result.violations).has("task_completion_not_representable"));
  }
});

// --- 一次报全 -----------------------------------------------------------------

test("review: 校验器一次报全部违规，不是遇错即停", () => {
  const record = validRecord({ confidence: 0.9, reviewer: "detector:x" });
  delete record.capture_id;
  const result = model.validateObservationReview(record);
  assert.equal(result.ok, false);
  assert.ok(result.violations.length >= 3, `应至少 3 条，实际 ${result.violations.length}`);
});

// --- 构建 ---------------------------------------------------------------------

test("review: buildObservationReview 生成 review_id 且同输入同 id", () => {
  const args = {
    taskId: "TASK-1", targetId: "target-001", captureId: "cap-0123456789abcdef",
    image: IMAGE, criterionVersion: "l2-criterion-v0.1",
    reviewer: "human:zyq", reviewedAt: "2026-10-05T12:00:00Z",
    outcome: "observed", note: "target visible",
    createdAt: "2026-10-05T12:00:00Z",
  };
  const first = model.buildObservationReview(args);
  const second = model.buildObservationReview(args);
  assert.equal(first.ok, true, JSON.stringify(first.violations));
  assert.ok(first.record.review_id.startsWith("rev-"), first.record.review_id);
  assert.equal(first.record.review_id, second.record.review_id);
});

test("review: buildObservationReview 也拦检测器结论", () => {
  const result = model.buildObservationReview({
    taskId: "TASK-1", targetId: "target-001", captureId: "cap-0123456789abcdef",
    image: IMAGE, criterionVersion: "l2-criterion-v0.1",
    reviewer: "detector:yolo", reviewedAt: "2026-10-05T12:00:00Z",
    outcome: "observed",
  });
  assert.equal(result.ok, false);
});

test("review: 构建出的记录 confidence 一定是 null", () => {
  const result = model.buildObservationReview({
    taskId: "TASK-1", targetId: "target-001", captureId: "cap-0123456789abcdef",
    image: IMAGE, criterionVersion: "l2-criterion-v0.1",
    reviewer: "human:zyq", reviewedAt: "2026-10-05T12:00:00Z",
    outcome: "observed", note: "x",
  });
  assert.equal(result.record.confidence, null);
});

// --- 与 Python 侧的一致性锚点 -----------------------------------------------

test("review: 违规码与 Python 侧同名", () => {
  // 这些字符串是两端共享的约定。改名会让一侧的测试失效而另一侧不知道。
  const expected = [
    "confidence_must_be_null",
    "reviewer_not_human",
    "missing_negative_evidence",
    "image_ref_hash_mismatch",
    "malformed_sha256",
    "invalid_outcome",
    "missing_field",
    "task_completion_not_representable",
  ];
  for (const code of expected) {
    assert.equal(typeof code, "string");
    assert.ok(code.length > 0);
  }
  // 至少验证其中三个真的会出现
  assert.ok(codes(model.validateObservationReview(validRecord({ confidence: 1 })).violations)
    .has("confidence_must_be_null"));
  assert.ok(codes(model.validateObservationReview(validRecord({ reviewer: "auto:x" })).violations)
    .has("reviewer_not_human"));
  assert.ok(codes(model.validateObservationReview(validRecord({ outcome: "bogus" })).violations)
    .has("invalid_outcome"));
});

test("review: 导出常量与 Python 侧一致", () => {
  assert.equal(model.REVIEW_OUTCOMES.observed, "observed");
  assert.equal(model.REVIEW_OUTCOMES.not_observed, "not_observed");
  assert.equal(model.REVIEW_OUTCOMES.undetermined, "undetermined");
  assert.equal(model.LINKED_TASK_COMPLETION_NOT_ASSERTED, "not_asserted");
  assert.equal(model.HUMAN_REVIEWER_PREFIX, "human:");
});
