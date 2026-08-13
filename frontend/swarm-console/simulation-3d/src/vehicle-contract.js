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

const FRAME_TYPES = new Set(["ENU", "NED", "WGS84"]);

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function requiredFiniteNumber(value, fieldName) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${fieldName} must be a finite number.`);
  }
  return value;
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
  const position = pose.position_m || pose.position || rawVehicle.position;
  const frame = String(
    pose.frame || rawVehicle.frame || snapshotFrame?.type || snapshotFrame || "ENU",
  ).toUpperCase();

  if (!FRAME_TYPES.has(frame)) {
    throw new Error(`Unsupported coordinate frame: ${frame}`);
  }
  if (!position || typeof position !== "object") {
    throw new Error(`Vehicle ${rawVehicle.id} requires pose.position_m or pose.position.`);
  }

  if (frame === "WGS84") {
    return {
      frame,
      longitudeDeg: requiredFiniteNumber(
        position.longitude_deg ?? position.longitude ?? position.lon,
        `Vehicle ${rawVehicle.id} longitude`,
      ),
      latitudeDeg: requiredFiniteNumber(
        position.latitude_deg ?? position.latitude ?? position.lat,
        `Vehicle ${rawVehicle.id} latitude`,
      ),
      altitudeM: requiredFiniteNumber(
        position.altitude_m ?? position.altitude ?? position.alt,
        `Vehicle ${rawVehicle.id} altitude`,
      ),
    };
  }

  const x = requiredFiniteNumber(
    position.x_m ?? position.x,
    `Vehicle ${rawVehicle.id} position x`,
  );
  const y = requiredFiniteNumber(
    position.y_m ?? position.y,
    `Vehicle ${rawVehicle.id} position y`,
  );
  const z = requiredFiniteNumber(
    position.z_m ?? position.z,
    `Vehicle ${rawVehicle.id} position z`,
  );

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
  const batteryPercent = finiteNumber(telemetry.battery_percent, -1);
  const linkQualityPercent = finiteNumber(telemetry.link_quality_percent, -1);
  if (batteryPercent < -1 || batteryPercent > 100) {
    throw new Error(`Vehicle ${rawVehicle.id} battery_percent must be between 0 and 100.`);
  }
  if (linkQualityPercent < -1 || linkQualityPercent > 100) {
    throw new Error(`Vehicle ${rawVehicle.id} link_quality_percent must be between 0 and 100.`);
  }
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
      batteryPercent,
      linkQualityPercent,
      stale: Boolean(telemetry.stale),
      ageMs: Number.isFinite(Number(telemetry.age_ms))
        ? Math.max(0, Number(telemetry.age_ms))
        : null,
    },
    agent: {
      id: String(agent.id || ""),
      status: String(agent.status || "unassigned"),
      intent: String(agent.intent || ""),
    },
    color: rawVehicle.color ? String(rawVehicle.color) : "",
    poseSource: String(rawVehicle.pose_source || ""),
  };
}

export function normalizeVehicleSnapshot(rawSnapshot) {
  if (!rawSnapshot || typeof rawSnapshot !== "object") {
    throw new Error("Vehicle snapshot must be an object.");
  }

  if (rawSnapshot.version !== VEHICLE_CONTRACT_VERSION) {
    throw new Error(`Unsupported vehicle snapshot version: ${rawSnapshot.version}`);
  }
  if (!Array.isArray(rawSnapshot.vehicles)) {
    throw new Error("Vehicle snapshot vehicles must be an array.");
  }
  if (rawSnapshot.full_state !== undefined && typeof rawSnapshot.full_state !== "boolean") {
    throw new Error("Vehicle snapshot full_state must be a boolean.");
  }
  if (rawSnapshot.source === undefined) {
    throw new Error("Vehicle snapshot requires source.");
  }
  const frameType = String(rawSnapshot.frame?.type || rawSnapshot.frame || "").toUpperCase();
  if (!FRAME_TYPES.has(frameType)) {
    throw new Error(`Unsupported coordinate frame: ${frameType || "missing"}`);
  }

  const vehicles = rawSnapshot.vehicles.map((vehicle) =>
    normalizeVehicle(vehicle, rawSnapshot),
  );
  const ids = new Set();
  for (const vehicle of vehicles) {
    if (ids.has(vehicle.id)) {
      throw new Error(`Duplicate vehicle id: ${vehicle.id}`);
    }
    ids.add(vehicle.id);
  }

  const parsedTimestamp = Date.parse(rawSnapshot.timestamp || "");
  const timestampMs = typeof rawSnapshot.timestamp_ms === "number" && Number.isFinite(rawSnapshot.timestamp_ms)
    ? rawSnapshot.timestamp_ms
    : Number.isFinite(parsedTimestamp)
      ? parsedTimestamp
      : NaN;
  if (!Number.isFinite(timestampMs)) {
    throw new Error("Vehicle snapshot requires a valid timestamp or timestamp_ms.");
  }

  return {
    version: VEHICLE_CONTRACT_VERSION,
    timestampMs,
    fullState: rawSnapshot.full_state !== false,
    source: normalizeSource(rawSnapshot.source),
    frame: rawSnapshot.frame || { type: "ENU" },
    vehicles,
  };
}
