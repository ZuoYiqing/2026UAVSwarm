(function attachConsoleModel(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.SwarmConsoleModel = api;
  }
})(typeof window !== "undefined" ? window : undefined, function createConsoleModel() {
  const ACTIVE_ACTION_STATUSES = new Set(["requested", "accepted", "executing"]);
  const TERMINAL_ACTION_STATUSES = new Set([
    "policy_rejected",
    "succeeded",
    "failed",
    "timed_out",
  ]);

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function finiteNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function mergeFleet(registryPayload, telemetryPayload, vehicleSnapshot) {
    const rows = asArray(registryPayload?.vehicles);
    const telemetryById = new Map(
      asArray(telemetryPayload?.nodes).map((node) => [String(node.node_id), node])
    );
    const vehiclesById = new Map(
      asArray(vehicleSnapshot?.vehicles).map((vehicle) => [String(vehicle.id), vehicle])
    );
    const ids = new Set([
      ...rows.map((row) => String(row.node_id)),
      ...telemetryById.keys(),
      ...vehiclesById.keys(),
    ]);
    const registryById = new Map(rows.map((row) => [String(row.node_id), row]));

    return [...ids].sort().map((id) => {
      const row = registryById.get(id) || {};
      const node = telemetryById.get(id) || {};
      const vehicle = vehiclesById.get(id) || {};
      const local = node.local_position || {};
      const battery = node.battery || {};
      const vehicleTelemetry = vehicle.telemetry || {};
      const stale = Boolean(
        node.stale ?? vehicleTelemetry.stale ?? row.stale ?? true
      );
      const connected = Boolean(
        (node.connected ?? vehicle.connected ?? row.connected ?? false) && !stale
      );

      return {
        id,
        nodeId: id,
        displayName: vehicle.display_name || id,
        backend: row.backend || telemetryPayload?.backend || "px4_sitl",
        backendMode: row.backend_mode || telemetryPayload?.backend_mode || "sitl",
        endpoint: row.endpoint || row.transport_endpoint || null,
        telemetryEndpoint: row.telemetry_endpoint || null,
        systemId: row.system_id ?? node.system_id ?? null,
        componentId: row.component_id ?? node.component_id ?? null,
        enabled: row.enabled !== false,
        connected,
        stale,
        connectionStatus: row.connection_status || (connected ? "connected" : "offline"),
        activeAction: row.active_action || null,
        lastError: row.last_error || null,
        telemetryAgeMs: row.telemetry_freshness_ms ?? node.age_ms ?? vehicleTelemetry.age_ms ?? null,
        vehicleType: vehicle.vehicle_type || node.vehicle_type || "unknown",
        flightMode: node.flight_mode || vehicleTelemetry.mode || null,
        armed: node.armed ?? vehicleTelemetry.armed ?? null,
        altitudeM: finiteNumber(local.altitude_m),
        zDownM: finiteNumber(local.z_down_m),
        batteryPercent: finiteNumber(battery.percent ?? vehicleTelemetry.battery_percent),
        groundSpeedMps: finiteNumber(node.velocity_mps?.ground_speed ?? vehicleTelemetry.ground_speed_mps),
        lastSeen: node.last_seen || null,
      };
    });
  }

  function findVehicle(fleet, nodeId) {
    const rows = asArray(fleet);
    return rows.find((vehicle) => vehicle.id === nodeId) || rows[0] || null;
  }

  function isFleetReady(fleet) {
    const enabled = asArray(fleet).filter((vehicle) => vehicle.enabled !== false);
    return enabled.length > 0 && enabled.every(
      (vehicle) => vehicle.connected === true && vehicle.stale === false
    );
  }

  function canExecute(vehicle, apiStatus) {
    if (apiStatus !== "live") return { allowed: false, reason: "Runtime API 未连接" };
    if (!vehicle) return { allowed: false, reason: "没有已注册载具" };
    if (!vehicle.enabled) return { allowed: false, reason: `${vehicle.id} 未启用` };
    if (!vehicle.connected || vehicle.stale) return { allowed: false, reason: `${vehicle.id} 遥测离线或已过期` };
    if (!vehicle.endpoint) return { allowed: false, reason: `${vehicle.id} 缺少传输端点` };
    if (!Number.isInteger(vehicle.systemId) || !Number.isInteger(vehicle.componentId)) {
      return { allowed: false, reason: `${vehicle.id} 缺少 MAVLink identity` };
    }
    return { allowed: true, reason: "允许调用" };
  }

  function markFleetStale(fleet) {
    return asArray(fleet).map((vehicle) => ({
      ...vehicle,
      connected: false,
      stale: true,
      connectionStatus: "stale",
    }));
  }

  function markVehicleSnapshotStale(snapshot) {
    if (!snapshot || typeof snapshot !== "object") return snapshot;
    return {
      ...snapshot,
      vehicles: asArray(snapshot.vehicles).map((vehicle) => ({
        ...vehicle,
        connected: false,
        telemetry: { ...(vehicle.telemetry || {}), stale: true },
      })),
    };
  }

  function buildRuntimeRequest(vehicle, altitudeM, options = {}) {
    if (!vehicle) throw new Error("没有已注册载具");
    if (!vehicle.enabled) throw new Error(`${vehicle.id} 未启用`);
    if (!vehicle.endpoint) throw new Error(`${vehicle.id} 缺少传输端点`);
    if (!Number.isInteger(vehicle.systemId) || !Number.isInteger(vehicle.componentId)) {
      throw new Error(`${vehicle.id} 缺少 MAVLink identity`);
    }
    if (options.requireConnected !== false && (!vehicle.connected || vehicle.stale)) {
      throw new Error(`${vehicle.id} 遥测离线或已过期`);
    }
    return {
      backend: vehicle.backend,
      backend_mode: vehicle.backendMode,
      backend_enabled: true,
      node_id: vehicle.nodeId,
      system_id: vehicle.systemId,
      component_id: vehicle.componentId,
      transport_endpoint: vehicle.endpoint,
      altitude_m: Number(altitudeM.toFixed(1)),
      connect_timeout_ms: 5000,
      command_timeout_ms: 10000,
      observe_timeout_ms: 25000,
      threshold_ratio: 0.7,
      auto_land: false,
    };
  }

  function buildOperationalActionRequest(vehicle, actionType, altitudeM, identifiers) {
    const base = buildRuntimeRequest(vehicle, altitudeM);
    const action = String(actionType || "").toLowerCase();
    if (!['takeoff', 'land'].includes(action)) {
      throw new Error(`不支持的正式动作：${actionType}`);
    }
    for (const name of ["request_id", "trace_id", "idempotency_key"]) {
      if (!identifiers?.[name]) throw new Error(`${name} 不能为空`);
    }
    const request = {
      backend: base.backend,
      backend_mode: base.backend_mode,
      backend_enabled: true,
      node_id: base.node_id,
      system_id: base.system_id,
      component_id: base.component_id,
      transport_endpoint: base.transport_endpoint,
      command_timeout_ms: base.command_timeout_ms,
      observe_timeout_ms: base.observe_timeout_ms,
      request_id: identifiers.request_id,
      trace_id: identifiers.trace_id,
      idempotency_key: identifiers.idempotency_key,
      command_source: "ground_station",
    };
    if (action === "takeoff") {
      request.altitude_m = base.altitude_m;
      request.altitude_tolerance_m = 0.3;
      request.stable_duration_ms = 1000;
    }
    return request;
  }

  function actionStatus(record) {
    return String(record?.lifecycle_status || record?.status || "unknown").toLowerCase();
  }

  function isActiveAction(record) {
    return ACTIVE_ACTION_STATUSES.has(actionStatus(record));
  }

  function isTerminalAction(record) {
    return TERMINAL_ACTION_STATUSES.has(actionStatus(record));
  }

  function normalizeActionRecord(payload, fallback = {}) {
    const raw = payload && typeof payload === "object" ? payload : {};
    const result = raw.result && typeof raw.result === "object" ? raw.result : {};
    const merged = { ...result, ...raw };
    const status = actionStatus(merged);
    const nodeId = merged.resolved_node_id || merged.node_id || fallback.node_id || null;
    const actionType = String(
      merged.action_type || merged.action || fallback.action_type || "unknown"
    ).toLowerCase();
    const ackEvidence = asArray(merged.ack_evidence);
    const completionEvidence = merged.completion_evidence || null;
    const failedStatus = ["policy_rejected", "failed", "timed_out"].includes(status);
    return {
      ...merged,
      contract_version: merged.contract_version || fallback.contract_version || null,
      node_id: nodeId,
      action_type: actionType,
      action_id: merged.action_id || fallback.action_id || null,
      request_id: merged.request_id || fallback.request_id || null,
      trace_id: merged.trace_id || fallback.trace_id || null,
      idempotency_key: merged.idempotency_key || fallback.idempotency_key || null,
      status,
      ack_evidence: ackEvidence,
      completion_evidence: completionEvidence,
      completion_state: merged.completion_state || completionEvidence?.status || null,
      request_parameters: merged.request_parameters || (fallback.altitude_m != null
        ? { altitude_m: fallback.altitude_m } : null),
      failure_reason: merged.failure_reason
        || merged.error
        || fallback.failure_reason
        || (failedStatus ? merged.code : null)
        || null,
      received_at: raw.received_at || fallback.received_at || new Date().toISOString(),
      raw: raw.raw || raw,
    };
  }

  function mergeActionRecords(current, incoming) {
    const rows = [...asArray(current)];
    for (const record of asArray(incoming)) {
      const normalized = normalizeActionRecord(record);
      const index = rows.findIndex((item) =>
        (normalized.action_id && item.action_id === normalized.action_id)
        || (normalized.request_id && item.request_id === normalized.request_id)
      );
      if (index >= 0) {
        const previous = rows[index];
        if (previous.node_id !== normalized.node_id) continue;
        // A delayed executing response must not roll back a server terminal record.
        if (isTerminalAction(previous) && !isTerminalAction(normalized)) continue;
        rows[index] = { ...previous, ...normalized,
          request_parameters: normalized.request_parameters ?? previous.request_parameters,
          smoke: normalized.smoke ?? previous.smoke,
          received_at: previous.received_at };
      }
      else rows.push(normalized);
    }
    return rows.sort((a, b) => {
      const aTime = a.timestamps?.requested_at || a.received_at || "";
      const bTime = b.timestamps?.requested_at || b.received_at || "";
      return String(bTime).localeCompare(String(aTime));
    });
  }

  function latestActionForNode(records, nodeId) {
    return asArray(records).find((record) => record.node_id === nodeId) || null;
  }

  function ackAccepted(ack) {
    if (!ack || ack.timeout === true) return false;
    const result = ack.result_name ?? ack.result;
    return result === 0 || ["ACCEPTED", "MAV_RESULT_ACCEPTED"].includes(String(result || "").toUpperCase());
  }

  function actionTelemetry(record) {
    const raw = record?.raw || record || {};
    const result = raw.result && typeof raw.result === "object" ? raw.result : {};
    const observation = raw.altitude_observation || result.altitude_observation || {};
    const threshold = raw.threshold_reached ?? result.threshold_reached ?? observation.threshold_reached;
    return {
      maxAltitudeAction: finiteNumber(raw.max_altitude_m ?? result.max_altitude_m ?? observation.max_altitude_m),
      lastZ: finiteNumber(raw.last_z ?? result.last_z ?? observation.last_z),
      thresholdReached: typeof threshold === "boolean" ? threshold : null,
    };
  }

  function actionStages(record) {
    if (!record) {
      return [
        ["request", "未请求", "idle"],
        ["policy", "待决策", "idle"],
        ["ack", "待 ACK", "idle"],
        ["execution", "未执行", "idle"],
        ["completion", "待遥测确认", "idle"],
      ].map(([key, label, tone]) => ({ key, label, tone }));
    }
    const status = actionStatus(record);
    const policyCode = String(
      record.policy_decision?.decision_code || record.policy_decision?.decision || ""
    ).toUpperCase();
    const acceptedAcks = asArray(record.ack_evidence).filter(ackAccepted);
    const completionReached = status === "succeeded"
      && record.completion_evidence?.completion_reached === true;
    const failed = status === "failed" || status === "timed_out";
    return [
      ["request", record.action_id ? "Runtime 已登记" : "客户端请求 / 待确认", record.action_id ? "done" : "warn"],
      [
        "policy",
        status === "policy_rejected" ? `拒绝 ${policyCode || ""}`.trim()
          : status === "requested" ? "评估中"
            : policyCode ? policyCode : "接口暂不支持",
        status === "policy_rejected" ? "failed" : status === "requested" ? "active" : policyCode === "ALLOW" ? "done" : "warn",
      ],
      [
        "ack",
        acceptedAcks.length ? `${acceptedAcks.length} 项已接受`
          : status === "requested" || status === "accepted" ? "等待 ACK"
            : "无 ACK 证据",
        acceptedAcks.length ? "done"
          : failed || status === "policy_rejected" ? "failed"
            : status === "succeeded" ? "warn" : "active",
      ],
      [
        "execution",
        status === "executing" ? "执行中"
          : status === "succeeded" ? "执行完成"
            : status === "accepted" ? "准入中"
              : status === "policy_rejected" ? "未执行"
                : failed ? "执行未完成" : "等待执行",
        status === "executing" || status === "accepted" ? "active" : status === "succeeded" ? "done" : failed ? "failed" : "idle",
      ],
      [
        "completion",
        completionReached ? "遥测已确认"
          : status === "timed_out" ? "遥测确认超时"
            : status === "failed" || status === "policy_rejected" ? "未确认"
              : "待遥测确认",
        completionReached ? "done" : status === "timed_out" || status === "failed" || status === "policy_rejected" ? "failed" : "active",
      ],
    ].map(([key, label, tone]) => ({ key, label, tone }));
  }

  function actionPermission(vehicle, apiStatus, records, actionType) {
    const base = canExecute(vehicle, apiStatus);
    if (!base.allowed) return base;
    const activeRows = asArray(records).filter(
      (record) => record.node_id === vehicle.id && (isActiveAction(record) || record.client_pending)
    );
    const active = activeRows.find((record) => record.action_type === "land") || activeRows[0];
    if (!active) return { allowed: true, reason: "允许调用" };
    const requestedAction = String(actionType || "").toLowerCase();
    if (requestedAction === "land" && active.action_type !== "land") {
      return { allowed: true, reason: `LAND 将请求中止 ${active.action_type.toUpperCase()}` };
    }
    return { allowed: false, reason: `${vehicle.id} 正在执行 ${active.action_type.toUpperCase()}` };
  }

  function eventMatchesAction(event, record) {
    if (!event || !record) return false;
    const values = [event, event.payload, event.details, event.raw, event.raw_event].filter(Boolean);
    if (values.some((value) => value.node_id && value.node_id !== record.node_id)) return false;
    for (const field of ["action_id", "request_id"]) {
      if (record[field] && values.some((value) => value[field] && value[field] !== record[field])) return false;
    }
    const matches = (field) => record[field] && values.some((value) => value?.[field] === record[field]);
    if (matches("action_id") || matches("request_id") || matches("trace_id")) return true;
    return false;
  }

  function createVehicleSnapshotMessage(snapshot) {
    if (!snapshot || typeof snapshot !== "object") throw new Error("vehicle snapshot 不能为空");
    const spatial = asArray(snapshot.vehicles).map((vehicle) => vehicle.spatial).find(Boolean) || {};
    return {
      type: "uav-swarm/vehicle-snapshot",
      version: "1.0",
      scene_id: snapshot.scene_id || spatial.scene_id || null,
      map_version: snapshot.map_version || spatial.map_version || null,
      source_timestamp: snapshot.timestamp || snapshot.source_timestamp || spatial.sample_timestamp || null,
      payload: snapshot,
    };
  }

  function validateSimulationReadyMessage(data) {
    return Boolean(
      data?.type === "uav-swarm/simulation-ready"
      && data?.payload?.contractVersion === "1.0"
      && data?.payload?.integration === "parent-snapshot"
    );
  }

  // --- 观察复核（L2）记录 ---------------------------------------------------
  //
  // 采集到图像（L1，CAPTURE）与判定"是否观察到目标"（L2）是两件事。
  // 三方已对齐：CAPTURE 的 pass **不能**把 OBSERVE、巡检步骤或原任务标记为完成。
  //
  // ⚠️ 本段是 Python 侧 `src/uav_runtime/observation/review_record.py` 的
  // **对照实现**。前端是静态页面（无构建步骤），不能 import Python，因此规则
  // 必须在两端各写一次。**两份实现必须行为一致** —— 否则会出现"前端放了、
  // 后端拒了"这种让人以为是 bug 的分歧。
  // 用例逐条对应：`tests/observation-review.test.js` ↔
  // `tests/unit/test_observation_review_record.py`。改一侧请同步另一侧。
  const REVIEW_VERSION = "0.1";
  const HUMAN_REVIEWER_PREFIX = "human:";
  const LINKED_TASK_COMPLETION_NOT_ASSERTED = "not_asserted";
  const REVIEW_OUTCOMES = Object.freeze({
    observed: "observed",
    not_observed: "not_observed",
    undetermined: "undetermined",
  });
  const REVIEW_REQUIRED_FIELDS = [
    "review_version", "review_id", "created_at", "task_id", "target_id",
    "capture_id", "image", "criterion_version", "reviewer", "reviewed_at",
    "outcome", "confidence", "linked_task_completion",
  ];
  const REVIEW_IMAGE_REQUIRED_FIELDS = [
    "ref", "sha256", "width", "height", "encoding", "captured_at",
    "vehicle_id", "camera_id",
  ];
  //: 必须是**非空字符串**的标识类字段。存在性与非空是两件事。
  const REVIEW_IDENTITY_FIELDS = [
    "review_id", "task_id", "target_id", "capture_id",
    "criterion_version", "reviewed_at",
  ];
  const SHA256_PATTERN = /^[0-9a-f]{64}$/;

  function nonEmptyString(value) {
    return typeof value === "string" && value.trim() !== "";
  }

  /**
   * 校验一条复核记录。返回 `{ok, record?, violations}` —— **不抛异常**。
   *
   * 前端要能一次把全部问题显示给操作者，抛异常会逼出"改一个跑一次"的循环。
   * 违规是**一次报全**的，与 Python 侧一致。
   */
  function validateObservationReview(record) {
    const violations = [];
    if (!record || typeof record !== "object" || Array.isArray(record)) {
      return {
        ok: false,
        violations: [{
          code: "not_an_object",
          actual_type: Array.isArray(record) ? "array" : typeof record,
        }],
      };
    }

    // ⚠️ 只查"键在不在"是不够的：**空字符串**能通过存在性检查，而一个
    // `capture_id: ""` 的记录没有任何东西能把它关联到某次采集 —— 恰好废掉
    // 这个字段的全部意义。因此标识类字段必须是**非空字符串**。
    // （这个洞最初是在这里被测试抓到的，Python 侧一并修了。）
    for (const field of REVIEW_REQUIRED_FIELDS) {
      if (!(field in record)) violations.push({ code: "missing_field", field });
    }
    for (const field of REVIEW_IDENTITY_FIELDS) {
      if (field in record && !nonEmptyString(record[field])) {
        violations.push({
          code: "empty_identity_field", field, value: record[field],
          hint: "标识类字段必须是非空字符串。空值会让这条记录无法关联到任何任务、目标或采集。",
        });
      }
    }

    // 规则一：不得编造数值置信度。
    // 检查的是"键存在且值为 null"，不是"值假" —— `confidence: 0` 也要拒，
    // 它同样是把主观印象伪装成测量值。缺失也按同一条规则报：省略会让
    // "忘了填"与"确实没有"看起来一样，而这条规则恰恰要区分这件事。
    if (!("confidence" in record) || record.confidence !== null) {
      violations.push({
        code: "confidence_must_be_null",
        field: "confidence",
        value: record.confidence === undefined ? null : record.confidence,
        hint: "人工结论不伪造数值置信度。必须显式填 null，并把判断依据写进 region 或 note。",
      });
    }

    // 规则二：reviewer 必须是人工。
    // `null` 必须被拒 —— 不能"值为空就跳过检查"，那样 reviewer=null 的
    // 记录会绕过这条规则。
    const reviewer = record.reviewer;
    if (typeof reviewer !== "string" || !reviewer.startsWith(HUMAN_REVIEWER_PREFIX)) {
      violations.push({
        code: "reviewer_not_human",
        field: "reviewer",
        value: reviewer === undefined ? null : reviewer,
        hint: "本阶段 L2 只接受人工复核，reviewer 必须以 human: 开头。"
          + "仿真真值只能用于离线标注与评价，不得写入运行时检测或冒充检测结果。",
      });
    } else if (!reviewer.slice(HUMAN_REVIEWER_PREFIX.length).trim()) {
      violations.push({
        code: "reviewer_not_human", field: "reviewer", value: reviewer,
        hint: "human: 后必须有实际标识，否则无法追溯是谁复核的。",
      });
    }

    if (record.outcome !== undefined
      && !Object.prototype.hasOwnProperty.call(REVIEW_OUTCOMES, record.outcome)) {
      violations.push({
        code: "invalid_outcome", field: "outcome", value: record.outcome,
        allowed: Object.keys(REVIEW_OUTCOMES),
      });
    }

    // 规则三：否定/未判定必须给出依据。
    // not_observed 只表示"在这份图像中未按判据看到"，**不证明目标不存在**；
    // 没有依据的否定与"检测器没报"在数据上无法区分 —— 而后者不能作为结论。
    const hasRegion = record.region && typeof record.region === "object"
      && !Array.isArray(record.region) && Object.keys(record.region).length > 0;
    const hasNote = nonEmptyString(record.note);
    if ((record.outcome === "not_observed" || record.outcome === "undetermined")
      && !hasRegion && !hasNote) {
      violations.push({
        code: "missing_negative_evidence", field: "note", outcome: record.outcome,
        hint: `outcome='${record.outcome}' 必须给出 region 或 note。`
          + "not_observed 只表示「在这份图像中未按判据看到」，不证明目标不存在；"
          + "没有依据的否定与「检测器没报」无法区分。",
      });
    }

    const image = record.image;
    if (image !== undefined && image !== null) {
      if (typeof image !== "object" || Array.isArray(image)) {
        violations.push({ code: "invalid_image", field: "image", value: image });
      } else {
        for (const field of REVIEW_IMAGE_REQUIRED_FIELDS) {
          if (!(field in image)) violations.push({ code: "missing_field", field: `image.${field}` });
        }
        if (image.sha256 !== undefined && !SHA256_PATTERN.test(String(image.sha256))) {
          violations.push({
            code: "malformed_sha256", field: "image.sha256", value: image.sha256,
            hint: "必须是 64 位小写十六进制。",
          });
        }
        if (typeof image.ref === "string" && typeof image.sha256 === "string") {
          const expected = `sha256:${image.sha256}`;
          if (image.ref !== expected) {
            violations.push({
              code: "image_ref_hash_mismatch", field: "image.ref",
              value: image.ref, expected,
              hint: "ref 必须与 sha256 自洽。引用不可变，否则同一条记录会指向不同图像。",
            });
          }
        }
      }
    }

    // 结构性约束：记录**无从表达**"任务已完成"。
    // 不靠"记得别那么做"，而是让它没有地方可写。
    if (record.linked_task_completion !== undefined
      && record.linked_task_completion !== LINKED_TASK_COMPLETION_NOT_ASSERTED) {
      violations.push({
        code: "task_completion_not_representable",
        field: "linked_task_completion",
        value: record.linked_task_completion,
        allowed: [LINKED_TASK_COMPLETION_NOT_ASSERTED],
        hint: "复核记录无从表达「任务已完成」。CAPTURE 成功不能自动完成 OBSERVE、巡检步骤"
          + "或原任务；要表达任务完成需要另一个显式动作（尚未设计）。",
      });
    }

    if (violations.length) return { ok: false, violations };

    const normalized = { ...record };
    normalized.review_version = String(normalized.review_version || REVIEW_VERSION);
    normalized.confidence = null;
    normalized.linked_task_completion = LINKED_TASK_COMPLETION_NOT_ASSERTED;
    normalized.outcome = String(normalized.outcome);
    return { ok: true, record: normalized, violations: [] };
  }

  /**
   * 由记录内容派生 16 位十六进制标识（确定性）。
   *
   * 用排序键的 JSON：同一份内容因键序不同而得到不同 id，会让"是不是同一条"
   * 无法判断。
   *
   * ⚠️ 这是**非加密**摘要，只用于生成 `review_id`。**不用于安全目的** ——
   * 需要密码学哈希的是图像本身，那由 `image.sha256` 承担，且应由采集端计算。
   * Python 侧用的是真 SHA-256；两端的 `review_id` **不会相同**，这是有意的：
   * 记录以 Python 侧写的文件为准，前端生成的 id 只用于本地预览与导出。
   */
  function reviewDigest(payload) {
    const canonical = JSON.stringify(payload, Object.keys(payload).sort());
    let h1 = 0x811c9dc5;
    let h2 = 0x01000193;
    for (let i = 0; i < canonical.length; i += 1) {
      const code = canonical.charCodeAt(i);
      h1 = Math.imul(h1 ^ code, 0x01000193) >>> 0;
      h2 = Math.imul(h2 + code, 0x85ebca6b) >>> 0;
    }
    return (h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0")).slice(0, 16);
  }

  /** 构造一条复核记录。返回 `{ok, record?, violations}`，与校验器同形。 */
  function buildObservationReview(args) {
    const a = args || {};
    const record = {
      review_version: REVIEW_VERSION,
      created_at: a.createdAt || new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      task_id: a.taskId,
      target_id: a.targetId,
      capture_id: a.captureId,
      image: a.image ? { ...a.image } : a.image,
      criterion_version: a.criterionVersion,
      reviewer: a.reviewer,
      reviewed_at: a.reviewedAt,
      outcome: a.outcome,
      // 本阶段人工结论一律不编造数值置信度。
      confidence: null,
      linked_task_completion: LINKED_TASK_COMPLETION_NOT_ASSERTED,
    };
    if (a.region !== undefined) record.region = { ...a.region };
    if (a.note !== undefined) record.note = a.note;

    record.review_id = `rev-${reviewDigest(record)}`;
    // 构建入口也做校验 —— 不能只在校验时拦，否则可以经 build 造出一条
    // reviewer="detector:..." 的记录，再想办法绕过校验。
    return validateObservationReview(record);
  }

  return {
    mergeFleet,
    findVehicle,
    isFleetReady,
    canExecute,
    markFleetStale,
    markVehicleSnapshotStale,
    buildRuntimeRequest,
    buildOperationalActionRequest,
    normalizeActionRecord,
    mergeActionRecords,
    latestActionForNode,
    isActiveAction,
    isTerminalAction,
    actionStages,
    ackAccepted,
    actionTelemetry,
    actionPermission,
    eventMatchesAction,
    createVehicleSnapshotMessage,
    validateSimulationReadyMessage,
    // 观察复核（L2）：与 Python 侧 review_record.py 对照
    REVIEW_VERSION,
    HUMAN_REVIEWER_PREFIX,
    LINKED_TASK_COMPLETION_NOT_ASSERTED,
    REVIEW_OUTCOMES,
    validateObservationReview,
    buildObservationReview,
  };
});
