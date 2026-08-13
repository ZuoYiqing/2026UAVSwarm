(function attachConsoleModel(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.SwarmConsoleModel = api;
  }
})(typeof window !== "undefined" ? window : undefined, function createConsoleModel() {
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

  return {
    mergeFleet,
    findVehicle,
    isFleetReady,
    canExecute,
    markFleetStale,
    markVehicleSnapshotStale,
    buildRuntimeRequest,
  };
});
