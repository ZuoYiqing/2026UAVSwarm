import {
  Cartesian3,
  Cartographic,
  Cesium3DTileset,
  ClockRange,
  Color,
  DirectionalLight,
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
import { createCityScene } from "./city-scene.js";
import { CITY_VIEWS } from "./city-layout.js";
import {
  createIcons,
  Building2,
  Map,
  Layers,
  Mountain,
  Route,
  Crosshair,
  Home,
  Plus,
  Minus,
  Compass,
  Radio,
} from "lucide";
import { DemoVehicleFeed } from "./demo-vehicle-feed.js";
import { VEHICLE_CONTRACT_VERSION } from "./vehicle-contract.js";
import { VehicleLayer } from "./vehicle-layer.js";
import {
  RuntimeVehicleSnapshotPoller,
  VehicleSnapshotState,
  createRuntimeSnapshotFetcher,
} from "./vehicle-snapshot-state.js";

const SCENE_ANCHOR = Object.freeze({
  longitude: 116.3913,
  latitude: 39.9075,
  altitude: 0,
});

const sceneDefinitions = Object.freeze({
  city: {
    label: "青岚市",
    kind: "city",
    showVehicles: true,
    range: CITY_VIEWS.city.range,
  },
  campus: {
    label: "任务园区",
    kind: "campus",
    showVehicles: true,
    range: 520,
  },
  1.1: {
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
  statusDot: document.querySelector("#status-dot"),
  sourceStatus: document.querySelector("#source-status"),
  error: document.querySelector("#scene-error"),
  playButton: document.querySelector("#play-button"),
  followButton: document.querySelector("#follow-button"),
  progress: document.querySelector("#timeline-progress"),
  missionTime: document.querySelector("#mission-time"),
  sourceKind: document.querySelector("#source-kind"),
  sourceConnection: document.querySelector("#source-connection"),
  sourceUpdated: document.querySelector("#source-updated"),
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
  telemetryPanel: document.querySelector(".telemetry-panel"),
  liveButton: document.querySelector("#live-button"),
  demoButton: document.querySelector("#demo-button"),
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

viewer.scene.backgroundColor = Color.fromCssColorString("#c1cbd0");
viewer.scene.globe.baseColor = Color.fromCssColorString("#9cab91");
viewer.imageryLayers.addImageryProvider(
  new GridImageryProvider({
    color: Color.TRANSPARENT,
    glowColor: Color.TRANSPARENT,
    backgroundColor: Color.fromCssColorString("#9cab91"),
  }),
);
viewer.scene.skyBox.show = false;
viewer.scene.globe.showGroundAtmosphere = false;
viewer.scene.skyAtmosphere.show = false;
viewer.scene.fog.enabled = false;
viewer.scene.requestRenderMode = false;
viewer.scene.screenSpaceCameraController.enableCollisionDetection = true;
viewer.scene.screenSpaceCameraController.minimumZoomDistance = 35;
viewer.scene.screenSpaceCameraController.maximumZoomDistance = 16000;

const sceneOrigin = Cartesian3.fromDegrees(
  SCENE_ANCHOR.longitude,
  SCENE_ANCHOR.latitude,
  SCENE_ANCHOR.altitude,
);
const missionFrame = Transforms.eastNorthUpToFixedFrame(sceneOrigin);
viewer.scene.light = new DirectionalLight({
  direction: Cartesian3.normalize(
    Matrix4.multiplyByPointAsVector(
      missionFrame,
      new Cartesian3(0.5, 0.35, -1),
      new Cartesian3(),
    ),
    new Cartesian3(),
  ),
  intensity: 1.1,
});
viewer.shadowMap.enabled = false;

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
const cityScene = createCityScene(viewer, missionFrame, (p) =>
  enuToWorld(...p),
);
document.querySelector("#city-statistics").textContent =
  `${cityScene.stats.buildings} 栋建筑 · ${cityScene.stats.trees.toLocaleString()} 株乔木 · 10.08 km²`;
const vehicleLayer = new VehicleLayer(viewer, positionToWorld);
const demoFeed = new DemoVehicleFeed();
const embedded = window.parent !== window;
const queryParameters = new URLSearchParams(window.location.search);
const runtimeApiBaseUrl =
  queryParameters.get("runtimeApiBaseUrl") ||
  import.meta.env.VITE_RUNTIME_API_BASE_URL ||
  "/api";
const snapshotState = new VehicleSnapshotState();

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
viewer.clock.shouldAnimate = false;

let activeTileset;
let activeSceneId = "city";
let activeViewId = "city";
let sceneLoadGeneration = 0;
let followEnabled = false;
let lastDemoUpdateSeconds = -1;
let latestSnapshot;
let lastRenderedStale = null;

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
  const staleCount = records.filter((record) =>
    vehicleLayer.isRecordStale(record),
  ).length;
  elements.vehicleSummary.textContent = staleCount
    ? `${records.length} 个节点 · ${typeCount} 种平台 · ${staleCount} STALE`
    : `${records.length} 个节点 · ${typeCount} 种平台`;
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
    elements.telemetryPanel.dataset.state = "offline";
    return;
  }

  const { vehicle, worldPosition } = record;
  const stale = vehicleLayer.isRecordStale(record);
  const cartographic = Cartographic.fromCartesian(worldPosition);
  elements.selectedId.textContent = vehicle.displayName;
  elements.selectedType.textContent = typeLabel(vehicle.vehicleType);
  elements.selectedMode.textContent = stale
    ? `${vehicle.telemetry.mode} · STALE`
    : vehicle.telemetry.mode;
  elements.telemetryPanel.dataset.state = stale ? "stale" : "fresh";
  elements.telemetryLat.textContent = `${CesiumMath.toDegrees(cartographic.latitude).toFixed(6)}°`;
  elements.telemetryLon.textContent = `${CesiumMath.toDegrees(cartographic.longitude).toFixed(6)}°`;
  elements.telemetryAlt.textContent = `${cartographic.height.toFixed(1)} m`;
  elements.telemetrySpeed.textContent = `${vehicle.velocity.groundSpeedMps.toFixed(1)} m/s`;
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

function connectionLabel(status) {
  return (
    {
      demo: "本地演示",
      connecting: "正在连接 Runtime",
      waiting: "等待主控制台",
      connected: "数据已连接",
      reconnecting: "连接波动，正在重试",
      stale: "数据已过期，位置已冻结",
      disconnected: "数据源断开",
    }[status.connection] || status.connection
  );
}

function formatLastUpdate(status) {
  if (status.lastAcceptedAtMs === null) {
    return "最后更新：--";
  }
  const time = new Date(status.lastAcceptedAtMs).toLocaleTimeString("zh-CN", {
    hour12: false,
  });
  const ageSeconds = Math.max(0, (status.ageMs || 0) / 1000);
  return `最后更新：${time} · ${ageSeconds.toFixed(1)}s 前`;
}

function updateSourceUi(snapshot) {
  const kind = sourceClass(snapshot.source.kind);
  elements.sourceKind.textContent = snapshot.source.label;
  elements.sourceKind.dataset.kind = kind;
}

function refreshSourceStatus(nowMs = Date.now()) {
  const status = snapshotState.statusAt(nowMs);
  const sourceLabel =
    latestSnapshot?.source.label ||
    (status.transport === "runtime" ? "RUNTIME API" : "MAIN CONSOLE");

  if (!latestSnapshot && status.mode === "live") {
    elements.sourceKind.textContent = sourceLabel;
    elements.sourceKind.dataset.kind = "unknown";
  }
  elements.sourceConnection.textContent = connectionLabel(status);
  elements.sourceConnection.dataset.state = status.connection;
  elements.sourceUpdated.textContent = formatLastUpdate(status);
  elements.statusDot.dataset.state = status.connection;
  elements.sourceStatus.textContent =
    status.mode === "demo"
      ? "LOCAL DEMO"
      : status.stale
        ? "LIVE · STALE"
        : status.connection === "connected"
          ? "LIVE"
          : status.connection.toUpperCase();

  elements.liveButton.classList.toggle("active", status.mode === "live");
  elements.demoButton.classList.toggle("active", status.mode === "demo");
  elements.playButton.disabled = status.mode === "live";
  elements.playButton.textContent =
    status.mode === "live"
      ? "实时"
      : viewer.clock.shouldAnimate
        ? "暂停"
        : "播放";
  elements.progress.classList.toggle(
    "live",
    status.mode === "live" && !status.stale,
  );
  elements.progress.classList.toggle("stale", status.stale);

  if (status.mode === "live") {
    elements.progress.style.width =
      status.lastAcceptedAtMs === null ? "0%" : "100%";
    elements.missionTime.value = status.stale
      ? `STALE · ${(status.ageMs / 1000).toFixed(1)}s`
      : status.connection === "connected"
        ? `${new Date(latestSnapshot.timestampMs).toLocaleTimeString("zh-CN", { hour12: false })} / LIVE`
        : "-- / LIVE";
  }

  if (lastRenderedStale !== status.stale) {
    lastRenderedStale = status.stale;
    vehicleLayer.setDataStale(status.stale);
    refreshVehicleControls();
    refreshSelectedTelemetry();
  }
}

function applyAcceptedSnapshot(snapshot) {
  latestSnapshot = snapshot;
  vehicleLayer.applySnapshot(snapshot);
  updateSourceUi(snapshot);
  refreshVehicleControls();
  refreshSelectedTelemetry();
}

function handleRawSnapshot(rawSnapshot, transport) {
  let result;
  try {
    result = snapshotState.ingest(rawSnapshot, { transport });
  } catch (error) {
    snapshotState.markTransportError(error, { transport });
    refreshSourceStatus();
    throw error;
  }

  if (transport === "parent" || transport === "bridge") {
    runtimePoller.stop();
  }
  if (result.accepted) {
    viewer.clock.shouldAnimate = snapshotState.mode === "demo";
    applyAcceptedSnapshot(result.snapshot);
  }
  refreshSourceStatus();
  return result;
}

function applyExternalSnapshot(rawSnapshot, transport = "bridge") {
  const result = handleRawSnapshot(rawSnapshot, transport);
  return {
    accepted: result.accepted,
    reason: result.reason,
    vehicleCount: result.snapshot.vehicles.length,
    timestampMs: result.snapshot.timestampMs,
  };
}

function clearDisplayedFleet(label) {
  latestSnapshot = undefined;
  vehicleLayer.applySnapshot(snapshotState.emptySnapshot(label));
  refreshVehicleControls();
  refreshSelectedTelemetry();
}

function useLive() {
  runtimePoller.stop();
  const transport = embedded ? "parent" : "runtime";
  snapshotState.activateLive(transport);
  viewer.clock.shouldAnimate = false;
  lastDemoUpdateSeconds = -1;
  lastRenderedStale = null;
  clearDisplayedFleet(embedded ? "MAIN CONSOLE" : "RUNTIME API");
  if (!embedded) {
    runtimePoller.start();
  }
  refreshSourceStatus();
}

function useDemo() {
  runtimePoller.stop();
  snapshotState.activateDemo();
  viewer.clock.currentTime = startTime.clone();
  viewer.clock.shouldAnimate = true;
  lastDemoUpdateSeconds = -1;
  lastRenderedStale = null;
  clearDisplayedFleet("LOCAL DEMO");
  updateDemo(viewer.clock);
}

function updateDemo(clock) {
  if (snapshotState.mode !== "demo") {
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
  const result = handleRawSnapshot(demoFeed.snapshotAt(elapsed), "demo");
  if (!result.accepted) {
    return;
  }
  const progress = Math.max(0, Math.min(1, elapsed / demoFeed.durationSeconds));
  elements.progress.style.width = `${progress * 100}%`;
  elements.missionTime.value = `${formatMissionTime(elapsed)} / ${formatMissionTime(demoFeed.durationSeconds)}`;
}

const runtimePoller = new RuntimeVehicleSnapshotPoller({
  fetchSnapshot: createRuntimeSnapshotFetcher({
    apiBaseUrl: runtimeApiBaseUrl,
  }),
  onSnapshot: async (rawSnapshot) => {
    handleRawSnapshot(rawSnapshot, "runtime");
  },
  onError: async (error) => {
    snapshotState.markTransportError(error, { transport: "runtime" });
    refreshSourceStatus();
  },
});

async function loadScene(sceneId) {
  const definition = sceneDefinitions[sceneId];
  if (!definition) return;
  const generation = ++sceneLoadGeneration;
  elements.status.textContent = `正在加载 ${definition.label}`;
  elements.error.hidden = true;
  document.querySelector("#scene-title").textContent = definition.label;
  document.querySelector("#city-statistics").hidden =
    definition.kind !== "city";
  document.querySelector("#map-location").textContent = definition.label;

  if (activeTileset) {
    viewer.scene.primitives.remove(activeTileset);
    activeTileset = undefined;
  }
  campusScene.setVisible(definition.kind === "campus");
  cityScene.setVisible(definition.kind === "city");
  document.querySelector("#city-tools").hidden = definition.kind !== "city";
  vehicleLayer.setVisible(definition.showVehicles);

  if (["campus", "city"].includes(definition.kind)) {
    activeSceneId = sceneId;
    activeViewId = definition.kind === "city" ? "city" : "campus";
    elements.status.textContent = `${definition.label} · READY`;
    await focusScene();
    return;
  }

  try {
    const tileset = await Cesium3DTileset.fromUrl(definition.url, {
      maximumScreenSpaceError: 12,
    });
    if (generation !== sceneLoadGeneration) {
      tileset.destroy();
      return;
    }
    viewer.scene.primitives.add(tileset);
    if (definition.anchorToMission) {
      tileset.modelMatrix = Transforms.eastNorthUpToFixedFrame(sceneOrigin);
    }
    activeTileset = tileset;
    activeSceneId = sceneId;
    elements.status.textContent = `${definition.label} · READY`;
    await focusScene();
  } catch (error) {
    if (generation !== sceneLoadGeneration) return;
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

  if (definition.kind === "city") {
    focusCityView(activeViewId);
    return;
  }

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

function focusCityView(id) {
  const view = CITY_VIEWS[id];
  if (!view || activeSceneId !== "city") return;
  activeViewId = id;
  followEnabled = false;
  elements.followButton.classList.remove("active");
  viewer.trackedEntity = undefined;
  viewer.camera.lookAt(
    enuToWorld(...view.target),
    new HeadingPitchRange(
      CesiumMath.toRadians(view.heading),
      CesiumMath.toRadians(view.pitch),
      view.range,
    ),
  );
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === id);
    button.setAttribute("aria-pressed", String(button.dataset.view === id));
  });
  document.querySelector("#map-location").textContent = view.label;
  viewer.scene.requestRender();
}

createIcons({
  icons: {
    Building2,
    Map,
    Layers,
    Mountain,
    Route,
    Crosshair,
    Home,
    Plus,
    Minus,
    Compass,
    Radio,
  },
});
document
  .querySelectorAll("[data-view]")
  .forEach((button) =>
    button.addEventListener("click", () => focusCityView(button.dataset.view)),
  );
document
  .querySelectorAll("[data-city-layer]")
  .forEach((input) =>
    input.addEventListener("change", () =>
      cityScene.setLayer(input.dataset.cityLayer, input.checked),
    ),
  );
document
  .querySelector("#shadows-toggle")
  .addEventListener("change", (event) => {
    viewer.shadowMap.enabled = event.target.checked;
    viewer.scene.requestRender();
  });
document
  .querySelector("#zoom-in")
  .addEventListener("click", () =>
    viewer.camera.zoomIn(
      Math.max(20, viewer.camera.positionCartographic.height * 0.22),
    ),
  );
document
  .querySelector("#zoom-out")
  .addEventListener("click", () =>
    viewer.camera.zoomOut(
      Math.max(20, viewer.camera.positionCartographic.height * 0.22),
    ),
  );
document.querySelector("#north-button").addEventListener("click", () => {
  followEnabled = false;
  elements.followButton.classList.remove("active");
  viewer.trackedEntity = undefined;
  if (activeSceneId === "city") {
    const view = CITY_VIEWS[activeViewId];
    viewer.camera.lookAt(
      enuToWorld(...view.target),
      new HeadingPitchRange(0, CesiumMath.toRadians(-65), view.range),
    );
  } else {
    viewer.camera.lookAtTransform(Matrix4.IDENTITY);
    viewer.camera.setView({
      orientation: { heading: 0, pitch: CesiumMath.toRadians(-65), roll: 0 },
    });
  }
});
document.querySelectorAll("button[data-panel]").forEach((button) =>
  button.addEventListener("click", () => {
    const shell = document.querySelector(".simulation-shell");
    const key = button.dataset.panel;
    const open = shell.dataset.panel === key;
    shell.dataset.panel = open ? "" : key;
    document
      .querySelectorAll("button[data-panel]")
      .forEach((control) =>
        control.setAttribute(
          "aria-expanded",
          String(!open && control.dataset.panel === key),
        ),
      );
  }),
);

document
  .querySelector("#scene-select")
  .addEventListener("change", (event) => loadScene(event.target.value));

document.querySelector("#home-button").addEventListener("click", () => {
  if (activeSceneId === "city") focusCityView("campus");
  else focusScene();
});

elements.followButton.addEventListener("click", () => {
  followEnabled = !followEnabled;
  elements.followButton.classList.toggle("active", followEnabled);
  viewer.trackedEntity = followEnabled
    ? vehicleLayer.getSelectedRecord()?.entity
    : undefined;
});

elements.liveButton.addEventListener("click", useLive);
elements.demoButton.addEventListener("click", useDemo);

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
  if (snapshotState.mode !== "demo") {
    return;
  }
  viewer.clock.shouldAnimate = !viewer.clock.shouldAnimate;
  elements.playButton.textContent = viewer.clock.shouldAnimate
    ? "暂停"
    : "播放";
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
  useLive,
  useDemo,
  selectVehicle: setSelectedVehicle,
  focusScene,
  getState() {
    return {
      sceneId: activeSceneId,
      dataMode: snapshotState.mode,
      transport: snapshotState.transport,
      connection: snapshotState.statusAt().connection,
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
    try {
      applyExternalSnapshot(event.data.payload, "parent");
    } catch (error) {
      elements.error.textContent = `载具快照无效：${error.message}`;
      elements.error.hidden = false;
    }
  }
  if (event.data?.type === "uav-swarm/use-demo") {
    useDemo();
  }
  if (event.data?.type === "uav-swarm/use-live") {
    useLive();
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
        integration: "parent-snapshot",
      },
    },
    parentOrigin,
  );
}

loadScene(activeSceneId);
window.setInterval(() => refreshSourceStatus(), 250);
window.addEventListener("beforeunload", () => runtimePoller.stop());

if (queryParameters.get("mode") === "demo") {
  useDemo();
} else {
  useLive();
}
