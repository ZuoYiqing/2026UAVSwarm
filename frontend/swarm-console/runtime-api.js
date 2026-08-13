/*
 * Runtime API adapter for 2026UAVSwarm Console.
 *
 * This file is intentionally frontend-only. It defines the HTTP contract that
 * the WSL/Python runtime bridge exposes. The UI may still render local demo
 * data while the bridge is offline, but execution calls must report the real
 * connection state instead of pretending that a backend action succeeded.
 *
 * Expected backend shape:
 *   GET  /api/health
 *   POST /api/backend/check
 *   POST /api/actions/smoke-takeoff
 *   POST /api/actions/land
 *   POST /api/planner/plan-mission
 *   GET  /api/replay?n=20
 *   GET  /api/capabilities
 *
 * The current Python repository already has CLI/runtime functions for these
 * concepts, but a browser cannot invoke CLI commands directly. A small HTTP
 * bridge should translate these requests to the existing runtime code.
 */
(function attachRuntimeApi(global) {
  const DEFAULT_BASE_URL = "http://127.0.0.1:8765/api";
  const STORAGE_KEY = "swarm-console.runtime-api-base-url";
  const DEFAULT_TIMEOUT_MS = 5000;
  const ACTION_TIMEOUT_GRACE_MS = 5000;

  function smokeTakeoffTimeoutMs(body = {}) {
    const commandTimeout = Number(body.command_timeout_ms) || 10000;
    const observeTimeout = Number(body.observe_timeout_ms) || 25000;
    const commandCount = body.auto_land === true ? 4 : 3;
    return Math.max(
      DEFAULT_TIMEOUT_MS,
      commandCount * commandTimeout + observeTimeout + ACTION_TIMEOUT_GRACE_MS
    );
  }

  function landTimeoutMs(body = {}) {
    const commandTimeout = Number(body.command_timeout_ms) || 10000;
    return Math.max(DEFAULT_TIMEOUT_MS, commandTimeout + ACTION_TIMEOUT_GRACE_MS);
  }

  function getConfiguredBaseUrl() {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_BASE_URL;
  }

  function setConfiguredBaseUrl(url) {
    const normalized = String(url || "").trim().replace(/\/+$/, "");
    localStorage.setItem(STORAGE_KEY, normalized || DEFAULT_BASE_URL);
    return getConfiguredBaseUrl();
  }

  async function request(path, options = {}) {
    const baseUrl = getConfiguredBaseUrl().replace(/\/+$/, "");
    const url = `${baseUrl}${path}`;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      options.timeoutMs || DEFAULT_TIMEOUT_MS
    );
    const headers = { ...(options.headers || {}) };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    let response;
    try {
      response = await fetch(url, {
        method: options.method || "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch (cause) {
      const timedOut = cause instanceof DOMException && cause.name === "AbortError";
      const error = new Error(
        timedOut
          ? `Runtime API 请求超时：${url}`
          : `无法连接 Runtime API：${url}`
      );
      error.kind = timedOut ? "timeout" : "network";
      error.url = url;
      error.cause = cause;
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
    }

    const text = await response.text();
    let payload = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        payload = { raw: text };
      }
    }

    if (!response.ok) {
      const message = payload.error || payload.message || `HTTP ${response.status}`;
      const error = new Error(`${message} (HTTP ${response.status})`);
      error.kind = "http";
      error.status = response.status;
      error.payload = payload;
      error.url = url;
      throw error;
    }
    return payload;
  }

  global.SwarmRuntimeApi = {
    getConfiguredBaseUrl,
    setConfiguredBaseUrl,
    health: () => request("/health", { timeoutMs: 2500 }),
    checkBackend: (body) => request("/backend/check", { method: "POST", body }),
    smokeTakeoff: (body) => request("/actions/smoke-takeoff", {
      method: "POST",
      body,
      timeoutMs: smokeTakeoffTimeoutMs(body),
    }),
    land: (body) => request("/actions/land", {
      method: "POST",
      body,
      timeoutMs: landTimeoutMs(body),
    }),
    planMission: (body) => request("/planner/plan-mission", { method: "POST", body }),
    replayLast: (n = 20) => request(`/replay?n=${encodeURIComponent(n)}`),
    capabilities: () => request("/capabilities"),
    events: (n = 50) => request(`/events?n=${encodeURIComponent(n)}`),
    recentActions: (n = 20) => request(`/actions/recent?n=${encodeURIComponent(n)}`),
    policyDecisions: (n = 20) => request(`/policy/decisions?n=${encodeURIComponent(n)}`),
    skills: () => request("/skills"),
    vehicles: () => request("/vehicles"),
    telemetryLatest: () => request("/telemetry/latest"),
    snapshot: () => request("/snapshot"),
    vehicleSnapshot: () => request("/vehicle-snapshot"),
    agentStatus: () => request("/agent/status"),
    simulationStatus: () => request("/simulation/status"),
    smokeTakeoffTimeoutMs,
    landTimeoutMs,
  };
})(window);
