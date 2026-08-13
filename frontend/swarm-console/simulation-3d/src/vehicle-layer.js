import {
  BillboardGraphics,
  Cartesian2,
  Cartesian3,
  Color,
  DistanceDisplayCondition,
  HeadingPitchRoll,
  HorizontalOrigin,
  LabelGraphics,
  LabelStyle,
  Math as CesiumMath,
  NearFarScalar,
  PolylineGlowMaterialProperty,
  Transforms,
  VerticalOrigin,
} from "cesium";

const TYPE_COLORS = Object.freeze({
  multirotor: "#36c7f4",
  fixed_wing: "#f5b84c",
  vtol: "#9a7cff",
  ugv: "#ff7b5f",
  usv: "#42d883",
  uuv: "#4a8dff",
  unknown: "#d7e1e3",
});

const markerCache = new Map();

function createMarker(vehicleType, cssColor) {
  const key = `${vehicleType}:${cssColor}`;
  if (markerCache.has(key)) {
    return markerCache.get(key);
  }

  const canvas = document.createElement("canvas");
  canvas.width = 112;
  canvas.height = 112;
  const context = canvas.getContext("2d");
  context.translate(56, 56);
  context.strokeStyle = "#061014";
  context.lineWidth = 8;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.fillStyle = cssColor;

  if (vehicleType === "fixed_wing") {
    context.beginPath();
    context.moveTo(0, -40);
    context.lineTo(13, -8);
    context.lineTo(43, 8);
    context.lineTo(12, 12);
    context.lineTo(8, 38);
    context.lineTo(0, 30);
    context.lineTo(-8, 38);
    context.lineTo(-12, 12);
    context.lineTo(-43, 8);
    context.lineTo(-13, -8);
    context.closePath();
    context.fill();
    context.stroke();
  } else if (vehicleType === "vtol") {
    context.beginPath();
    context.moveTo(0, -38);
    context.lineTo(15, -6);
    context.lineTo(38, 7);
    context.lineTo(12, 13);
    context.lineTo(0, 34);
    context.lineTo(-12, 13);
    context.lineTo(-38, 7);
    context.lineTo(-15, -6);
    context.closePath();
    context.fill();
    context.stroke();
    for (const x of [-34, 34]) {
      context.beginPath();
      context.arc(x, 8, 9, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    }
  } else if (vehicleType === "ugv") {
    context.fillRect(-32, -22, 64, 44);
    context.strokeRect(-32, -22, 64, 44);
    for (const [x, y] of [
      [-30, -28],
      [30, -28],
      [-30, 28],
      [30, 28],
    ]) {
      context.beginPath();
      context.arc(x, y, 9, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    }
  } else if (vehicleType === "usv" || vehicleType === "uuv") {
    context.beginPath();
    context.moveTo(0, -38);
    context.lineTo(28, 20);
    context.lineTo(0, 36);
    context.lineTo(-28, 20);
    context.closePath();
    context.fill();
    context.stroke();
  } else {
    for (const [x, y] of [
      [-28, -28],
      [28, -28],
      [-28, 28],
      [28, 28],
    ]) {
      context.beginPath();
      context.moveTo(x * 0.42, y * 0.42);
      context.lineTo(x, y);
      context.stroke();
      context.beginPath();
      context.arc(x, y, 11, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    }
    context.fillRect(-9, -18, 18, 36);
    context.beginPath();
    context.moveTo(0, -31);
    context.lineTo(9, -12);
    context.lineTo(-9, -12);
    context.closePath();
    context.fill();
    context.stroke();
  }

  const image = canvas.toDataURL("image/png");
  markerCache.set(key, image);
  return image;
}

function colorForVehicle(vehicle) {
  return vehicle.color || TYPE_COLORS[vehicle.vehicleType] || TYPE_COLORS.unknown;
}

function hasFreshPose(vehicle) {
  return vehicle.connected && !vehicle.telemetry.stale;
}

export class VehicleLayer {
  constructor(viewer, positionToWorld) {
    this.viewer = viewer;
    this.positionToWorld = positionToWorld;
    this.records = new Map();
    this.entityToVehicle = new Map();
    this.selectedVehicleId = "";
    this.routesVisible = true;
    this.labelsVisible = true;
    this.visible = true;
    this.dataStale = false;
  }

  applySnapshot(snapshot) {
    const receivedIds = new Set();
    for (const vehicle of snapshot.vehicles) {
      receivedIds.add(vehicle.id);
      this.upsertVehicle(vehicle, snapshot.timestampMs);
    }

    if (snapshot.fullState) {
      for (const vehicleId of this.records.keys()) {
        if (!receivedIds.has(vehicleId)) {
          this.removeVehicle(vehicleId);
        }
      }
    }

    if (
      !this.selectedVehicleId ||
      !this.records.has(this.selectedVehicleId)
    ) {
      this.setSelected(snapshot.vehicles[0]?.id || "");
    }
  }

  upsertVehicle(vehicle, timestampMs) {
    const colorCss = colorForVehicle(vehicle);
    const color = Color.fromCssColorString(colorCss);
    let record = this.records.get(vehicle.id);
    const freezePose = Boolean(record && !hasFreshPose(vehicle));
    const worldPosition = freezePose
      ? record.worldPosition
      : this.positionToWorld(vehicle.position);

    if (!record) {
      const trailPositions = [worldPosition.clone()];
      const routeEntity = this.viewer.entities.add({
        id: `vehicle-route:${vehicle.id}`,
        show: this.visible && this.routesVisible,
        polyline: {
          positions: trailPositions,
          width: 3,
          material: new PolylineGlowMaterialProperty({
            color: color.withAlpha(0.9),
            glowPower: 0.22,
            taperPower: 0.5,
          }),
        },
      });
      const entity = this.viewer.entities.add({
        id: `vehicle:${vehicle.id}`,
        show: this.visible,
        position: worldPosition,
        orientation: Transforms.headingPitchRollQuaternion(
          worldPosition,
          new HeadingPitchRoll(
            CesiumMath.toRadians(vehicle.attitude.yawDeg),
            CesiumMath.toRadians(vehicle.attitude.pitchDeg),
            CesiumMath.toRadians(vehicle.attitude.rollDeg),
          ),
        ),
        billboard: new BillboardGraphics({
          image: createMarker(vehicle.vehicleType, colorCss),
          scale: 0.42,
          rotation: -CesiumMath.toRadians(vehicle.attitude.yawDeg),
          verticalOrigin: VerticalOrigin.CENTER,
          horizontalOrigin: HorizontalOrigin.CENTER,
          pixelOffset: new Cartesian2(0, -5),
          scaleByDistance: new NearFarScalar(100, 0.74, 3000, 0.24),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 9000),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        }),
        label: new LabelGraphics({
          text: vehicle.displayName,
          show: this.labelsVisible,
          font: "600 14px Segoe UI",
          fillColor: Color.WHITE,
          outlineColor: Color.fromCssColorString("#071015"),
          outlineWidth: 4,
          style: LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cartesian2(0, 30),
          scaleByDistance: new NearFarScalar(100, 1, 3000, 0.5),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        }),
      });
      record = {
        vehicle,
        entity,
        routeEntity,
        trailPositions,
        worldPosition,
        lastTrailTimestampMs: timestampMs,
        markerKey: `${vehicle.vehicleType}:${colorCss}`,
      };
      this.records.set(vehicle.id, record);
      this.entityToVehicle.set(entity.id, vehicle.id);
    } else {
      record.vehicle = vehicle;
      const markerKey = `${vehicle.vehicleType}:${colorCss}`;
      if (record.markerKey !== markerKey) {
        record.entity.billboard.image = createMarker(vehicle.vehicleType, colorCss);
        record.markerKey = markerKey;
      }
      if (!freezePose) {
        record.worldPosition = worldPosition;
        record.entity.position = worldPosition;
        record.entity.orientation = Transforms.headingPitchRollQuaternion(
          worldPosition,
          new HeadingPitchRoll(
            CesiumMath.toRadians(vehicle.attitude.yawDeg),
            CesiumMath.toRadians(vehicle.attitude.pitchDeg),
            CesiumMath.toRadians(vehicle.attitude.rollDeg),
          ),
        );
        record.entity.billboard.rotation = -CesiumMath.toRadians(
          vehicle.attitude.yawDeg,
        );
        if (
          timestampMs - record.lastTrailTimestampMs >= 450 &&
          Cartesian3.distance(
            record.trailPositions[record.trailPositions.length - 1],
            worldPosition,
          ) >= 1
        ) {
          record.trailPositions.push(worldPosition.clone());
          if (record.trailPositions.length > 160) {
            record.trailPositions.shift();
          }
          record.routeEntity.polyline.positions = [...record.trailPositions];
          record.lastTrailTimestampMs = timestampMs;
        }
      }
    }

    record.entity.show = this.visible;
    record.routeEntity.show = this.visible && this.routesVisible;
    record.entity.label.show = this.labelsVisible;
    this.#applyRecordState(record);
  }

  removeVehicle(vehicleId) {
    const record = this.records.get(vehicleId);
    if (!record) {
      return;
    }
    this.viewer.entities.remove(record.entity);
    this.viewer.entities.remove(record.routeEntity);
    this.entityToVehicle.delete(record.entity.id);
    this.records.delete(vehicleId);
  }

  setSelected(vehicleId) {
    this.selectedVehicleId = this.records.has(vehicleId) ? vehicleId : "";
    for (const [id, record] of this.records) {
      const selected = id === this.selectedVehicleId;
      record.entity.billboard.scale = selected ? 0.56 : 0.42;
      this.#applyRecordState(record, selected);
    }
  }

  setDataStale(stale) {
    if (this.dataStale === stale) {
      return;
    }
    this.dataStale = stale;
    for (const [id, record] of this.records) {
      this.#applyRecordState(record, id === this.selectedVehicleId);
    }
  }

  #applyRecordState(record, selected = record.vehicle.id === this.selectedVehicleId) {
    const stale =
      this.dataStale ||
      record.vehicle.telemetry.stale ||
      !record.vehicle.connected;
    record.entity.billboard.color = stale
      ? Color.WHITE.withAlpha(0.48)
      : Color.WHITE;
    record.entity.label.text = stale
      ? `${record.vehicle.displayName} · STALE`
      : record.vehicle.displayName;
    record.entity.label.fillColor = stale
      ? Color.fromCssColorString("#f5b84c")
      : selected
        ? Color.fromCssColorString("#36c7f4")
        : Color.WHITE;
  }

  setRoutesVisible(visible) {
    this.routesVisible = visible;
    for (const record of this.records.values()) {
      record.routeEntity.show = this.visible && visible;
    }
  }

  setLabelsVisible(visible) {
    this.labelsVisible = visible;
    for (const record of this.records.values()) {
      record.entity.label.show = visible;
    }
  }

  setVisible(visible) {
    this.visible = visible;
    for (const record of this.records.values()) {
      record.entity.show = visible;
      record.routeEntity.show = visible && this.routesVisible;
    }
  }

  vehicleIdFromPickedEntity(entity) {
    return entity ? this.entityToVehicle.get(entity.id) || "" : "";
  }

  getSelectedRecord() {
    return this.records.get(this.selectedVehicleId);
  }

  getRecords() {
    return [...this.records.values()];
  }

  isRecordStale(record) {
    return Boolean(
      record &&
      (this.dataStale || record.vehicle.telemetry.stale || !record.vehicle.connected),
    );
  }
}
