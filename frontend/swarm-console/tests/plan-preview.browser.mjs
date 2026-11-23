import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve, sep } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { publicSnapshot } from "../simulation-3d/tests/fixtures/public-snapshot.js";

// Browser test with the real parent and a separately built three-dimensional
// receiver. All HTTP responses are intercepted without a bound server.
const consoleRoot = fileURLToPath(new URL("../", import.meta.url));
assert.ok(process.env.UAVSWARM_TWIN_DIST, "UAVSWARM_TWIN_DIST must point to the receiver build.");
const twinRoot = resolve(process.env.UAVSWARM_TWIN_DIST);
await access(resolve(twinRoot, "index.html"));
const dependencies = process.env.UAVSWARM_PLAYWRIGHT_ROOT ?? resolve(consoleRoot, "simulation-3d");
const { chromium } = createRequire(resolve(dependencies, "package.json"))("playwright");
const consoleOrigin = "http://127.0.0.1:5178";
const twinOrigin = "http://127.0.0.1:5179";
const runtimeOrigin = "http://127.0.0.1:8765";
const fixture = JSON.parse(await readFile(new URL("./fixtures/equipment-inspection-lifecycle.json", import.meta.url), "utf8"));
const replacement = { ...fixture.plan, plan_id: fixture.plan.plan_id + "-replacement",
  steps: fixture.plan.steps.filter(step => step.step_id !== "goto-0") };
const epoch = Date.parse(fixture.completed_run.first_arrival.source_timestamp);
const readyMessage = { type: "uav-swarm/simulation-ready",
  payload: { integration: "parent-snapshot", contractVersion: "1.0" } };

const fixtureAdapter = `
(() => {
  const original = ${JSON.stringify(fixture.plan)};
  const replacement = ${JSON.stringify(replacement)};
  window.previewFixture = { rejected: 0, executionAttempts: 0 };
  window.SwarmRuntimeApi.missionFixture = {
    validateCandidate({ objective }) {
      if (objective === "replace") {
        return new Promise(resolve => {
          previewFixture.resolveCandidate = () => resolve({ result: "validated", plan: replacement });
        });
      }
      if (objective === "unsupported") {
        previewFixture.rejected += 1;
        const step = { step_id: "observe", node_id: "UAV-02", action_type: "observe" };
        return { result: "validated", plan: { ...original, steps: [...original.steps, step] } };
      }
      return { result: "validated", plan: original };
    },
    execute() {
      previewFixture.executionAttempts += 1;
      throw new Error("Execution is outside the preview test.");
    },
  };
})();
`;

// Use the page's fixed clock for the simulated Runtime sample timestamps.
const fixtureSnapshotReader = `
window.SwarmRuntimeApi.vehicleSnapshot = async () => {
  const url = "${runtimeOrigin}/api/vehicle-snapshot?fixture_time_ms=" + Date.now();
  return (await fetch(url)).json();
};
`;

const apiResponses = new Map([
  ["/api/health", { status: "ok", service: "plan-preview-fixture" }],
  ["/api/snapshot", { active_actions: [] }],
  ["/api/telemetry/latest", { nodes: [] }],
  ["/api/vehicles", { vehicles: [] }],
  ["/api/mission/progress", fixture.completed_run.before],
  ["/api/actions/lifecycle", []],
  ["/api/actions/recent", []],
  ["/api/policy/decisions", []],
  ["/api/events", []],
  ["/api/replay", []],
]);
const requestMethods = [];
const errors = [];
const browser = await chromium.launch({
  headless: true,
  channel: process.env.UAVSWARM_BROWSER_CHANNEL || undefined,
});

async function openConsole(withFixture, query = "") {
  const context = await browser.newContext({ serviceWorkers: "block" });
  await context.addInitScript(({ consoleOrigin, twinOrigin }) => {
    if (location.origin === twinOrigin) {
      window.planMessages = [];
      window.addEventListener("message", event => {
        if (event.source === parent && event.origin === consoleOrigin && event.data?.type === "uav-swarm/plan-preview") {
          window.planMessages.push(event.data.payload);
        }
      });
    }
    if (location.origin === consoleOrigin && window === top) {
      // Hold the real iframe's ready event until each test has set up its
      // ordering. Synthetic events still exercise the application's guard.
      const pending = new Map();
      window.addEventListener("message", event => {
        if (event.isTrusted && event.origin === twinOrigin && event.data?.type === "uav-swarm/simulation-ready") {
          pending.set(event.source, { data: event.data, origin: event.origin, source: event.source });
          event.stopImmediatePropagation();
        }
      }, true);
      window.releaseFixtureReady = () => {
        const frame = document.getElementById("simulation-frame")?.contentWindow;
        const event = pending.get(frame);
        if (!event) return false;
        pending.delete(frame);
        window.dispatchEvent(new MessageEvent("message", event));
        return true;
      };
    }
  }, { consoleOrigin, twinOrigin });
  await context.route("**/*", async route => {
    const request = route.request();
    const address = new URL(request.url());
    requestMethods.push({ method: request.method(), path: address.pathname });
    if (request.method() !== "GET") return route.abort();
    if (address.origin === twinOrigin) {
      const asset = resolve(twinRoot, "." + (address.pathname === "/" ? "/index.html" : address.pathname));
      if (!asset.startsWith(twinRoot + sep)) return route.abort();
      return route.fulfill({ path: asset });
    }
    if (address.origin === runtimeOrigin) {
      const response = address.pathname === "/api/vehicle-snapshot"
        ? publicSnapshot({ time: Number(address.searchParams.get("fixture_time_ms")) || epoch })
        : apiResponses.get(address.pathname) ?? {};
      return route.fulfill({ json: response,
        headers: { "Access-Control-Allow-Origin": consoleOrigin } });
    }
    if (address.origin !== consoleOrigin) return route.abort();
    const filename = resolve(consoleRoot, "." + (address.pathname === "/" ? "/index.html" : address.pathname));
    if (!filename.startsWith(resolve(consoleRoot) + sep)) return route.abort();
    const contentType = { ".css": "text/css", ".html": "text/html", ".js": "text/javascript" }[
      filename.slice(filename.lastIndexOf("."))
    ];
    if (!contentType) return route.fulfill({ status: 404 });
    let body = await readFile(filename, "utf8");
    if (address.pathname === "/runtime-api.js") {
      body += fixtureSnapshotReader;
      if (withFixture) body += fixtureAdapter;
    }
    return route.fulfill({ body, contentType });
  });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  await page.clock.install({ time: new Date(epoch - 100_000) });
  await page.clock.pauseAt(new Date(epoch));
  await page.goto(consoleOrigin + "/" + query);
  return { page, context };
}

async function waitFor(getValue, message) {
  for (let attempt = 0; attempt < 400; attempt++) {
    const value = await getValue();
    if (value) return value;
    await delay(20);
  }
  assert.fail(message);
}

async function getTwin(page) {
  await page.frameLocator("#simulation-frame").locator("#plan-preview-status").waitFor({ state: "attached" });
  return page.frames().find(frame => frame.url().startsWith(twinOrigin + "/"));
}

async function beginValidation(page, objective) {
  await page.locator(".nav button[title='任务规划']").click();
  await page.locator("#template-plan-objective").fill(objective);
  await page.getByRole("button", { name: "校验任务候选" }).click();
}

const messages = frame => frame.evaluate(() => window.planMessages);
const twinState = frame => frame.evaluate(() => window.SwarmSimulationBridge?.getState());
async function releaseReady(page) {
  await waitFor(() => page.evaluate(() => releaseFixtureReady()), "The iframe did not report ready");
}

async function waitForTelemetry(frame) {
  return waitFor(async () => {
    const state = await twinState(frame);
    return state?.vehicleCount === 3 && state.alignment.every(node => node.aligned) ? state.alignment : null;
  }, "The real iframe did not render fixture telemetry");
}
async function waitForMessages(frame, count) {
  return waitFor(async () => {
    const received = await messages(frame);
    return received.length >= count ? received : null;
  }, `Expected ${count} plan messages`);
}

try {
  const { page, context } = await openConsole(true);
  await beginValidation(page, "original");
  await page.getByRole("heading", { name: "人工确认与执行" }).waitFor();
  await page.getByRole("button", { name: "查看三维集群态势" }).click();
  let frame = await getTwin(page);
  assert.equal(new URL(frame.url()).searchParams.get("planPreview"), "fixture");
  assert.deepEqual(await messages(frame), []);
  await releaseReady(page);
  const [first] = await waitForMessages(frame, 1);
  const expectedWaypoints = fixture.plan.steps.filter(step => step.action_type === "goto")
    .map(({ step_id, node_id, params }) => ({
      step_id, node_id, north_m: params.north_m, east_m: params.east_m, down_m: params.down_m,
    }));
  assert.deepEqual(first, {
    version: "1.0", plan_id: fixture.plan.plan_id, scene_id: fixture.plan.scene_id,
    map_version: fixture.plan.map_version, frame: "scene_ned", expires_at_ms: epoch + 60_000,
    waypoints: expectedWaypoints,
  });
  await waitForTelemetry(frame);
  assert.deepEqual((await twinState(frame)).planPreview, {
    planId: first.plan_id, expiresAtMs: first.expires_at_ms, waypointCount: 5,
  });
  assert.match(await frame.locator("#plan-preview-status").textContent(), /计划预览 · 测试桩/);
  assert.equal(await frame.locator("#plan-preview-status").isVisible(), true);

  await page.clock.fastForward(10_000);
  assert.deepEqual(await messages(frame), [first], "Telemetry refreshed the plan");
  await frame.goto(frame.url());
  assert.deepEqual(await messages(frame), [], "The reloaded document had not sent ready");
  await releaseReady(page);
  assert.deepEqual(await waitForMessages(frame, 1), [first], "Reload extended or changed the preview");
  await page.evaluate(() => { window.oldFixtureIframe = document.getElementById("simulation-frame").contentWindow; });

  await beginValidation(page, "replace");
  await page.getByRole("button", { name: "查看三维集群态势" }).click();
  frame = await getTwin(page);
  await page.evaluate(({ origin, data }) => {
    window.dispatchEvent(new MessageEvent("message", { source: window.oldFixtureIframe, origin, data }));
    const current = document.getElementById("simulation-frame").contentWindow;
    window.dispatchEvent(new MessageEvent("message", { source: current, origin: "http://127.0.0.1:5188", data }));
  }, { origin: twinOrigin, data: readyMessage });
  assert.equal(await page.locator(".twin-panel .badge").textContent(), "WAITING");
  assert.deepEqual(await messages(frame), []);
  await releaseReady(page);
  assert.deepEqual(await waitForMessages(frame, 1), [null]);
  await page.evaluate(() => previewFixture.resolveCandidate());
  const [, second] = await waitForMessages(frame, 2);
  assert.equal(second.plan_id, replacement.plan_id);
  assert.equal(second.expires_at_ms, epoch + 70_000);
  assert.deepEqual(second.waypoints, expectedWaypoints.filter(step => step.step_id !== "goto-0"));
  const existingTelemetry = await waitForTelemetry(frame);
  const foreign = { ...second, map_version: "different-map" };
  await page.evaluate(({ origin, payload }) => {
    document.getElementById("simulation-frame").contentWindow.postMessage({ type: "uav-swarm/plan-preview", payload }, origin);
  }, { origin: twinOrigin, payload: foreign });
  await waitForMessages(frame, 3);
  assert.equal((await twinState(frame)).planPreview, null);
  assert.deepEqual((await twinState(frame)).alignment, existingTelemetry);
  await page.evaluate(({ origin, data }) => {
    const source = document.getElementById("simulation-frame").contentWindow;
    window.dispatchEvent(new MessageEvent("message", { source, origin, data }));
  }, { origin: twinOrigin, data: readyMessage });
  assert.deepEqual(await waitForMessages(frame, 4), [null, second, foreign, second]);

  await page.clock.fastForward(50_000);
  assert.equal((await twinState(frame)).planPreview?.planId, replacement.plan_id);
  assert.equal((await messages(frame)).length, 4, "The previous candidate's deadline cleared its replacement");
  await page.clock.fastForward(10_000);
  assert.equal((await waitForMessages(frame, 5)).at(-1), null);
  assert.equal((await twinState(frame)).planPreview, null);
  await waitForTelemetry(frame);
  assert.deepEqual((await twinState(frame)).alignment.map(node => node.id), existingTelemetry.map(node => node.id));
  assert.equal(await page.locator("#fixture-plan-preview-clear").isDisabled(), true);

  await beginValidation(page, "original");
  await page.getByRole("heading", { name: "人工确认与执行" }).waitFor();
  await page.getByRole("button", { name: "查看三维集群态势" }).click();
  frame = await getTwin(page);
  await releaseReady(page);
  await waitForMessages(frame, 1);
  const beforeRevocation = await waitForTelemetry(frame);
  await page.getByRole("button", { name: "撤销计划预览" }).click();
  assert.equal((await waitForMessages(frame, 2)).at(-1), null);
  assert.equal((await twinState(frame)).planPreview, null);
  assert.deepEqual((await twinState(frame)).alignment, beforeRevocation);
  assert.equal(await page.evaluate(() => state.fixturePlan.plan.plan_id), fixture.plan.plan_id);

  await beginValidation(page, "unsupported");
  await page.getByText("缺少已校验的载具、航点或场景版本").waitFor();
  await page.getByRole("button", { name: "查看三维集群态势" }).click();
  frame = await getTwin(page);
  await releaseReady(page);
  assert.deepEqual(await waitForMessages(frame, 1), [null]);
  assert.equal(await page.evaluate(() => previewFixture.executionAttempts), 0);
  await context.close();

  const regular = await openConsole(false, "?planPreview=fixture");
  await regular.page.locator(".nav button[title='三维集群态势']").click();
  frame = await getTwin(regular.page);
  assert.equal(new URL(frame.url()).searchParams.has("planPreview"), false);
  await releaseReady(regular.page);
  await waitForTelemetry(frame);
  assert.deepEqual(await messages(frame), []);
  assert.equal(await regular.page.locator("#fixture-plan-preview-clear").count(), 0);
  await regular.context.close();

  const stage = await openConsole(true, "?mode=stage&source=live");
  await stage.page.locator("#stage-view-3").click();
  frame = await getTwin(stage.page);
  assert.equal(new URL(frame.url()).searchParams.has("planPreview"), false);
  await releaseReady(stage.page);
  await waitForTelemetry(frame);
  assert.deepEqual(await messages(frame), []);
  assert.equal(await stage.page.evaluate(() => previewFixture.executionAttempts), 0);
  await stage.context.close();

  assert.deepEqual(errors, []);
  assert.deepEqual(requestMethods.filter(request => request.method !== "GET"), []);
  console.log(`Real console and Cesium preview passed in three browser contexts. Intercepted ${requestMethods.length} reads, zero write requests and zero execution attempts.`);
} finally {
  await browser.close();
}
