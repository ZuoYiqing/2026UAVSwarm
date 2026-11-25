const test = require("node:test");
const assert = require("node:assert/strict");

function loadApi(fetchImpl, windowOverrides = {}) {
  const previous = {
    window: global.window,
    localStorage: global.localStorage,
    fetch: global.fetch,
  };
  const storage = new Map();
  global.window = {
    setTimeout,
    clearTimeout,
    localStorage: {
      getItem: (key) => storage.get(key) || null,
      setItem: (key, value) => storage.set(key, value),
    },
    ...windowOverrides,
  };
  global.localStorage = global.window.localStorage;
  global.fetch = fetchImpl;
  delete require.cache[require.resolve("../runtime-api.js")];
  require("../runtime-api.js");
  const api = global.window.SwarmRuntimeApi;
  return {
    api,
    restore() {
      global.window = previous.window;
      global.localStorage = previous.localStorage;
      global.fetch = previous.fetch;
    },
  };
}

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(payload),
  };
}

test("request deadline covers a stalled response body", async () => {
  const runtime = loadApi(async (_url, options) => ({ ok: true, status: 200,
    text: () => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }),
  }));
  global.window.setTimeout = (callback) => setTimeout(callback, 10);
  try {
    await assert.rejects(runtime.api.health(), (error) => error.kind === "timeout");
  } finally {
    runtime.restore();
  }
});

function controlledTimers() {
  const pending = new Set();
  const scheduled = [];
  return {
    pending,
    scheduled,
    window: {
      setTimeout(callback, delay) {
        const timer = { callback, delay };
        pending.add(timer);
        scheduled.push(delay);
        return timer;
      },
      clearTimeout(timer) { pending.delete(timer); },
    },
    fire(delay) {
      const timer = [...pending].find(item => item.delay === delay);
      assert.ok(timer, `No timer scheduled at ${delay} ms`);
      pending.delete(timer);
      timer.callback();
    },
  };
}

test("mission preview hints at 5 seconds and times out at 20 seconds even if only the response body stalls", async () => {
  const timers = controlledTimers();
  const hints = [];
  let signal;
  const runtime = loadApi(async (url, options) => {
    assert.equal(url, "http://127.0.0.1:8765/api/planner/plan-mission");
    assert.equal(options.method, "POST");
    assert.deepEqual(JSON.parse(options.body), { objective: "巡检东北视觉标记" });
    signal = options.signal;
    return {
      ok: true, status: 200,
      text: () => new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      }),
    };
  }, timers.window);
  try {
    const pending = runtime.api.planMission({ objective: "巡检东北视觉标记" }, {
      onSlow: timeoutMs => hints.push(timeoutMs),
    });
    const timedOut = assert.rejects(pending, error => error.kind === "timeout");
    await Promise.resolve();
    assert.deepEqual(timers.scheduled, [20_000, 5_000]);
    assert.deepEqual(hints, []);
    timers.fire(5_000);
    assert.deepEqual(hints, [20_000]);
    assert.equal(signal.aborted, false);
    timers.fire(20_000);
    await timedOut;
    assert.equal(timers.pending.size, 0);
  } finally {
    runtime.restore();
  }
});

test("mission preview respects the URL and call-specific timeouts and clears timers on early replies", async () => {
  const timers = controlledTimers();
  const location = { search: "?planTimeoutMs=30000" };
  const earlyReply = { result: "ready" };
  let status = 200;
  const runtime = loadApi(async () => response(earlyReply, status), { ...timers.window, location });
  const onSlow = () => assert.fail("Completed preview must not display a slow hint");
  try {
    assert.deepEqual(await runtime.api.planMission({}, { onSlow }), earlyReply);
    assert.deepEqual(timers.scheduled, [30_000, 5_000]);
    assert.equal(timers.pending.size, 0);

    timers.scheduled.length = 0;
    status = 503;
    await assert.rejects(runtime.api.planMission({}, { timeoutMs: 25_000, slowHintMs: 3_000, onSlow }),
      error => error.kind === "http" && error.status === 503);
    assert.deepEqual(timers.scheduled, [25_000, 3_000]);
    assert.equal(timers.pending.size, 0);

    timers.scheduled.length = 0;
    location.search = "?planTimeoutMs=invalid";
    status = 200;
    await runtime.api.planMission({}, { onSlow });
    await runtime.api.vehicles();
    assert.deepEqual(timers.scheduled, [20_000, 5_000, 5_000]);
    assert.equal(timers.pending.size, 0);
  } finally {
    runtime.restore();
  }
});

test("operational takeoff posts the exact node-bound body", async () => {
  const calls = [];
  const runtime = loadApi(async (url, options) => {
    calls.push({ url, options });
    return response({ action_id: "act-2", node_id: "UAV-02", status: "executing" }, 202);
  });
  const body = {
    node_id: "UAV-02",
    transport_endpoint: "udpin:127.0.0.1:14541",
    request_id: "req-2",
    trace_id: "trace-2",
    idempotency_key: "idem-2",
  };
  try {
    const result = await runtime.api.takeoff(body);
    assert.equal(result.action_id, "act-2");
    assert.equal(calls[0].url, "http://127.0.0.1:8765/api/actions/takeoff");
    assert.equal(calls[0].options.method, "POST");
    assert.deepEqual(JSON.parse(calls[0].options.body), body);
  } finally {
    runtime.restore();
  }
});

test("lifecycle and action status use server-owned read routes", async () => {
  const calls = [];
  const runtime = loadApi(async (url) => {
    calls.push(url);
    return response([]);
  });
  try {
    await runtime.api.actionLifecycle(30);
    await runtime.api.actionStatus("act/UAV-02");
    assert.deepEqual(calls, [
      "http://127.0.0.1:8765/api/actions/lifecycle?n=30",
      "http://127.0.0.1:8765/api/actions/act%2FUAV-02",
    ]);
  } finally {
    runtime.restore();
  }
});

test("HTTP busy response remains structured for the UI", async () => {
  const runtime = loadApi(async () => response({ error: "node_busy", node_id: "UAV-02" }, 409));
  try {
    await assert.rejects(
      runtime.api.land({ node_id: "UAV-02" }),
      (error) => error.kind === "http"
        && error.status === 409
        && error.payload.error === "node_busy"
    );
  } finally {
    runtime.restore();
  }
});
