import test from "node:test";
import assert from "node:assert/strict";
import {
  abortFlightAction,
  createFlightActionClient,
  listInflightActions,
  summarizeActionResult,
} from "../src/flight-action.js";

/** 造一个假的 fetch，记录调用参数，返回预设响应。 */
function fakeFetch({ status = 200, body = {}, throwError = null, delayMs = 0 } = {}) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    if (delayMs) {
      await new Promise((resolve, reject) => {
        const t = setTimeout(resolve, delayMs);
        init?.signal?.addEventListener(
          "abort",
          () => {
            clearTimeout(t);
            const err = new Error("aborted");
            err.name = "AbortError";
            reject(err);
          },
          { once: true },
        );
      });
    }
    if (throwError) throw throwError;
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    };
  };
  impl.calls = calls;
  return impl;
}

const OK_TAKEOFF = {
  action: "takeoff",
  action_id: "act_1",
  accepted: true,
  status: "succeeded",
  result: "pass",
  node_id: "UAV-01",
  system_id: 1,
  endpoint: "udpin:127.0.0.1:14540",
  arm_ack: { command: 400, result: 0, result_name: "MAV_RESULT_ACCEPTED", timeout: false },
  takeoff_ack: { command: 22, result: 0, result_name: "MAV_RESULT_ACCEPTED", timeout: false },
  land_ack: { command: 21, result: 0, result_name: "MAV_RESULT_ACCEPTED", timeout: false },
  max_altitude_m: 2.11,
  threshold_reached: true,
  altitude_observation: {
    observed: true,
    sample_count: 75,
    max_altitude_m: 2.11,
    threshold_altitude_m: 2.1,
    threshold_reached: true,
  },
  policy_decision: {
    decision_code: "allow",
    primary_reason_code: null,
    audit_tags: ["policy", "allow"],
    effective_scope: "self_only",
  },
};

test("takeoff posts the documented contract to /api/actions/takeoff", async () => {
  const fetchImpl = fakeFetch({ body: OK_TAKEOFF });
  const client = createFlightActionClient({ apiBaseUrl: "/api/", fetchImpl });

  const result = await client.takeoff({ nodeId: "UAV-01", altitudeM: 3 });

  assert.equal(fetchImpl.calls.length, 1);
  const { url, init } = fetchImpl.calls[0];
  assert.equal(url, "/api/actions/takeoff");
  assert.equal(init.method, "POST");
  assert.equal(init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(init.body), {
    node_id: "UAV-01",
    altitude_m: 3,
    altitude_tolerance_m: 0.3,
    stable_duration_ms: 1000,
  });
  assert.equal(result.ok, true);
});

test("land posts node_id to /api/actions/land", async () => {
  const fetchImpl = fakeFetch({ body: { action: "land", accepted: true, result: "pass" } });
  const client = createFlightActionClient({ fetchImpl });

  const result = await client.land({ nodeId: "UAV-03" });

  assert.equal(fetchImpl.calls[0].url, "/api/actions/land");
  assert.deepEqual(JSON.parse(fetchImpl.calls[0].init.body), { node_id: "UAV-03" });
  assert.equal(result.ok, true);
});

test("a satisfied action summary keeps ACK, altitude and policy evidence", () => {
  const s = summarizeActionResult(OK_TAKEOFF);
  assert.equal(s.accepted, true);
  assert.equal(s.result, "pass");
  assert.equal(s.acks.arm.resultName, "MAV_RESULT_ACCEPTED");
  assert.equal(s.acks.takeoff.command, 22);
  assert.equal(s.maxAltitudeM, 2.11);
  assert.equal(s.thresholdReached, true);
  assert.equal(s.altitude.sampleCount, 75);
  assert.equal(s.policyDecision.decisionCode, "allow");
});

test("missing fields become null instead of being faked as zero or false", () => {
  const s = summarizeActionResult({ action: "takeoff" });
  assert.equal(s.accepted, null);
  assert.equal(s.result, null);
  assert.equal(s.maxAltitudeM, null);
  assert.equal(s.thresholdReached, null);
  assert.equal(s.altitude, null);
  assert.equal(s.policyDecision, null);
  assert.equal(s.acks.arm, null);
});

test("HTTP 200 with accepted=false is reported as failure, not success", async () => {
  const fetchImpl = fakeFetch({
    body: { action: "takeoff", accepted: false, result: "fail", failure_reason: "policy_denied" },
  });
  const client = createFlightActionClient({ fetchImpl });

  const result = await client.takeoff({ nodeId: "UAV-01" });

  assert.equal(result.ok, false);
  assert.equal(result.error, "policy_denied");
});

test("non-2xx response surfaces the Runtime error payload", async () => {
  const fetchImpl = fakeFetch({
    status: 400,
    body: { error: "invalid_parameter", message: "altitude_tolerance_m must be less than altitude_m" },
  });
  const client = createFlightActionClient({ fetchImpl });

  const result = await client.takeoff({ nodeId: "UAV-01" });

  assert.equal(result.ok, false);
  assert.equal(result.httpStatus, 400);
  assert.equal(result.error, "invalid_parameter");
  assert.match(result.message, /altitude_tolerance_m/);
});

test("network failure is normalized and never throws", async () => {
  const fetchImpl = fakeFetch({ throwError: new TypeError("Failed to fetch") });
  const client = createFlightActionClient({ fetchImpl });

  const result = await client.takeoff({ nodeId: "UAV-01" });

  assert.equal(result.ok, false);
  assert.equal(result.error, "network_error");
  assert.match(result.message, /Failed to fetch/);
});

test("aborting an in-flight takeoff reports aborted and clears the registry", async () => {
  const fetchImpl = fakeFetch({ body: OK_TAKEOFF, delayMs: 50 });
  const client = createFlightActionClient({ fetchImpl });

  const pending = client.takeoff({ nodeId: "UAV-01" });
  assert.deepEqual(listInflightActions(), ["takeoff:UAV-01"]);

  assert.equal(abortFlightAction("takeoff", "UAV-01"), true);
  const result = await pending;

  assert.equal(result.ok, false);
  assert.equal(result.error, "aborted");
  assert.deepEqual(listInflightActions(), []);
});

test("a second takeoff for the same node is tracked separately per node", async () => {
  const fetchImpl = fakeFetch({ body: OK_TAKEOFF, delayMs: 30 });
  const client = createFlightActionClient({ fetchImpl });

  const a = client.takeoff({ nodeId: "UAV-01" });
  const b = client.takeoff({ nodeId: "UAV-02" });
  assert.deepEqual(listInflightActions().sort(), ["takeoff:UAV-01", "takeoff:UAV-02"]);

  await Promise.all([a, b]);
  assert.deepEqual(listInflightActions(), []);
});

test("event callback receives request and response phases for auditability", async () => {
  const fetchImpl = fakeFetch({ body: OK_TAKEOFF });
  const events = [];
  const client = createFlightActionClient({ fetchImpl, onEvent: (e) => events.push(e) });

  await client.takeoff({ nodeId: "UAV-01" });

  assert.equal(events[0].phase, "request");
  assert.equal(events[0].kind, "takeoff");
  assert.equal(events[0].nodeId, "UAV-01");
  assert.equal(events[1].phase, "response");
  assert.equal(events[1].summary.actionId, "act_1");
});
