"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const model = require("../semantic-preview.js");

const root = path.join(__dirname, "..");
const read = filename => fs.readFileSync(path.join(root, filename), "utf8");
const directory = "evidence/semantic-preview/";
const clarifyFile = "01-clarification.preview.json";
const boundFile = "02-clarified.preview.json";
const boundText = read(directory + boundFile);
const bound = JSON.parse(boundText);
const unknown = {
  ...bound,
  status: "unknown",
  bindings: [],
  reason_code: "TEST_NO_CATALOG_EVIDENCE",
};

function harness() {
  const events = {};
  const calls = { runtime: [], frame: [], static: [] };
  const app = { innerHTML: "", addEventListener(name, callback) { events[name] = callback; } };
  const result = { innerHTML: "" };
  const frame = { contentWindow: { postMessage(...args) { calls.frame.push(args); } } };
  const nodes = { app, "semantic-preview-result": result, "simulation-frame": frame };
  const context = vm.createContext({
    URL, console,
    fetch: async url => {
      calls.static.push(url);
      return { ok: true, text: async () => read(url) };
    },
    document: {
      getElementById: id => nodes[id] ?? null,
      querySelector: () => null,
    },
    localStorage: { getItem: () => null, setItem() {} },
    window: {
      location: { href: "http://127.0.0.1:5178/" },
      SwarmConsoleModel: require("../console-model.js"),
      SwarmSemanticPreview: model,
      SwarmRuntimeApi: new Proxy({}, {
        get: (_, key) => () => {
          calls.runtime.push(key);
          if (key === "health") return Promise.reject(new Error("No Runtime in this test"));
        },
      }),
      addEventListener() {},
    },
    setInterval() {},
  });
  const run = js => vm.runInContext(js, context);
  run(read("app.js"));
  const chooseSample = file => events.click({
    target: { closest: selector => selector === "[data-semantic-sample]" ? { dataset: { semanticSample: file } } : null },
  });
  const importFile = (name, text) => events.change({
    target: { files: [{ name, text }], value: name, hasAttribute: attr => attr === "data-semantic-file" },
  });
  const chooseModelReplay = file => events.change({
    target: { value: file, hasAttribute: attr => attr === "data-semantic-model-sample" },
  });
  return { run, calls, result, nodes, chooseSample, importFile, chooseModelReplay };
}

test("refreshing the planning page updates vehicle rows without replacing replay controls", () => {
  const h = harness();
  h.nodes["slot-content"] = { firstElementChild: {}, innerHTML: "existing controls" };
  h.nodes["vehicle-table-body"] = { innerHTML: "stale rows" };
  h.nodes["vehicle-table-empty"] = { hidden: true };
  h.run('state.page = state.renderedPage = "planning"; state.fleet = []; renderRegions()');
  assert.equal(h.nodes["slot-content"].innerHTML, "existing controls");
  assert.equal(h.nodes["vehicle-table-body"].innerHTML, "");
  assert.equal(h.nodes["vehicle-table-empty"].hidden, false);
});

test("packaged previews retain the hashes of their original evidence", () => {
  for (const tag of ["01-clarification", "02-clarified", "higher-12", "higher-2", "higher-27"]) {
    const p = model.parse(read(directory + tag + ".preview.json"));
    assert.ok(p.record, p.error);
    const raw = fs.readFileSync(path.join(root, directory, p.record.source.evidence_file));
    assert.equal(p.record.source.evidence_sha256, crypto.createHash("sha256").update(raw).digest("hex"));
  }
});

test("recorded-model selector displays the actual response and cannot run the model or dispatch", async () => {
  const h = harness();
  const baseline = h.calls.runtime.slice();
  h.run('state.page = "twin"');
  assert.match(h.run("route()"), /模型实测回放（不触发推理）/);
  for (const [tag, expected, status] of [
    ["higher-12", "link-block-4-3-2-0", "bound"],
    ["higher-2", "link-block-4-3-3-0", "clarify"],
    ["higher-27", "unknown", "clarify"],
  ]) {
    const file = tag + ".preview.json";
    await h.chooseModelReplay(file);
    const p = JSON.parse(read(directory + file));
    const raw = JSON.parse(read(directory + p.source.evidence_file));
    assert.equal(p.source.model_executed, true);
    assert.equal(p.scope.model_response, raw.model_trace.model_raw_response);
    assert.equal(raw.expected, expected);
    assert.equal(p.status, status);
    assert.match(h.result.innerHTML, /模型实测回放（文件标注） · qwen3.5-0.8b-q4-lab/);
    assert.match(h.result.innerHTML, /模型原始回复/);
    if (status === "clarify") {
      assert.match(h.result.innerHTML, /模型选项与目录规则不一致，没有绑定/);
      assert.doesNotMatch(h.result.innerHTML, /已绑定|原文依据/);
      assert.deepEqual(p.bindings, []);
    } else {
      assert.match(h.result.innerHTML, /目录规则一致/);
      assert.deepEqual(p.bindings.map(row => row.entity_id), [expected]);
    }
  }
  await h.chooseModelReplay("../unlisted.json");
  assert.deepEqual(h.calls.static, ["./" + directory + "higher-12.preview.json",
    "./" + directory + "higher-2.preview.json", "./" + directory + "higher-27.preview.json"]);
  assert.deepEqual(h.calls.runtime, baseline);
  assert.deepEqual(h.calls.frame, []);
});

test("semantic preview validates status, schema and explicit absence of execution authority", () => {
  assert.equal(model.parse(read(directory + clarifyFile)).record.status, "clarify");
  assert.equal(model.parse(boundText).record.status, "bound");
  assert.equal(model.parse(JSON.stringify(unknown)).record.status, "unknown");

  for (const input of [
    "{", "null", '{"status":"grounded_requires_planning","execution_ready":false}',
    JSON.stringify({ ...bound, schema_version: "0.2" }),
    JSON.stringify({ ...bound, execution_authorized: true }),
    JSON.stringify({ ...bound, execution_authorized: undefined }),
    JSON.stringify({ ...bound, status: "unknown" }),
    JSON.stringify({ ...bound, bindings: [{ ...bound.bindings[0], evidence: "not in the objective" }] }),
  ]) {
    assert.ok(model.parse(input).error, input);
  }
});

test("semantic preview reuses evidence on the planning and twin pages without Runtime or iframe messages", async () => {
  const h = harness();
  const runtimeBefore = h.calls.runtime.slice();
  h.run('state.page = "planning"');
  assert.match(h.run("route()"), /离线算法证据 · 只读预览/);
  assert.doesNotMatch(h.run("route()"), /<iframe/);

  await h.chooseSample(clarifyFile);
  const clarifiedQuestion = h.result.innerHTML;
  assert.match(clarifiedQuestion, /待澄清.*AMBIGUOUS_HIGHEST_BUILDING/);
  assert.match(clarifiedQuestion, /simple_recon_v0_1 \/ simple_recon_v0_1-map-1/);
  assert.match(clarifiedQuestion, /请标记最高的那栋楼。/);
  assert.match(clarifiedQuestion, /link-block-4-3-2-1/);
  assert.match(clarifiedQuestion, /link-block-4-3-3-2/);
  assert.equal((clarifiedQuestion.match(/52 m/g) ?? []).length, 2);

  h.run('state.page = "twin"');
  const twin = h.run("route()");
  assert.equal((twin.match(/<iframe /g) ?? []).length, 1);
  assert.match(twin, /id="simulation-frame"/);
  assert.match(twin, /AMBIGUOUS_HIGHEST_BUILDING/);

  await h.chooseSample(boundFile);
  const boundResult = h.result.innerHTML;
  assert.match(boundResult, /已绑定.*ROUTE_PLANNING_REQUIRED/);
  assert.match(boundResult, /原文依据 link-block-4-3-2-1/);
  assert.match(boundResult, /离线规则验证 · 模型未运行/);
  assert.doesNotMatch(boundResult, /link-block-4-3-3-2|ActionRequest/);
  assert.ok(boundResult.includes(bound.source.evidence_sha256));
  assert.ok(boundResult.includes(bound.source.catalog_content_sha256));

  await h.importFile("test-only-unknown.preview.json", async () => JSON.stringify({
    ...unknown,
    scope: { required: ["<b>本地限定条件</b>"] },
  }));
  assert.match(h.result.innerHTML, /未知.*TEST_NO_CATALOG_EVIDENCE/);
  assert.match(h.result.innerHTML, /&lt;b&gt;本地限定条件&lt;\/b&gt;/);
  assert.doesNotMatch(h.result.innerHTML, /semantic-preview-entities/);
  assert.deepEqual(h.calls.runtime, runtimeBefore);
  assert.deepEqual(h.calls.frame, []);
  assert.deepEqual(h.calls.static, ["./" + directory + clarifyFile, "./" + directory + boundFile]);
});

test("new file clears old bindings immediately and ignores a late result after a failed import", async () => {
  const h = harness();
  await h.chooseSample(boundFile);
  let finishRead;
  const pending = h.importFile("slow.preview.json", () => new Promise(resolve => { finishRead = resolve; }));
  assert.match(h.result.innerHTML, /正在读取 slow.preview.json/);
  assert.doesNotMatch(h.result.innerHTML, /已绑定|link-block-4-3-2-1/);

  await h.importFile("<invalid>.raw.json", async () => "{");
  assert.match(h.result.innerHTML, /&lt;invalid&gt;.raw.json：无法解析 JSON/);
  finishRead(boundText);
  await pending;
  assert.doesNotMatch(h.result.innerHTML, /已绑定|link-block-4-3-2-1/);
  assert.match(h.result.innerHTML, /无法解析 JSON/);

  await h.chooseSample(clarifyFile);
  assert.match(h.result.innerHTML, /待澄清/);
  assert.doesNotMatch(h.result.innerHTML, /无法解析 JSON/);
});
