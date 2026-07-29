import {
  Cartesian3,
  Cartographic,
  Cesium3DTileset,
  ClockRange,
  Color,
  EllipsoidTerrainProvider,
  GridImageryProvider,
  HeadingPitchRange,
  JulianDate,
  Math as CesiumMath,
  Matrix4,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Transforms,
  Viewer,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "./styles.css";
import { createCampusScene } from "./campus-scene.js";
import { DemoVehicleFeed } from "./demo-vehicle-feed.js";
import {
  VEHICLE_CONTRACT_VERSION,
  normalizeVehicleSnapshot,
} from "./vehicle-contract.js";
import { VehicleLayer } from "./vehicle-layer.js";

const SCENE_ANCHOR = Object.freeze({
  longitude: 116.3913,
  latitude: 39.9075,
  altitude: 0,
});

const sceneDefinitions = Object.freeze({
  campus: {
    label: "任务园区",
    kind: "campus",
    showVehicles: true,
    range: 520,
  },
  "1.1": {
    label: "3D Tiles 1.1",
    kind: "tileset",
    url: "./tiles/1.1/MetadataGranularities/tileset.json",
    anchorToMission: true,
    showVehicles: true,
    range: 200,
  },
  "1.0": {
    label: "3D Tiles 1.0",
    kind: "tileset",
    url: "./tiles/1.0/TilesetWithDiscreteLOD/tileset.json",
    anchorToMission: false,
    showVehicles: false,
    range: 2800,
  },
});

const elements = {
  status: document.querySelector("#scene-status"),
  sourceStatus: document.querySelector("#source-status"),
  error: document.querySelector("#scene-error"),
  playButton: document.querySelector("#play-button"),
  followButton: document.querySelector("#follow-button"),
  progress: document.querySelector("#timeline-progress"),
  missionTime: document.querySelector("#mission-time"),
  sourceKind: document.querySelector("#source-kind"),
  vehicleSummary: document.querySelector("#vehicle-summary"),
  vehicleSelect: document.querySelector("#vehicle-select"),
  selectedId: document.querySelector("#selected-vehicle-id"),
  selectedType: document.querySelector("#selected-vehicle-type"),
  selectedMode: document.querySelector("#selected-vehicle-mode"),
  telemetryLat: document.querySelector("#telemetry-lat"),
  telemetryLon: document.querySelector("#telemetry-lon"),
  telemetryAlt: document.querySelector("#telemetry-alt"),
  telemetrySpeed: document.querySelector("#telemetry-speed"),
  telemetryBattery: document.querySelector("#telemetry-battery"),
  telemetrySource: document.querySelector("#telemetry-source"),
  telemetryAgent: document.querySelector("#telemetry-agent"),
};

const viewer = new Viewer("cesium-container", {
  animation: false,
  baseLayer: false,
  baseLayerPicker: false,
  fullscreenButton: false,
  geocoder: false,
  homeButton: false,
  infoBox: false,
  navigationHelpButton: false,
  sceneModePicker: false,
  selectionIndicator: false,
  terrainProvider: new EllipsoidTerrainProvider(),
  timeline: false,
});

viewer.imageryLayers.addImageryProvider(
  new GridImageryProvider({
    cells: 20,
    color: Color.fromCssColorString("#2a6974").withAlpha(0.3),
    glowColor: Color.fromCssColorString("#071015").withAlpha(0.16),
    backgroundColor: Color.fromCssColorString("#0a1b20"),
  }),
);
viewer.scene.backgroundColor = Color.fromCssColorString("#050a0d");
viewer.scene.globe.baseColor = Color.fromCssColorString("#0a1b20");
viewer.scene.globe.showGroundAtmosphere = false;
viewer.scene.skyAtmosphere.show = false;
viewer.scene.fog.enabled = false;
viewer.scene.requestRenderMode = false;
viewer.scene.screenSpaceCameraController.enableCollisionDetection = false;

const sceneOrigin = Cartesian3.fromDegrees(
  SCENE_ANCHOR.longitude,
  SCENE_ANCHOR.latitude,
  SCENE_ANCHOR.altitude,
);
const missionFrame = Transforms.eastNorthUpToFixedFrame(sceneOrigin);

function enuToWorld(eastM, northM, upM) {
  return Matrix4.multiplyByPoint(
    missionFrame,
    new Cartesian3(eastM, northM, upM),
    new Cartesian3(),
  );
}

function positionToWorld(position) {
  if (position.frame === "WGS84") {
    return Cartesian3.fromDegrees(
      position.longitudeDeg,
      position.latitudeDeg,
      position.altitudeM,
    );
  }
  return enuToWorld(position.eastM, position.northM, position.upM);
}

const campusScene = createCampusScene(viewer, (position) =>
  enuToWorld(position[0], position[1], position[2]),
);
const vehicleLayer = new VehicleLayer(viewer, positionToWorld);
const demoFeed = new DemoVehicleFeed();

const startTime = JulianDate.now();
const stopTime = JulianDate.addSeconds(
  startTime,
  demoFeed.durationSeconds,
  new JulianDate(),
);
viewer.clock.startTime = startTime.clone();
viewer.clock.stopTime = stopTime.clone();
viewer.clock.currentTime = startTime.clone();
viewer.clock.clockRange = ClockRange.LOOP_STOP;
viewer.clock.multiplier = 1;
viewer.clock.shouldAnimate = true;

let activeTileset;
let activeSceneId = "campus";
let dataMode = "demo";
let followEnabled = false;
let lastDemoUpdateSeconds = -1;
let latestSnapshot;

function formatMissionTime(seconds) {
  const safeSeconds = Math.max(0, Math.min(demoFeed.durationSeconds, seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = Math.floor(safeSeconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}

function sourceClass(kind) {
  return ["demo", "simulation", "physical", "hybrid"].includes(kind)
    ? kind
    : "unknown";
}

function typeLabel(vehicleType) {
  return (
    {
      multirotor: "多旋翼",
      fixed_wing: "固定翼",
      vtol: "垂直起降固定翼",
      ugv: "无人车",
      usv: "无人艇",
      uuv: "水下航行器",
      unknown: "未知平台",
    }[vehicleType] || vehicleType
  );
}

function refreshVehicleControls() {
  const records = vehicleLayer.getRecords();
  const selectedId = vehicleLayer.selectedVehicleId;
  elements.vehicleSelect.replaceChildren();
  for (const record of records) {
    const option = document.createElement("option");
    option.value = record.vehicle.id;
    option.textContent = `${record.vehicle.displayName} · ${typeLabel(record.vehicle.vehicleType)}`;
    option.selected = record.vehicle.id === selectedId;
    elements.vehicleSelect.append(option);
  }
  elements.vehicleSelect.disabled = records.length === 0;

  const typeCount = new Set(records.map((record) => record.vehicle.vehicleType))
    .size;
  elements.vehicleSummary.textContent = `${records.length} 个节点 · ${typeCount} 种平台`;
}

function refreshSelectedTelemetry() {
  const record = vehicleLayer.getSelectedRecord();
  if (!record) {
    elements.selectedId.textContent = "NO VEHICLE";
    elements.selectedType.textContent = "--";
    elements.selectedMode.textContent = "OFFLINE";
    for (const element of [
      elements.telemetryLat,
      elements.telemetryLon,
      elements.telemetryAlt,
      elements.telemetrySpeed,
      elements.telemetryBattery,
      elements.telemetrySource,
      elements.telemetryAgent,
    ]) {
      element.textContent = "--";
    }
    return;
  }

  const { vehicle, worldPosition } = record;
  const cartographic = Cartographic.fromCartesian(worldPosition);
  elements.selectedId.textContent = vehicle.displayName;
  elements.selectedType.textContent = typeLabel(vehicle.vehicleType);
  elements.selectedMode.textContent = vehicle.telemetry.mode;
  elements.telemetryLat.textContent =
    `${CesiumMath.toDegrees(cartographic.latitude).toFixed(6)}°`;
  elements.telemetryLon.textContent =
    `${CesiumMath.toDegrees(cartographic.longitude).toFixed(6)}°`;
  elements.telemetryAlt.textContent = `${cartographic.height.toFixed(1)} m`;
  elements.telemetrySpeed.textContent =
    `${vehicle.velocity.groundSpeedMps.toFixed(1)} m/s`;
  elements.telemetryBattery.textContent =
    vehicle.telemetry.batteryPercent >= 0
      ? `${vehicle.telemetry.batteryPercent.toFixed(0)}%`
      : "--";
  elements.telemetrySource.textContent = vehicle.source.label;
  elements.telemetryAgent.textContent = vehicle.agent.id
    ? `${vehicle.agent.status} · ${vehicle.agent.id}`
    : "unassigned";
}

function setSelectedVehicle(vehicleId) {
  vehicleLayer.setSelected(vehicleId);
  elements.vehicleSelect.value = vehicleLayer.selectedVehicleId;
  refreshSelectedTelemetry();
  if (followEnabled) {
    viewer.trackedEntity =
      vehicleLayer.getSelectedRecord()?.entity || undefined;
  }
}

function updateSourceUi(snapshot) {
  const kind = sourceClass(snapshot.source.kind);
  elements.sourceKind.textContent = snapshot.source.label;
  elements.sourceKind.dataset.kind = kind;
  elements.sourceStatus.textContent =
    kind === "demo" ? "LOCAL DEMO" : `${kind.toUpperCase()} LIVE`;
}

function applyNormalizedSnapshot(snapshot, mode) {
  latestSnapshot = snapshot;
  dataMode = mode;
  vehicleLayer.applySnapshot(snapshot);
  updateSourceUi(snapshot);
  refreshVehicleControls();
  refreshSelectedTelemetry();

  const live = mode === "external";
  elements.playButton.disabled = live;
  elements.playButton.textContent = live
    ? "实时"
    : viewer.clock.shouldAnimate
      ? "暂停"
      : "播放";
  elements.progress.classList.toggle("live", live);
  if (live) {
    elements.progress.style.width = "100%";
    elements.missionTime.value = `${new Date(snapshot.timestampMs).toLocaleTimeString()} / LIVE`;
  }
}

function applyExternalSnapshot(rawSnapshot) {
  const snapshot = normalizeVehicleSnapshot(rawSnapshot);
  viewer.clock.shouldAnimate = false;
  applyNormalizedSnapshot(snapshot, "external");
  return {
    accepted: snapshot.vehicles.length,
    timestampMs: snapshot.timestampMs,
  };
}

function useDemo() {
  dataMode = "demo";
  viewer.clock.currentTime = startTime.clone();
  viewer.clock.shouldAnimate = true;
  lastDemoUpdateSeconds = -1;
  updateDemo(viewer.clock);
}

function updateDemo(clock) {
  if (dataMode !== "demo") {
    return;
  }
  const elapsed = JulianDate.secondsDifference(clock.currentTime, startTime);
  if (
    lastDemoUpdateSeconds >= 0 &&
    Math.abs(elapsed - lastDemoUpdateSeconds) < 0.12
  ) {
    return;
  }
  lastDemoUpdateSeconds = elapsed;
  const snapshot = normalizeVehicleSnapshot(demoFeed.snapshotAt(elapsed));
  applyNormalizedSnapshot(snapshot, "demo");
  const progress = Math.max(
    0,
    Math.min(1, elapsed / demoFeed.durationSeconds),
  );
  elements.progress.style.width = `${progress * 100}%`;
  elements.missionTime.value =
    `${formatMissionTime(elapsed)} / ${formatMissionTime(demoFeed.durationSeconds)}`;
}

async function loadScene(sceneId) {
  const definition = sceneDefinitions[sceneId];
  elements.status.textContent = `正在加载 ${definition.label}`;
  elements.error.hidden = true;

  if (activeTileset) {
    viewer.scene.primitives.remove(activeTileset);
    activeTileset = undefined;
  }
  campusScene.setVisible(definition.kind === "campus");
  vehicleLayer.setVisible(definition.showVehicles);

  if (definition.kind === "campus") {
    activeSceneId = sceneId;
    elements.status.textContent = `${definition.label} · READY`;
    await focusScene();
    return;
  }

  try {
    const tileset = await Cesium3DTileset.fromUrl(definition.url, {
      maximumScreenSpaceError: 12,
    });
    viewer.scene.primitives.add(tileset);
    if (definition.anchorToMission) {
      tileset.modelMatrix = Transforms.eastNorthUpToFixedFrame(sceneOrigin);
    }
    activeTileset = tileset;
    activeSceneId = sceneId;
    elements.status.textContent = `${definition.label} · READY`;
    await focusScene();
  } catch (error) {
    elements.status.textContent = `${definition.label} · ERROR`;
    elements.error.textContent = `场景加载失败：${error.message}`;
    elements.error.hidden = false;
  }
}

async function focusScene() {
  followEnabled = false;
  elements.followButton.classList.remove("active");
  viewer.trackedEntity = undefined;
  const definition = sceneDefinitions[activeSceneId];

  if (definition.kind === "campus" || definition.anchorToMission) {
    viewer.camera.lookAt(
      sceneOrigin,
      new HeadingPitchRange(
        CesiumMath.toRadians(-28),
        CesiumMath.toRadians(-48),
        definition.range,
      ),
    );
    return;
  }

  if (activeTileset) {
    await viewer.zoomTo(
      activeTileset,
      new HeadingPitchRange(
        CesiumMath.toRadians(-28),
        CesiumMath.toRadians(-34),
        definition.range,
      ),
    );
  }
}

document
  .querySelector("#scene-select")
  .addEventListener("change", (event) => loadScene(event.target.value));

document.querySelector("#home-button").addEventListener("click", focusScene);

elements.followButton.addEventListener("click", () => {
  followEnabled = !followEnabled;
  elements.followButton.classList.toggle("active", followEnabled);
  viewer.trackedEntity = followEnabled
    ? vehicleLayer.getSelectedRecord()?.entity
    : undefined;
});

document.querySelector("#demo-button").addEventListener("click", useDemo);

document.querySelector("#route-toggle").addEventListener("change", (event) => {
  vehicleLayer.setRoutesVisible(event.target.checked);
});

document.querySelector("#label-toggle").addEventListener("change", (event) => {
  vehicleLayer.setLabelsVisible(event.target.checked);
});

elements.vehicleSelect.addEventListener("change", (event) => {
  setSelectedVehicle(event.target.value);
});

elements.playButton.addEventListener("click", () => {
  if (dataMode !== "demo") {
    return;
  }
  viewer.clock.shouldAnimate = !viewer.clock.shouldAnimate;
  elements.playButton.textContent = viewer.clock.shouldAnimate ? "暂停" : "播放";
  elements.playButton.title = viewer.clock.shouldAnimate
    ? "暂停本地演示"
    : "播放本地演示";
});

document.querySelector("#speed-select").addEventListener("change", (event) => {
  viewer.clock.multiplier = Number(event.target.value);
});

const pickHandler = new ScreenSpaceEventHandler(viewer.scene.canvas);
pickHandler.setInputAction((movement) => {
  const picked = viewer.scene.pick(movement.position);
  const vehicleId = vehicleLayer.vehicleIdFromPickedEntity(picked?.id);
  if (vehicleId) {
    setSelectedVehicle(vehicleId);
  }
}, ScreenSpaceEventType.LEFT_CLICK);

viewer.clock.onTick.addEventListener((clock) => {
  updateDemo(clock);
  refreshSelectedTelemetry();
});

const bridge = Object.freeze({
  contractVersion: VEHICLE_CONTRACT_VERSION,
  applyVehicleSnapshot: applyExternalSnapshot,
  useDemo,
  selectVehicle: setSelectedVehicle,
  focusScene,
  getState() {
    return {
      sceneId: activeSceneId,
      dataMode,
      source: latestSnapshot?.source || null,
      vehicleCount: vehicleLayer.getRecords().length,
      selectedVehicleId: vehicleLayer.selectedVehicleId,
    };
  },
});
window.SwarmSimulationBridge = bridge;

const allowedMessageOrigins = new Set([
  window.location.origin,
  "http://127.0.0.1:5178",
  "http://localhost:5178",
  "http://127.0.0.1:5173",
  "http://localhost:5173",
]);
window.addEventListener("message", (event) => {
  if (!allowedMessageOrigins.has(event.origin)) {
    return;
  }
  if (event.data?.type === "uav-swarm/vehicle-snapshot") {
    applyExternalSnapshot(event.data.payload);
  }
  if (event.data?.type === "uav-swarm/use-demo") {
    useDemo();
  }
});

if (window.parent !== window) {
  const parentOrigin = document.referrer
    ? new URL(document.referrer).origin
    : "*";
  window.parent.postMessage(
    {
      type: "uav-swarm/simulation-ready",
      payload: {
        contractVersion: VEHICLE_CONTRACT_VERSION,
      },
    },
    parentOrigin,
  );
}

updateDemo(viewer.clock);
loadScene(activeSceneId);

