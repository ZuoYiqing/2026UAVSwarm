/**
 * 飞行动作客户端：把三维视图的按钮接到 Runtime 的 /api/actions/* 端点上。
 *
 * 设计要点：
 * - 只负责"发起请求 + 归一化结果"，不碰 UI，便于用 node:test 覆盖。
 * - 默认走相对路径 /api，由页面的来源决定实际地址：
 *     · 独立打开（5179，Vite 有 /api 代理）→ 命中 Vite 代理转发到 8765；
 *     · 嵌入主控制台（iframe）→ 与父页面同源，不会产生跨域。
 * - 所有失败都归一化成 { ok:false, error, message }，绝不抛异常给 UI，
 *   避免一个网络抖动把整个三维视图带崩。
 * - 支持中断：in-flight 时再次点击同一动作会 abort 掉上一次。
 *
 * 契约来源（Runtime 侧）：
 *   POST /api/actions/takeoff   { node_id, altitude_m, altitude_tolerance_m, stable_duration_ms }
 *   POST /api/actions/land      { node_id }
 * 响应里 accepted/status/result/arm_ack/takeoff_ack/land_ack/max_altitude_m/
 * threshold_reached/policy_decision 等字段用于展示。
 */

/** 动作进行中的取消信号集合，按 `kind:nodeId` 索引。 */
const inflight = new Map();

export class FlightActionError extends Error {
  constructor(code, message, detail = {}) {
    super(message);
    this.name = "FlightActionError";
    this.code = code;
    this.detail = detail;
  }
}

function actionKey(kind, nodeId) {
  return `${kind}:${nodeId ?? ""}`;
}

/**
 * 中断指定节点的某个动作（如果正在执行）。
 * @returns {boolean} 是否确实中断了一个在途请求
 */
export function abortFlightAction(kind, nodeId) {
  const key = actionKey(kind, nodeId);
  const controller = inflight.get(key);
  if (!controller) return false;
  controller.abort();
  inflight.delete(key);
  return true;
}

/** 当前有哪些动作在途（供 UI 显示"执行中"状态）。 */
export function listInflightActions() {
  return [...inflight.keys()];
}

/**
 * 从 Runtime 的动作响应里提取展示用的摘要。
 * 缺失的字段一律给 null，绝不用 0 或 false 冒充"未知"。
 */
export function summarizeActionResult(raw) {
  if (!raw || typeof raw !== "object") {
    return { accepted: null, result: null, status: null, failureReason: null, acks: {}, maxAltitudeM: null, thresholdReached: null, altitude: null, policyDecision: null };
  }
  const ackOf = (a) =>
    a && typeof a === "object"
      ? {
          command: a.command ?? null,
          result: a.result ?? null,
          resultName: a.result_name ?? null,
          timeout: a.timeout ?? null,
        }
      : null;
  const altitude = raw.altitude_observation && typeof raw.altitude_observation === "object"
    ? {
        observed: raw.altitude_observation.observed ?? null,
        sampleCount: raw.altitude_observation.sample_count ?? null,
        maxAltitudeM: raw.altitude_observation.max_altitude_m ?? null,
        thresholdAltitudeM: raw.altitude_observation.threshold_altitude_m ?? null,
        thresholdReached: raw.altitude_observation.threshold_reached ?? null,
      }
    : null;
  const policy = raw.policy_decision && typeof raw.policy_decision === "object"
    ? {
        decisionCode: raw.policy_decision.decision_code ?? null,
        primaryReasonCode: raw.policy_decision.primary_reason_code ?? null,
        auditTags: Array.isArray(raw.policy_decision.audit_tags) ? [...raw.policy_decision.audit_tags] : [],
        effectiveScope: raw.policy_decision.effective_scope ?? null,
      }
    : null;
  return {
    action: raw.action ?? null,
    actionId: raw.action_id ?? null,
    accepted: typeof raw.accepted === "boolean" ? raw.accepted : null,
    result: raw.result ?? null,
    status: raw.status ?? null,
    lifecycleStatus: raw.lifecycle_status ?? null,
    failureReason: raw.failure_reason || null,
    nodeId: raw.node_id ?? null,
    systemId: raw.system_id ?? null,
    endpoint: raw.endpoint ?? null,
    acks: {
      arm: ackOf(raw.arm_ack),
      takeoff: ackOf(raw.takeoff_ack),
      land: ackOf(raw.land_ack),
    },
    maxAltitudeM: raw.max_altitude_m ?? null,
    thresholdReached: raw.threshold_reached ?? null,
    altitude,
    policyDecision: policy,
  };
}

/**
 * 创建一个动作客户端。
 *
 * @param {object} options
 * @param {string} [options.apiBaseUrl="/api"]  API 基地址（默认相对路径）
 * @param {Function} [options.fetchImpl]       注入的 fetch（测试用）
 * @param {Function} [options.onEvent]         事件回调，便于 UI 记录日志
 */
export function createFlightActionClient({
  apiBaseUrl = "/api",
  fetchImpl = globalThis.fetch,
  onEvent = () => {},
} = {}) {
  const baseUrl = String(apiBaseUrl || "/api").replace(/\/+$/, "");

  async function post(path, body, { nodeId, kind, signal } = {}) {
    const key = actionKey(kind, nodeId);
    const controller = new AbortController();
    // 外部 signal（例如组件卸载）与内部 controller 联动
    if (signal) {
      if (signal.aborted) controller.abort();
      else signal.addEventListener("abort", () => controller.abort(), { once: true });
    }
    inflight.set(key, controller);
    onEvent({ phase: "request", kind, nodeId, path, body });

    let response;
    try {
      response = await fetchImpl(`${baseUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (error) {
      inflight.delete(key);
      const aborted = error?.name === "AbortError";
      const normalized = new FlightActionError(
        aborted ? "aborted" : "network_error",
        aborted ? "动作已取消" : `无法连接 Runtime：${error?.message || error}`,
        { kind, nodeId },
      );
      onEvent({ phase: "error", kind, nodeId, error: normalized });
      return { ok: false, error: normalized.code, message: normalized.message };
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    inflight.delete(key);

    if (!response.ok) {
      const message = payload?.message || payload?.error || `Runtime 返回 HTTP ${response.status}`;
      onEvent({ phase: "error", kind, nodeId, httpStatus: response.status, payload });
      return {
        ok: false,
        error: payload?.error || `http_${response.status}`,
        message,
        httpStatus: response.status,
        code: payload?.code ?? null,
        raw: payload,
      };
    }

    const summary = summarizeActionResult(payload);
    onEvent({ phase: "response", kind, nodeId, summary, raw: payload });

    // accepted=false 且带 failure_reason：动作被拒或失败，但仍返回 200，
    // 必须当成失败暴露给用户，不能因为 HTTP 成功就显示成功。
    if (summary.accepted === false || summary.result === "fail") {
      return {
        ok: false,
        error: summary.failureReason || "action_rejected",
        message: summary.failureReason || "动作未被接受",
        summary,
        raw: payload,
      };
    }
    return { ok: true, summary, raw: payload };
  }

  return {
    /** 发起正式起飞（要求稳定的目标高度完成证据）。 */
    takeoff({ nodeId, altitudeM = 3, altitudeToleranceM = 0.3, stableDurationMs = 1000, signal } = {}) {
      return post(
        "/actions/takeoff",
        {
          node_id: nodeId ?? null,
          altitude_m: altitudeM,
          altitude_tolerance_m: altitudeToleranceM,
          stable_duration_ms: stableDurationMs,
        },
        { nodeId, kind: "takeoff", signal },
      );
    },

    /** 发起降落（要求落地且 disarmed 的证据）。 */
    land({ nodeId, signal } = {}) {
      return post("/actions/land", { node_id: nodeId ?? null }, { nodeId, kind: "land", signal });
    },

    abort: abortFlightAction,
    listInflight: listInflightActions,
  };
}
