import {
  VEHICLE_CONTRACT_VERSION,
  normalizeVehicleSnapshot,
} from "./vehicle-contract.js";

export const DEFAULT_STALE_AFTER_MS = 3_000;

const TRANSPORT_PRIORITY = Object.freeze({
  demo: 0,
  runtime: 1,
  bridge: 2,
  parent: 2,
});

function transportPriority(transport) {
  return TRANSPORT_PRIORITY[transport] ?? -1;
}

function hasFreshPose(vehicle) {
  return vehicle.connected && !vehicle.telemetry.stale;
}

function preserveTrustedPose(vehicle, previousVehicle) {
  if (!previousVehicle || hasFreshPose(vehicle)) {
    return vehicle;
  }
  return {
    ...vehicle,
    position: previousVehicle.position,
    attitude: previousVehicle.attitude,
  };
}

export class VehicleSnapshotState {
  constructor({ staleAfterMs = DEFAULT_STALE_AFTER_MS, now = Date.now } = {}) {
    this.staleAfterMs = staleAfterMs;
    this.now = now;
    this.mode = "live";
    this.transport = "runtime";
    this.activatedAtMs = this.now();
    this.lastAcceptedAtMs = null;
    this.lastContactAtMs = null;
    this.lastTimestampMs = null;
    this.lastSnapshot = null;
    this.lastError = "";
    this.vehicles = new Map();
  }

  activateDemo(atMs = this.now()) {
    this.#reset("demo", "demo", atMs);
  }

  activateLive(transport = "runtime", atMs = this.now()) {
    if (!["runtime", "parent", "bridge"].includes(transport)) {
      throw new Error(`Unsupported live transport: ${transport}`);
    }
    this.#reset("live", transport, atMs);
  }

  #reset(mode, transport, atMs) {
    this.mode = mode;
    this.transport = transport;
    this.activatedAtMs = atMs;
    this.lastAcceptedAtMs = null;
    this.lastContactAtMs = null;
    this.lastTimestampMs = null;
    this.lastSnapshot = null;
    this.lastError = "";
    this.vehicles.clear();
  }

  ingest(rawSnapshot, { transport = "runtime", receivedAtMs = this.now() } = {}) {
    const snapshot = normalizeVehicleSnapshot(rawSnapshot);
    const incomingPriority = transportPriority(transport);
    if (incomingPriority < 0) {
      throw new Error(`Unsupported snapshot transport: ${transport}`);
    }

    if (transport === "demo" && this.mode !== "demo") {
      return { accepted: false, reason: "demo-disabled", snapshot };
    }

    if (transport !== "demo" && this.mode === "demo") {
      this.activateLive(transport, receivedAtMs);
    } else if (
      this.mode === "live" &&
      incomingPriority < transportPriority(this.transport)
    ) {
      return { accepted: false, reason: "transport-suppressed", snapshot };
    } else if (
      this.mode === "live" &&
      incomingPriority > transportPriority(this.transport)
    ) {
      this.transport = transport;
    }

    this.lastContactAtMs = receivedAtMs;
    this.lastError = "";

    if (this.lastTimestampMs !== null) {
      if (snapshot.timestampMs < this.lastTimestampMs) {
        return { accepted: false, reason: "out-of-order", snapshot };
      }
      if (snapshot.timestampMs === this.lastTimestampMs) {
        return { accepted: false, reason: "duplicate", snapshot };
      }
    }

    const previousVehicles = new Map(this.vehicles);
    const previousIds = new Set(previousVehicles.keys());
    const added = [];
    const updated = [];
    const removed = [];
    const appliedVehicles = snapshot.vehicles.map((vehicle) =>
      preserveTrustedPose(vehicle, previousVehicles.get(vehicle.id)),
    );

    if (snapshot.fullState) {
      this.vehicles.clear();
    }
    for (const vehicle of appliedVehicles) {
      if (previousIds.has(vehicle.id)) {
        updated.push(vehicle.id);
      } else {
        added.push(vehicle.id);
      }
      this.vehicles.set(vehicle.id, vehicle);
      previousIds.delete(vehicle.id);
    }
    if (snapshot.fullState) {
      removed.push(...previousIds);
    }

    const appliedSnapshot = { ...snapshot, vehicles: appliedVehicles };
    this.lastTimestampMs = appliedSnapshot.timestampMs;
    this.lastAcceptedAtMs = receivedAtMs;
    this.lastSnapshot = appliedSnapshot;

    return {
      accepted: true,
      reason: "accepted",
      snapshot: appliedSnapshot,
      diff: { added, updated, removed },
    };
  }

  markTransportError(error, { transport = this.transport } = {}) {
    if (transportPriority(transport) < transportPriority(this.transport)) {
      return false;
    }
    this.lastError = error instanceof Error ? error.message : String(error || "unknown error");
    return true;
  }

  statusAt(nowMs = this.now()) {
    if (this.mode === "demo") {
      return {
        mode: "demo",
        transport: "demo",
        connection: "demo",
        stale: false,
        ageMs: this.lastAcceptedAtMs === null ? null : nowMs - this.lastAcceptedAtMs,
        lastAcceptedAtMs: this.lastAcceptedAtMs,
        lastContactAtMs: this.lastContactAtMs,
        lastError: this.lastError,
      };
    }

    if (this.lastAcceptedAtMs === null) {
      const waiting = this.transport === "parent" || this.transport === "bridge";
      return {
        mode: "live",
        transport: this.transport,
        connection: this.lastError
          ? "disconnected"
          : waiting
            ? "waiting"
            : "connecting",
        stale: false,
        ageMs: null,
        lastAcceptedAtMs: null,
        lastContactAtMs: this.lastContactAtMs,
        lastError: this.lastError,
      };
    }

    const ageMs = Math.max(0, nowMs - this.lastAcceptedAtMs);
    const stale = ageMs > this.staleAfterMs;
    return {
      mode: "live",
      transport: this.transport,
      connection: stale ? "stale" : this.lastError ? "reconnecting" : "connected",
      stale,
      ageMs,
      lastAcceptedAtMs: this.lastAcceptedAtMs,
      lastContactAtMs: this.lastContactAtMs,
      lastError: this.lastError,
    };
  }

  emptySnapshot(sourceLabel = "LIVE") {
    return {
      version: VEHICLE_CONTRACT_VERSION,
      timestampMs: this.now(),
      fullState: true,
      source: { id: "waiting", kind: "unknown", label: sourceLabel },
      frame: { type: "ENU" },
      vehicles: [],
    };
  }

  getVehicle(vehicleId) {
    return this.vehicles.get(vehicleId);
  }
}

export class RuntimeVehicleSnapshotPoller {
  constructor({
    fetchSnapshot,
    onSnapshot,
    onError,
    intervalMs = 200,
    setTimer = (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
    clearTimer = (timerId) => globalThis.clearTimeout(timerId),
  }) {
    this.fetchSnapshot = fetchSnapshot;
    this.onSnapshot = onSnapshot;
    this.onError = onError;
    this.intervalMs = intervalMs;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.running = false;
    this.inFlight = false;
    this.timerId = null;
    this.generation = 0;
  }

  start() {
    if (this.running) {
      return false;
    }
    this.running = true;
    this.generation += 1;
    this.#schedule(0, this.generation);
    return true;
  }

  stop() {
    this.running = false;
    this.generation += 1;
    if (this.timerId !== null) {
      this.clearTimer(this.timerId);
      this.timerId = null;
    }
  }

  async pollOnce() {
    if (this.inFlight) {
      return { polled: false, reason: "in-flight" };
    }
    this.inFlight = true;
    try {
      const snapshot = await this.fetchSnapshot();
      await this.onSnapshot(snapshot);
      return { polled: true, ok: true };
    } catch (error) {
      await this.onError(error);
      return { polled: true, ok: false, error };
    } finally {
      this.inFlight = false;
    }
  }

  #schedule(delayMs, generation) {
    this.timerId = this.setTimer(async () => {
      this.timerId = null;
      await this.pollOnce();
      if (this.running && this.generation === generation) {
        this.#schedule(this.intervalMs, generation);
      }
    }, delayMs);
  }
}

export function createRuntimeSnapshotFetcher({
  apiBaseUrl = "/api",
  timeoutMs = 1_500,
  fetchImpl = fetch,
} = {}) {
  const baseUrl = String(apiBaseUrl || "/api").replace(/\/+$/, "");
  const url = `${baseUrl}/vehicle-snapshot`;

  return async function fetchRuntimeVehicleSnapshot() {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(url, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`Runtime vehicle snapshot HTTP ${response.status}`);
      }
      return await response.json();
    } finally {
      clearTimeout(timeoutId);
    }
  };
}
