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
  };
});
