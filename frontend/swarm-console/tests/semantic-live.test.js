"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const read = filename => fs.readFileSync(path.join(root, filename), "utf8");
const endpoint = "http://127.0.0.1:18118/lab/semantic-preview";
const preview = JSON.parse(read("evidence/semantic-preview/higher-12.preview.json"));
// Recorded evidence is used only as an explicitly mocked HTTP response in these tests.
const wrapper = {
  service: "uavswarm_lab_semantic_preview", api_version: "0.1", mode: "live",
  execution_authorized: false, elapsed_ms: 75, preview,
  evidence_json: read("evidence/semantic-preview/higher-12.raw.json"),
};
const response = (payload, status = 200) => ({
  status, ok: status === 200, text: async () => JSON.stringify(payload),
});

function harness() {
  const events = {}, timers = new Map();
  const calls = { lab: [], runtime: [], frame: [], static: [] };
  const nodes = {
    app: { innerHTML: "", addEventListener(name, handler) { events[name] = handler; } },
    "semantic-live-result": { innerHTML: "" },
    "semantic-preview-result": { innerHTML: "" },
    "semantic-lab-health": { innerHTML: "" },
    "semantic-live-objective": { value: "" },
    "semantic-live-example": {}, "semantic-live-submit": {}, "semantic-lab-check": {},
    "simulation-frame": { contentWindow: { postMessage(...args) { calls.frame.push(args); } } },
  };
  let reply = () => response(wrapper);
  const context = vm.createContext({
    URL, console, AbortController, TextEncoder, crypto: crypto.webcrypto,
    setTimeout(callback) { const id = {}; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
    setInterval() {},
    fetch: async (url, options) => {
      if (url.startsWith(endpoint)) {
        calls.lab.push({ url, options });
        return reply(url, options);
      }
      calls.static.push(url);
      return { ok: true, text: async () => read(url) };
    },
    localStorage: { getItem: () => null, setItem() {} },
    document: { getElementById: id => nodes[id] ?? null, querySelector: () => null },
    window: {
      location: { href: "http://127.0.0.1:5178/" }, addEventListener() {},
      SwarmSemanticPreview: require("../semantic-preview.js"),
      SwarmConsoleModel: require("../console-model.js"),
      SwarmRuntimeApi: { health() { calls.runtime.push("health"); return Promise.reject(new Error("Test Runtime offline")); } },
    },
  });
  const run = code => vm.runInContext(code, context);
  run(read("semantic-preview-api.js"));
  run(read("app.js"));
  const click = attribute => events.click({ target: {
    closest: selector => selector === `[${attribute}]` ? {} : null,
  } });
  const fill = value => {
    nodes["semantic-live-objective"].value = value;
    return events.input({ target: {
      value, hasAttribute: attribute => attribute === "data-semantic-live-objective",
    } });
  };
  return { run, nodes, calls, timers, fill, click, reply: value => { reply = value; } };
}

test("Lab health never requests inference or presents the model as online", async () => {
  const h = harness();
  h.reply(() => response({ ...wrapper, status: "ready", model_status: "not_checked" }));
  await h.click("data-semantic-health");
  assert.equal(h.calls.lab.length, 1);
  assert.equal(h.calls.lab[0].url, endpoint + "/health");
  assert.equal(h.calls.lab[0].options.method, "GET");
  assert.equal(h.calls.lab[0].options.body, undefined);
  assert.match(h.nodes["semantic-lab-health"].innerHTML, /Lab 可接收请求 · 模型状态未检查/);
  assert.doesNotMatch(h.nodes["semantic-live-result"].innerHTML, /已绑定/);
});

test("live inference posts only the original objective and reuses preview rendering in planning and twin", async () => {
  const h = harness(), baseline = h.calls.runtime.slice();
  h.fill(preview.objective);
  await h.click("data-semantic-infer");
  const request = h.calls.lab[0];
  assert.equal(request.url, endpoint);
  assert.equal(request.options.method, "POST");
  assert.deepEqual(JSON.parse(request.options.body), { objective: preview.objective });
  assert.equal(request.options.redirect, "error");
  const liveHtml = h.nodes["semantic-live-result"].innerHTML;
  assert.match(liveHtml, /本地实时推理/);
  assert.match(liveHtml, /Lab 耗时 75 ms/);
  assert.match(liveHtml, /本次模型响应/);
  assert.match(liveHtml, /模型原始回复/);
  assert.match(liveHtml, /已绑定.*MODEL_CHOICE_EVIDENCE_MATCH/);
  assert.match(liveHtml, /原证据 SHA-256（已核对）/);
  assert.ok(liveHtml.includes(preview.source.evidence_sha256));
  assert.ok(liveHtml.includes(preview.objective));
  assert.doesNotMatch(liveHtml, /模型实测回放/);

  await h.run('loadSemanticSample("higher-2.preview.json")');
  assert.match(h.nodes["semantic-preview-result"].innerHTML, /录制证据回放/);
  assert.match(h.nodes["semantic-preview-result"].innerHTML, /待澄清/);
  assert.equal(h.nodes["semantic-live-result"].innerHTML, liveHtml);
  const imported = h.run("JSON.stringify(state.semanticPreview.record)");
  await h.run(`loadSemanticPreview(async () => ${JSON.stringify(imported)}, "import.preview.json")`);
  assert.match(h.nodes["semantic-preview-result"].innerHTML, /本地文件导入/);
  assert.match(h.nodes["semantic-preview-result"].innerHTML, /导入模型记录（文件标注）/);

  h.run('state.page="planning"');
  assert.match(h.run("route()"), /本地试推理/);
  assert.doesNotMatch(h.run("route()"), /<iframe/);
  h.run('state.page="twin"');
  assert.equal((h.run("route()").match(/<iframe /g) ?? []).length, 1);
  assert.match(h.run("route()"), /Lab 耗时 75 ms/);
  assert.deepEqual(h.calls.runtime, baseline);
  assert.deepEqual(h.calls.frame, []);
});

test("HTTP 422, 429, 503, 504 and 502 clear the last live binding without loading recorded evidence", async () => {
  const h = harness();
  h.fill(preview.objective);
  for (const [status, reason] of [
    [422, "UNSUPPORTED_PREVIEW_OBJECTIVE"], [429, "PREVIEW_BUSY"], [503, "MODEL_UNAVAILABLE"],
    [504, "MODEL_TIMEOUT"], [502, "MODEL_RESPONSE_REJECTED"],
  ]) {
    h.reply(() => response(wrapper));
    await h.click("data-semantic-infer");
    assert.match(h.nodes["semantic-live-result"].innerHTML, /已绑定/);
    h.reply(() => response({ error: { reason_code: reason } }, status));
    await h.click("data-semantic-infer");
    const html = h.nodes["semantic-live-result"].innerHTML;
    assert.ok(html.includes(`HTTP ${status} · ${reason}`));
    assert.doesNotMatch(html, /已绑定|link-block-4-3-2-0|模型原始回复/);
    assert.equal(h.nodes["semantic-live-submit"].disabled, false);
  }
  assert.deepEqual(h.calls.static, []);
  assert.deepEqual(h.calls.frame, []);
});

test("a live semantic abstention displays its candidates and never retains a preceding binding", async () => {
  const h = harness();
  h.fill(preview.objective);
  await h.click("data-semantic-infer");
  for (const tag of ["higher-2", "higher-27"]) {
    const candidate = JSON.parse(read(`evidence/semantic-preview/${tag}.preview.json`));
    h.fill(candidate.objective);
    h.reply(() => response({ ...wrapper, preview: candidate,
      evidence_json: read(`evidence/semantic-preview/${tag}.raw.json`) }));
    await h.click("data-semantic-infer");
    assert.match(h.nodes["semantic-live-result"].innerHTML, /本地实时推理/);
    assert.match(h.nodes["semantic-live-result"].innerHTML, /待澄清.*MODEL_CHOICE_REQUIRES_REVIEW/);
    assert.match(h.nodes["semantic-live-result"].innerHTML, /semantic-preview-entities/);
    assert.doesNotMatch(h.nodes["semantic-live-result"].innerHTML, /已绑定|原文依据/);
  }
});

test("live wrapper rejects authorization, mismatched objectives and evidence before rendering bindings", async () => {
  const h = harness();
  h.fill(preview.objective);
  for (const payload of [
    { ...wrapper, execution_authorized: true },
    { ...wrapper, execution_authorized: undefined },
    { ...wrapper, mode: "replay" },
    { ...wrapper, elapsed_ms: -1 },
    { ...wrapper, preview: { ...preview, execution_authorized: true } },
    { ...wrapper, preview: { ...preview, objective: "another objective" } },
    { ...wrapper, evidence_json: wrapper.evidence_json + " " },
    { ...wrapper, preview: { ...preview, scope: { ...preview.scope, model_response: '{"choice":"2"}' } } },
  ]) {
    h.reply(() => response(payload));
    await h.click("data-semantic-infer");
    assert.match(h.nodes["semantic-live-result"].innerHTML, /LAB_RESPONSE_INVALID|LAB_EVIDENCE_MISMATCH/);
    assert.doesNotMatch(h.nodes["semantic-live-result"].innerHTML, /已绑定|原文依据/);
  }
});

test("one live request runs at a time and timeout covers reading its body", async () => {
  const h = harness();
  h.fill(preview.objective);
  let finish;
  h.reply(() => new Promise(resolve => { finish = resolve; }));
  const first = h.click("data-semantic-infer");
  await h.click("data-semantic-infer");
  assert.equal(h.calls.lab.length, 1);
  assert.equal(h.nodes["semantic-live-submit"].disabled, true);
  assert.match(h.nodes["semantic-live-result"].innerHTML, /正在等待本次模型响应/);
  finish(response(wrapper));
  await first;
  assert.match(h.nodes["semantic-live-result"].innerHTML, /已绑定/);
  h.fill("修改原话");
  assert.doesNotMatch(h.nodes["semantic-live-result"].innerHTML, /已绑定/);

  h.reply((url, options) => ({ status: 200, ok: true, text: () => new Promise((resolve, reject) => {
    if (options.signal.aborted) reject(new Error("Test body already aborted"));
    else options.signal.addEventListener("abort", () => reject(new Error("Test body aborted")));
  }) }));
  const stalled = h.click("data-semantic-infer");
  await Promise.resolve();
  for (const callback of h.timers.values()) callback();
  await stalled;
  assert.match(h.nodes["semantic-live-result"].innerHTML, /LAB_TIMEOUT/);
  assert.equal(h.nodes["semantic-live-submit"].disabled, false);
  assert.equal(h.timers.size, 0);
});
