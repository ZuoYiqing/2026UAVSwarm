export const VEHICLE_CONTRACT_VERSION = "1.0";

export const VEHICLE_TYPES = Object.freeze([
  "multirotor",
  "fixed_wing",
  "vtol",
  "ugv",
  "usv",
  "uuv",
  "unknown",
]);

const TYPE_ALIASES = Object.freeze({
  quadrotor: "multirotor",
  multicopter: "multirotor",
  "fixed-wing": "fixed_wing",
  fixedwing: "fixed_wing",
  rover: "ugv",
  boat: "usv",
});

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function normalizeVehicleType(value) {
  const candidate = String(value || "unknown").toLowerCase();
  const normalized = TYPE_ALIASES[candidate] || candidate;
  return VEHICLE_TYPES.includes(normalized) ? normalized : "unknown";
}

function normalizeSource(vehicleSource, snapshotSource) {
  const source = vehicleSource || snapshotSource || {};
  if (typeof source === "string") {
    return {
      id: source,
      kind: "unknown",
      label: source,
    };
  }
  return {
    id: String(source.id || "unknown"),
    kind: String(source.kind || "unknown"),
    label: String(source.label || source.id || "unknown"),
  };
}

function normalizePosition(rawVehicle, snapshotFrame) {
  const pose = rawVehicle.pose || {};
  const position = pose.position_m || pose.position || rawVehicle.position || {};
  const frame = String(
    pose.frame || rawVehicle.frame || snapshotFrame?.type || snapshotFrame || "ENU",
  ).toUpperCase();

  if (frame === "WGS84") {
    return {
      frame,
      longitudeDeg: finiteNumber(
        position.longitude_deg ?? position.longitude ?? position.lon,
      ),
      latitudeDeg: finiteNumber(
        position.latitude_deg ?? position.latitude ?? position.lat,
      ),
      altitudeM: finiteNumber(
        position.altitude_m ?? position.altitude ?? position.alt,
      ),
    };
  }

  const x = finiteNumber(position.x_m ?? position.x);
  const y = finiteNumber(position.y_m ?? position.y);
  const z = finiteNumber(position.z_m ?? position.z);

  if (frame === "NED") {
    return {
      frame: "ENU",
      eastM: y,
      northM: x,
      upM: -z,
      sourceFrame: "NED",
    };
  }

  return {
    frame: "ENU",
    eastM: x,
    northM: y,
    upM: z,
    sourceFrame: frame,
  };
}

function normalizeAttitude(rawVehicle) {
  const attitude = rawVehicle.pose?.attitude_deg || rawVehicle.attitude_deg || {};
  return {
    rollDeg: finiteNumber(attitude.roll),
    pitchDeg: finiteNumber(attitude.pitch),
    yawDeg: finiteNumber(attitude.yaw ?? attitude.heading),
  };
}

function normalizeVelocity(rawVehicle) {
  const velocity = rawVehicle.velocity_mps || {};
  const eastMps = finiteNumber(velocity.east ?? velocity.x);
  const northMps = finiteNumber(velocity.north ?? velocity.y);
  const upMps = finiteNumber(velocity.up ?? velocity.z);
  const providedSpeed = Number(rawVehicle.telemetry?.ground_speed_mps);
  return {
    eastMps,
    northMps,
    upMps,
    groundSpeedMps: Number.isFinite(providedSpeed)
      ? providedSpeed
      : Math.hypot(eastMps, northMps),
  };
}

function normalizeVehicle(rawVehicle, snapshot) {
  if (!rawVehicle || !String(rawVehicle.id || "").trim()) {
    throw new Error("Each vehicle requires a non-empty id.");
  }

  const telemetry = rawVehicle.telemetry || {};
  const agent = rawVehicle.agent || {};
  return {
    id: String(rawVehicle.id),
    displayName: String(rawVehicle.display_name || rawVehicle.callsign || rawVehicle.id),
    vehicleType: normalizeVehicleType(
      rawVehicle.vehicle_type || rawVehicle.type,
    ),
    model: String(rawVehicle.model || "unspecified"),
    source: normalizeSource(rawVehicle.source, snapshot.source),
    connected: rawVehicle.connected !== false,
    position: normalizePosition(rawVehicle, snapshot.frame),
    attitude: normalizeAttitude(rawVehicle),
    velocity: normalizeVelocity(rawVehicle),
    telemetry: {
      armed: Boolean(telemetry.armed),
      mode: String(telemetry.mode || "UNKNOWN"),
      batteryPercent: finiteNumber(telemetry.battery_percent, -1),
      linkQualityPercent: finiteNumber(telemetry.link_quality_percent, -1),
    },
    agent: {
      id: String(agent.id || ""),
      status: String(agent.status || "unassigned"),
      intent: String(agent.intent || ""),
    },
    color: rawVehicle.color ? String(rawVehicle.color) : "",
  };
}

export function normalizeVehicleSnapshot(rawSnapshot) {
  if (!rawSnapshot || typeof rawSnapshot !== "object") {
    throw new Error("Vehicle snapshot must be an object.");
  }

  const vehicles = Array.isArray(rawSnapshot.vehicles)
    ? rawSnapshot.vehicles.map((vehicle) =>
        normalizeVehicle(vehicle, rawSnapshot),
      )
    : [];
  const ids = new Set();
  for (const vehicle of vehicles) {
    if (ids.has(vehicle.id)) {
      throw new Error(`Duplicate vehicle id: ${vehicle.id}`);
    }
    ids.add(vehicle.id);
  }

  const parsedTimestamp = Date.parse(rawSnapshot.timestamp || "");
  const timestampMs = Number.isFinite(Number(rawSnapshot.timestamp_ms))
    ? Number(rawSnapshot.timestamp_ms)
    : Number.isFinite(parsedTimestamp)
      ? parsedTimestamp
      : Date.now();

  return {
    version: String(rawSnapshot.version || VEHICLE_CONTRACT_VERSION),
    timestampMs,
    fullState: rawSnapshot.full_state !== false,
    source: normalizeSource(rawSnapshot.source),
    frame: rawSnapshot.frame || { type: "ENU" },
    vehicles,
  };
}

