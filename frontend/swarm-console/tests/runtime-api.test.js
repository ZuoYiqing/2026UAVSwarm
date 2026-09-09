const test = require("node:test");
const assert = require("node:assert/strict");

function loadApi(fetchImpl) {
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
