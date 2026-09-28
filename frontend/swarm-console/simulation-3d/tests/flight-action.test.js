import test from "node:test";
import assert from "node:assert/strict";
import {
  abortFlightAction,
  createFlightActionClient,
  listInflightActions,
  summarizeActionResult,
} from "../src/flight-action.js";

// --- goto 的真实响应样本（取自 2026-09-28 活体验证）-------------------------
const OK_GOTO = {
  action: "goto",
  action_id: "act_5c4238ce67e0",
  accepted: true,
  status: "succeeded",
  result: "pass",
  failure_reason: null,
  node_id: "UAV-01",
  mode_confirmed: true,
  observed_main_mode: 6,
  arrival_observed: true,
  completion_state: "stable_within_tolerance",
  stream_setpoints: 34,
  stream_errors: 0,
  target_scene_ned_m: { north: 4.0, east: 0.0, down: -3.0 },
  target_vehicle_local_ned_m: { north: 3.98, east: 0.02, down: -3.0 },
  arrival: {
    observed: true,
    reason: "stable_within_tolerance",
    samples: 34,
    last_error_m: 0.14446003259954177,
    hold_s: 1.600130609999951,
  },
  restored: {
    restored: true,
    main_mode: 4,
    main_mode_name: "AUTO",
    sub_mode: 3,
    observed_main_mode: 4,
    observed_sub_mode: 3,
    observed_main_mode_name: "AUTO_LOITER",
    still_in_offboard: false,
    accepted_fallback: false,
    attempted: true,
  },
};

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

// --- goto ----------------------------------------------------------------

test("goto posts scene_ned coordinates to /actions/goto", async () => {
  const fetchImpl = fakeFetch({ body: OK_GOTO });
  const client = createFlightActionClient({ fetchImpl });

  const result = await client.goto({ nodeId: "UAV-01", northM: 4, eastM: -2, downM: -5 });

  assert.equal(result.ok, true);
  assert.equal(fetchImpl.calls.length, 1);
  assert.match(fetchImpl.calls[0].url, /\/actions\/goto$/);
  const body = JSON.parse(fetchImpl.calls[0].init.body);
  assert.deepEqual(body, {
    node_id: "UAV-01",
    north_m: 4,
    east_m: -2,
    down_m: -5,
    arrival_tolerance_m: 1,
    hold_s: 1,
  });
});

test("goto exposes the evidence needed to tell success from a silent no-op", async () => {
  const fetchImpl = fakeFetch({ body: OK_GOTO });
  const client = createFlightActionClient({ fetchImpl });

  const { ok, summary } = await client.goto({ nodeId: "UAV-01", northM: 4 });

  assert.equal(ok, true);
  assert.equal(summary.goto.modeConfirmed, true, "必须暴露 OFFBOARD 是否真的进了");
  assert.equal(summary.goto.arrivalObserved, true);
  assert.ok(Math.abs(summary.goto.arrivalErrorM - 0.1445) < 0.001, "必须暴露实际偏差");
  assert.equal(summary.goto.streamSetpoints, 34);
  assert.equal(summary.goto.restored.restored, true);
  assert.equal(summary.goto.restored.stillInOffboard, false);
  // 子模式必须可见 —— RTL(5) 与 LOITER(3) 的主模式相同，只看主模式会误判
  assert.equal(summary.goto.restored.observedSubMode, 3);
});

test("goto flags a vehicle left in OFFBOARD via stillInOffboard", async () => {
  const dangerous = {
    ...OK_GOTO,
    result: "fail",
    accepted: false,
    failure_reason: "mode_restore_failed",
    restored: { ...OK_GOTO.restored, restored: false, still_in_offboard: true, observed_main_mode: 6, observed_sub_mode: 0 },
  };
  const client = createFlightActionClient({ fetchImpl: fakeFetch({ body: dangerous }) });

  const result = await client.goto({ nodeId: "UAV-01" });

  assert.equal(result.ok, false);
  assert.equal(result.error, "mode_restore_failed");
  assert.equal(result.summary.goto.restored.stillInOffboard, true, "危险状态必须能读到");
});

test("goto carries AUTO sub_mode so RTL is distinguishable from LOITER", async () => {
  // AUTO + RTL(5)：主模式与 LOITER 相同，只有子模式能区分
  const rtl = {
    ...OK_GOTO,
    result: "fail",
    accepted: false,
    failure_reason: "mode_restore_failed",
    restored: {
      ...OK_GOTO.restored,
      restored: false,
      observed_main_mode: 4,
      observed_sub_mode: 5,
      observed_main_mode_name: "AUTO_RTL",
    },
  };
  const client = createFlightActionClient({ fetchImpl: fakeFetch({ body: rtl }) });

  const { summary } = await client.goto({ nodeId: "UAV-01" });

  assert.equal(summary.goto.restored.observedSubMode, 5, "RTL 必须能从子模式识别出来");
  assert.equal(summary.goto.restored.observedMainModeName, "AUTO_RTL");
  assert.equal(summary.goto.restored.restored, false);
});

test("goto rejection for missing calibration surfaces the reason", async () => {
  const rejected = {
    action: "goto",
    result: "fail",
    accepted: false,
    status: "rejected",
    failure_reason: "coordinate_calibration_unavailable",
    code: "coordinate_calibration_unavailable",
    calibration_status: "stale",
  };
  const client = createFlightActionClient({ fetchImpl: fakeFetch({ body: rejected }) });

  const result = await client.goto({ nodeId: "UAV-01" });

  assert.equal(result.ok, false);
  assert.equal(result.error, "coordinate_calibration_unavailable");
});

test("goto defaults down_m to -3 (3 m altitude, z is positive down)", async () => {
  const fetchImpl = fakeFetch({ body: OK_GOTO });
  const client = createFlightActionClient({ fetchImpl });

  await client.goto({ nodeId: "UAV-01" });

  const body = JSON.parse(fetchImpl.calls[0].init.body);
  assert.equal(body.down_m, -3, "z 向下为正，-3 才是高度 3 米");
});

test("goto is tracked as its own in-flight kind", async () => {
  const fetchImpl = fakeFetch({ body: OK_GOTO, delayMs: 40 });
  const client = createFlightActionClient({ fetchImpl });

  const pending = client.goto({ nodeId: "UAV-01" });
  assert.deepEqual(listInflightActions(), ["goto:UAV-01"]);

  await pending;
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
