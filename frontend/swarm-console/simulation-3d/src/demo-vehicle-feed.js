const DEMO_DURATION_SECONDS = 120;

const DEMO_VEHICLES = Object.freeze([
  {
    id: "MR-01",
    displayName: "MR-01",
    vehicleType: "multirotor",
    model: "quad-x",
    color: "#36c7f4",
    altitudeBias: 0,
    mode: "AUTO.MISSION",
    agentStatus: "executing",
    intent: "inspect-sector-a",
    points: [
      [-128, -72, 32],
      [-66, -18, 46],
      [-5, 32, 58],
      [70, 62, 52],
      [130, 10, 42],
      [72, -66, 36],
      [-24, -86, 44],
    ],
  },
  {
    id: "MR-02",
    displayName: "MR-02",
    vehicleType: "multirotor",
    model: "hexacopter",
    color: "#42d883",
    altitudeBias: 0,
    mode: "AUTO.LOITER",
    agentStatus: "standby",
    intent: "hold-east-gate",
    points: [
      [-100, 64, 38],
      [-35, 92, 48],
      [30, 70, 62],
      [104, 36, 54],
      [58, -12, 44],
      [-28, 8, 50],
    ],
  },
  {
    id: "FW-01",
    displayName: "FW-01",
    vehicleType: "fixed_wing",
    model: "fixed-wing-trainer",
    color: "#f5b84c",
    altitudeBias: 0,
    mode: "AUTO.CRUISE",
    agentStatus: "executing",
    intent: "perimeter-patrol",
    points: [
      [-205, -115, 92],
      [-210, 105, 96],
      [0, 155, 102],
      [210, 102, 94],
      [220, -108, 88],
      [0, -160, 98],
    ],
  },
  {
    id: "VTOL-01",
    displayName: "VTOL-01",
    vehicleType: "vtol",
    model: "tilt-rotor",
    color: "#9a7cff",
    altitudeBias: 0,
    mode: "AUTO.TRANSITION",
    agentStatus: "executing",
    intent: "rapid-response",
    points: [
      [-145, 4, 24],
      [-72, 28, 48],
      [12, 12, 72],
      [124, -20, 70],
      [58, -58, 40],
    ],
  },
  {
    id: "UGV-01",
    displayName: "UGV-01",
    vehicleType: "ugv",
    model: "four-wheel-rover",
    color: "#ff7b5f",
    altitudeBias: 0,
    mode: "AUTO.ROUTE",
    agentStatus: "executing",
    intent: "logistics-transfer",
    points: [
      [-132, -34, 1.4],
      [-60, -34, 1.4],
      [8, -34, 1.4],
      [82, -34, 1.4],
      [130, 18, 1.4],
      [72, 36, 1.4],
      [-20, 36, 1.4],
      [-132, -34, 1.4],
    ],
  },
]);

function interpolateRoute(points, progress) {
  const wrappedProgress = ((progress % 1) + 1) % 1;
  const segmentProgress = wrappedProgress * points.length;
  const startIndex = Math.floor(segmentProgress) % points.length;
  const endIndex = (startIndex + 1) % points.length;
  const amount = segmentProgress - Math.floor(segmentProgress);
  const start = points[startIndex];
  const end = points[endIndex];
  const position = start.map(
    (value, index) => value + (end[index] - value) * amount,
  );
  const eastDelta = end[0] - start[0];
  const northDelta = end[1] - start[1];
  const yawDeg = (Math.atan2(eastDelta, northDelta) * 180) / Math.PI;
  const segmentSeconds = DEMO_DURATION_SECONDS / points.length;
  const groundSpeedMps =
    Math.hypot(eastDelta, northDelta) / Math.max(1, segmentSeconds);
  return { position, yawDeg, groundSpeedMps };
}

export class DemoVehicleFeed {
  constructor() {
    this.durationSeconds = DEMO_DURATION_SECONDS;
  }

  snapshotAt(elapsedSeconds) {
    const progress =
      ((elapsedSeconds % this.durationSeconds) + this.durationSeconds) %
      this.durationSeconds;
    return {
      version: "1.0",
      timestamp_ms: Date.now(),
      full_state: true,
      source: {
        id: "local-demo",
        kind: "demo",
        label: "LOCAL DEMO",
      },
      frame: {
        type: "ENU",
      },
      vehicles: DEMO_VEHICLES.map((definition, index) => {
        const route = interpolateRoute(
          definition.points,
          progress / this.durationSeconds + index * 0.07,
        );
        return {
          id: definition.id,
          display_name: definition.displayName,
          vehicle_type: definition.vehicleType,
          model: definition.model,
          color: definition.color,
          connected: true,
          pose: {
            frame: "ENU",
            position_m: {
              x: route.position[0],
              y: route.position[1],
              z: route.position[2] + definition.altitudeBias,
            },
            attitude_deg: {
              roll: 0,
              pitch: 0,
              yaw: route.yawDeg,
            },
          },
          velocity_mps: {
            east: 0,
            north: 0,
            up: 0,
          },
          telemetry: {
            armed: definition.vehicleType !== "ugv",
            mode: definition.mode,
            battery_percent: Math.max(
              34,
              94 - Math.floor(progress / 4) - index * 5,
            ),
            link_quality_percent: 96 - index * 3,
            ground_speed_mps: route.groundSpeedMps,
          },
          agent: {
            id: `agent-${definition.id.toLowerCase()}`,
            status: definition.agentStatus,
            intent: definition.intent,
          },
        };
      }),
    };
  }
}

