import {
  BoxGeometry,
  BufferGeometry,
  CylinderGeometry,
  Float32BufferAttribute,
  IcosahedronGeometry,
  Matrix4,
  Quaternion,
  Vector3,
} from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import {
  CITY,
  bridgeDeckHeight,
  createCityLayout,
  createInterchangeRamp,
  riverNorth,
  seededRandom,
  terrainHeight,
} from "./city-layout.js";

const P = {
  land: "#9cab91",
  hill: "#68865b",
  pavement: "#c3c7c0",
  road: "#49565b",
  edge: "#9ba9a5",
  line: "#e8e6cd",
  water: "#4f9ead",
  bank: "#92ad83",
  glass: ["#577e8d", "#688e9e", "#7598a8", "#4e7082"],
  wall: ["#c5c9c4", "#b2b9b9", "#d8d9ce", "#a5afb3"],
  brick: ["#a67c69", "#b3917a", "#c0a18a", "#a38e7f"],
  window: "#476975",
  roof: "#87989b",
  green: ["#507b4e", "#648947", "#7a994f", "#3e6d55"],
  bark: "#786b56",
  rail: "#d3d8d3",
  accent: "#dfaf54",
  solar: "#355d78",
};

// Three.js supplies geometry only; Cesium remains the sole renderer and camera.
export function buildCityGeometry() {
  const batches = new Map();
  const random = seededRandom(74021);
  let treeCount = 0;
  const { buildings, blocks } = createCityLayout();
  function add(layer, color, geometry) {
    geometry.deleteAttribute("uv");
    if (!geometry.index)
      geometry.setIndex(
        Array.from({ length: geometry.attributes.position.count }, (_, i) => i),
      );
    const key = `${layer}:${color}`;
    if (!batches.has(key)) batches.set(key, { layer, color, parts: [] });
    batches.get(key).parts.push(geometry);
  }
  function box(layer, color, x, y, z, w, d, h, rotation = 0) {
    const geometry = new BoxGeometry(w, d, h);
    geometry.rotateZ(rotation);
    geometry.translate(x, y, z + h / 2);
    add(layer, color, geometry);
  }
  function cylinder(
    layer,
    color,
    x,
    y,
    z,
    radius,
    height,
    top = radius,
    segments = 8,
  ) {
    const geometry = new CylinderGeometry(top, radius, height, segments);
    geometry.rotateX(Math.PI / 2);
    geometry.translate(x, y, z + height / 2);
    add(layer, color, geometry);
  }
  function line(layer, color, a, b, radius = 0.7) {
    const start = new Vector3(...a),
      end = new Vector3(...b);
    const delta = end.clone().sub(start);
    const geometry = new CylinderGeometry(radius, radius, delta.length(), 6);
    geometry.applyMatrix4(
      new Matrix4().compose(
        start.add(end).multiplyScalar(0.5),
        new Quaternion().setFromUnitVectors(
          new Vector3(0, 1, 0),
          delta.normalize(),
        ),
        new Vector3(1, 1, 1),
      ),
    );
    add(layer, color, geometry);
  }
  function ribbon(layer, color, points, width) {
    const positions = [],
      indices = [];
    points.forEach((point, i) => {
      const a = points[Math.max(0, i - 1)],
        b = points[Math.min(points.length - 1, i + 1)];
      const dx = b[0] - a[0],
        dy = b[1] - a[1],
        length = Math.hypot(dx, dy);
      const ox = ((-dy / length) * width) / 2,
        oy = ((dx / length) * width) / 2;
      positions.push(
        point[0] + ox,
        point[1] + oy,
        point[2],
        point[0] - ox,
        point[1] - oy,
        point[2],
      );
      if (i) {
        const k = i * 2;
        indices.push(k - 2, k - 1, k, k - 1, k + 1, k);
      }
    });
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(positions, 3));
    g.setIndex(indices);
    g.computeVertexNormals();
    add(layer, color, g);
  }
  function tree(x, y, z = 0, size = 1, pine = false) {
    treeCount++;
    cylinder("vegetation", P.bark, x, y, z, 0.7 * size, 5 * size);
    if (pine) {
      cylinder(
        "vegetation",
        P.green[treeCount % 4],
        x,
        y,
        z + 3 * size,
        5.2 * size,
        13 * size,
        0,
        7,
      );
    } else {
      const g = new IcosahedronGeometry(1, 1);
      g.scale(5.4 * size, 5.4 * size, 6.7 * size);
      g.translate(x, y, z + 8 * size);
      add("vegetation", P.green[treeCount % 4], g);
    }
  }

  // Continuous relief, with the flat mission plane preserved at the campus.
  const terrain = new BufferGeometry(),
    points = [],
    indices = [];
  const nx = 90,
    ny = 70;
  for (let j = 0; j <= ny; j++)
    for (let i = 0; i <= nx; i++) {
      const x = -1800 + i * 40,
        y = -1400 + j * 40;
      points.push(x, y, terrainHeight(x, y) - 2);
      if (i && j) {
        const k = j * (nx + 1) + i;
        indices.push(k - nx - 2, k - nx - 1, k, k - nx - 2, k, k - 1);
      }
    }
  terrain.setAttribute("position", new Float32BufferAttribute(points, 3));
  terrain.setIndex(indices);
  terrain.computeVertexNormals();
  add("terrain", P.land, terrain);
  const riverPoints = Array.from({ length: 91 }, (_, i) => [
    -1800 + i * 40,
    riverNorth(-1800 + i * 40),
    0.4,
  ]);
  ribbon(
    "terrain",
    P.bank,
    riverPoints.map(([x, y]) => [x, y, 0.1]),
    207,
  );
  ribbon("terrain", P.water, riverPoints, 147);
  for (const side of [-1, 1]) {
    ribbon(
      "terrain",
      P.pavement,
      riverPoints.map(([x, y]) => [x, y + side * 91, 0.65]),
      8,
    );
    for (let x = -1730; x < 1730; x += 33)
      tree(x, riverNorth(x) + side * 106, 0, 0.8 + random() * 0.5);
  }

  // Street surfaces, medians, crossings, sidewalks and roadside trees.
  for (const y of CITY.roadsY) {
    for (let x = -1410; x < 1400; x += 20) {
      if (terrainHeight(x, y) > 2) continue;
      box("transport", P.pavement, x, y, -0.1, 20.1, 32, 0.3);
      box("transport", P.road, x, y, 0.25, 20.1, 23, 0.2);
      box("transport", P.line, x, y, 0.5, 8, 0.45, 0.03);
      if (CITY.roadsX.every((rx) => Math.abs(rx - x) > 28) && x % 40 === 10) {
        tree(x, y + 18, 0, 0.85);
        tree(x, y - 18, 0, 0.85);
      }
    }
  }
  for (const x of CITY.roadsX) {
    const crossing = CITY.bridgeX.includes(x),
      river = riverNorth(x);
    const bridgeHeight = (y) => (crossing ? bridgeDeckHeight(x, y) - 0.6 : 0);
    for (let y = -1120; y < 1070; y += 20) {
      if (terrainHeight(x, y) > 2 || (!crossing && Math.abs(y - river) < 112))
        continue;
      const z = bridgeHeight(y);
      if (z > 0) continue;
      box("transport", P.pavement, x, y, 0, 32, 20.1, 0.3);
      box("transport", P.road, x, y, 0.35, 23, 20.1, 0.2);
      box("transport", P.line, x, y, 0.6, 0.45, 8, 0.03);
      if (CITY.roadsY.every((ry) => Math.abs(ry - y) > 28) && y % 40 === 0) {
        tree(x + 18, y, 0, 0.85);
        tree(x - 18, y, 0, 0.85);
      }
    }
    if (crossing) {
      const path = Array.from({ length: 51 }, (_, i) => {
        const y = river - 250 + i * 10;
        return [x, y, bridgeHeight(y) + 0.6];
      });
      ribbon(
        "transport",
        P.edge,
        path.map(([a, b, c]) => [a, b, c - 0.25]),
        29,
      );
      ribbon("transport", P.road, path, 24);
      for (const offset of [-13, 13])
        ribbon(
          "transport",
          P.rail,
          path.map(([a, b, c]) => [a + offset, b, c + 1.2]),
          0.7,
        );
      ribbon(
        "transport",
        P.line,
        path.map(([a, b, c]) => [a, b, c + 0.05]),
        0.5,
      );
      for (const offset of [-65, 65]) {
        for (const side of [-1, 1]) {
          const px = x + side * 11,
            py = river + offset;
          cylinder("transport", P.wall[2], px, py, 0, 2.3, 58, 1.7);
          for (let cable = -5; cable <= 5; cable++)
            line(
              "transport",
              P.rail,
              [px, py, 56],
              [px, py + cable * 13, 18],
              0.45,
            );
        }
      }
    }
  }
  for (const x of CITY.roadsX)
    for (const y of CITY.roadsY) {
      if (terrainHeight(x, y) > 2) continue;
      for (const side of [-1, 1])
        for (let s = -8; s <= 8; s += 3) {
          box("transport", P.line, x + s, y + side * 17, 0.68, 1.5, 5, 0.04);
          box("transport", P.line, x + side * 17, y + s, 0.68, 5, 1.5, 0.04);
        }
    }

  // East-west elevated expressway with continuous loop ramps onto the river bridge.
  const express = Array.from({ length: 91 }, (_, i) => [
    -1500 + i * 34,
    -775,
    24,
  ]);
  ribbon(
    "transport",
    P.edge,
    express.map(([x, y, z]) => [x, y, z - 0.4]),
    33,
  );
  ribbon("transport", P.road, express, 30);
  for (const offset of [-15, 0, 15])
    ribbon(
      "transport",
      offset === 0 ? P.accent : P.rail,
      express.map(([x, y, z]) => [x, y + offset, z + 0.7]),
      0.6,
    );
  for (let x = -1450; x < 1520; x += 85) {
    cylinder("transport", P.wall[1], x, -775, 0, 3.2, 23);
    for (const y of [-782, -768])
      box("transport", P.line, x, y, 24.04, 10, 0.4, 0.04);
  }
  for (const side of [-1, 1]) {
    const loop = createInterchangeRamp(side);
    ribbon(
      "transport",
      P.edge,
      loop.map(([x, y, z]) => [x, y, z - 0.5]),
      12,
    );
    ribbon("transport", P.road, loop, 10);
    ribbon(
      "transport",
      P.line,
      loop.map(([x, y, z]) => [x, y, z + 0.03]),
      0.4,
    );
    for (let i = 0; i < loop.length; i += 10) {
      const [x, y, z] = loop[i];
      cylinder("transport", P.wall[1], x, y, 0, 1.8, z - 0.5);
    }
  }

  for (const block of blocks) {
    box(
      "terrain",
      block.park ? "#81a269" : P.pavement,
      block.x,
      block.y,
      -0.4,
      block.width,
      block.depth,
      0.45,
    );
    if (block.park) {
      if (block.x === 680) {
        for (let y = -265; y < 180; y += 25) {
          for (const x of [567, 793]) tree(x, y, 0, 0.9);
        }
        continue;
      }
      const path = Array.from({ length: 49 }, (_, i) => {
        const t = (i * Math.PI) / 24;
        return [
          block.x + Math.cos(t) * block.width * 0.35,
          block.y + Math.sin(t) * block.depth * 0.36,
          0.4,
        ];
      });
      ribbon("terrain", "#d2ceba", path, 5);
      for (let i = 0; i < 65; i++)
        tree(
          block.x + (random() - 0.5) * (block.width - 24),
          block.y + (random() - 0.5) * (block.depth - 24),
          0,
          0.9 + random() * 0.7,
        );
      cylinder("terrain", P.water, block.x, block.y, 0.3, 20, 0.3, 20, 32);
    }
  }

  for (const b of buildings) {
    const { x, y, width: w, depth: d, height: h, variant: v } = b;
    const wall =
      b.style === "glass"
        ? P.glass[v]
        : b.style === "brick"
          ? P.brick[v]
          : P.wall[v];
    box("buildings", P.roof, x, y, 0.1, w + 5, d + 5, 3);
    box("buildings", wall, x, y, 3, w, d, h);
    box("buildings", P.wall[2], x, y, h + 3, w + 1.5, d + 1.5, 1.5);
    box(
      "buildings",
      P.roof,
      x + w * 0.16,
      y,
      h + 4.5,
      w * 0.38,
      d * 0.45,
      4 + v,
    );
    const step = b.style === "glass" ? 8 : 6;
    for (let z = 7; z < h; z += step) {
      const band = b.style === "glass" ? P.wall[v] : P.window;
      const bh = b.style === "glass" ? 0.65 : 2.4;
      for (const side of [-1, 1]) {
        box(
          "buildings",
          band,
          x,
          y + side * (d / 2 + 0.06),
          z,
          w - 3,
          0.16,
          bh,
        );
        box(
          "buildings",
          band,
          x + side * (w / 2 + 0.06),
          y,
          z,
          0.16,
          d - 3,
          bh,
        );
      }
    }
    for (const side of [-1, 1]) {
      for (let i = -1; i <= 1; i++)
        box(
          "buildings",
          wall,
          x + (i * w) / 4,
          y + side * (d / 2 + 0.22),
          4,
          1.3,
          0.6,
          h - 2,
        );
      if (b.style === "glass")
        box("buildings", P.wall[2], x + (side * w) / 2, y, 4, 1.2, d + 1, h);
    }
    if (v === 0 && b.style === "glass") {
      cylinder("buildings", P.rail, x, y, h + 9, 0.65, 14);
      box("buildings", P.accent, x, y, h + 23, 2, 2, 1);
    }
    if (v === 2 && b.style === "glass") {
      cylinder(
        "buildings",
        P.glass[1],
        x,
        y,
        h + 4,
        w * 0.25,
        12,
        w * 0.18,
        16,
      );
    }
    if (v === 3) {
      box(
        "buildings",
        P.green[2],
        x - w * 0.25,
        y,
        h + 4.6,
        w * 0.3,
        d * 0.8,
        0.6,
      );
    }
  }
  // Landmark paired towers, with a skybridge and a lower public podium.
  for (const x of [728, 808]) {
    box("buildings", P.glass[0], x, 885, 0, 46, 54, 226);
    for (let z = 5; z < 226; z += 7)
      box("buildings", P.wall[2], x, 885, z, 47, 55, 0.8);
    box("buildings", P.wall[2], x, 885, 226, 38, 46, 14);
  }
  box("buildings", P.glass[1], 768, 885, 164, 82, 22, 16);
  box("buildings", P.wall[2], 750, 885, 0, 160, 100, 9);
  box("buildings", P.glass[2], 750, 833, 0, 144, 4, 7);
  for (let x = 686; x < 825; x += 15) tree(x, 811, 0, 0.9);

  // A civic sports ground beside the river, with a running track and courts.
  const stadiumX = 680,
    stadiumY = -55;
  const oval = Array.from({ length: 65 }, (_, i) => {
    const t = (i * Math.PI) / 32;
    return [stadiumX + Math.cos(t) * 72, stadiumY + Math.sin(t) * 112, 0.9];
  });
  ribbon("terrain", "#b67a68", oval, 11);
  box("terrain", "#527e61", stadiumX, stadiumY, 0.65, 90, 156, 0.2);
  for (const x of [-42, 42])
    box("terrain", P.line, stadiumX + x, stadiumY, 0.95, 0.3, 145, 0.03);
  for (const y of [-72, 0, 72])
    box("terrain", P.line, stadiumX, stadiumY + y, 0.95, 84, 0.3, 0.03);
  box("buildings", P.wall[2], stadiumX - 94, stadiumY, 0, 18, 124, 8);
  box("buildings", P.roof, stadiumX - 94, stadiumY, 8, 24, 128, 1);

  // Forest is elevation-aware and cannot intrude into mission streets.
  for (let i = 0; i < 1350; i++) {
    const x = -1720 + random() * 1300,
      y = 350 + random() * 980,
      h = terrainHeight(x, y);
    if (h < 12 || h > 278) continue;
    tree(x, y, h - 1.6, 1 + random() * 1.1, true);
  }
  const trail = Array.from({ length: 150 }, (_, i) => {
    const t = i / 149,
      x = -450 - t * 990,
      y = 380 + t * 820 + 60 * Math.sin(t * 18);
    return [x, y, terrainHeight(x, y) + 0.3];
  });
  ribbon("terrain", "#c3b79a", trail, 5);
  const pavilionX = -1080,
    pavilionY = 870,
    pavilionZ = terrainHeight(pavilionX, pavilionY);
  cylinder(
    "buildings",
    P.wall[2],
    pavilionX,
    pavilionY,
    pavilionZ,
    13,
    4,
    13,
    8,
  );
  cylinder(
    "buildings",
    P.brick[0],
    pavilionX,
    pavilionY,
    pavilionZ + 8,
    19,
    8,
    0,
    8,
  );
  for (const x of [-8, 8])
    for (const y of [-8, 8])
      cylinder(
        "buildings",
        P.wall[2],
        pavilionX + x,
        pavilionY + y,
        pavilionZ,
        0.6,
        9,
      );

  // The mission campus uses the same ENU origin, with no changes to vehicle poses.
  box("terrain", "#b1b9b0", 0, 0, -0.25, 420, 310, 0.35);
  box("transport", P.road, 0, -25, 0.2, 405, 14, 0.15);
  box("transport", P.road, 0, -145, 0.2, 294, 19, 0.15);
  box("transport", P.road, 112, 12, 0.2, 12, 265, 0.15);
  for (let x = -180; x < 195; x += 22)
    box("transport", P.line, x, -25, 0.4, 9, 0.35, 0.03);
  for (let x = -126; x <= 126; x += 22)
    box("transport", P.line, x, -145, 0.4, 11, 0.45, 0.03);
  for (const end of [-130, 130])
    for (let y = -151; y <= -139; y += 3)
      box("transport", P.line, end, y, 0.4, 12, 1, 0.03);
  const campusBuildings = [
    [-10, 75, 68, 36, 22],
    [-88, 85, 48, 30, 16],
    [70, 78, 50, 30, 18],
    [70, 125, 44, 24, 12],
    [-80, 130, 52, 26, 14],
    [0, 128, 42, 22, 12],
    [-142, 24, 72, 42, 16],
    [-142, 74, 72, 34, 13],
    [42, -82, 58, 38, 14],
    [126, -87, 62, 42, 12],
    [156, 15, 44, 28, 10],
  ];
  for (const [x, y, w, d, h] of campusBuildings) {
    box("buildings", P.wall[2], x, y, 0.3, w, d, h);
    box("buildings", P.roof, x, y, h + 0.3, w + 1.5, d + 1.5, 1);
    for (let z = 4; z < h; z += 4)
      box("buildings", P.glass[0], x, y - d / 2 - 0.12, z, w - 5, 0.3, 1.7);
    if (x === -142)
      box("buildings", P.glass[1], x, y - d / 2 - 0.2, 0.5, w * 0.75, 0.4, 10);
  }
  cylinder("buildings", P.wall[2], 14, 18, 0, 5, 34);
  cylinder("buildings", P.glass[1], 14, 18, 34, 10, 5, 10, 12);
  cylinder("buildings", P.rail, 14, 18, 39, 11, 1, 11, 12);
  line("buildings", P.rail, [14, 18, 40], [14, 18, 48], 0.45);
  box("terrain", P.roof, -139, -82, 0.4, 120, 75, 0.3);
  for (const x of [-177, -139, -101]) {
    const ring = Array.from({ length: 33 }, (_, i) => {
      const t = (i * Math.PI) / 16;
      return [x + 12 * Math.cos(t), -80 + 12 * Math.sin(t), 0.76];
    });
    ribbon("transport", P.accent, ring, 0.6);
    for (const side of [-1, 1])
      box("transport", P.line, x + side * 3.5, -80, 0.77, 1, 12, 0.03);
    box("transport", P.line, x, -80, 0.77, 8, 1, 0.03);
  }
  for (const side of [-1, 1]) {
    box("buildings", P.rail, side * 210, 0, 0, 0.6, 310, 1.8);
    box("buildings", P.rail, 0, side * 155, 0, 420, 0.6, 1.8);
  }
  for (let x = -198; x <= 198; x += 22) tree(x, 149, 0, 0.7);
  for (let y = -100; y <= 120; y += 22) tree(200, y, 0, 0.65);
  box("terrain", "#719467", -45, 9, 0.2, 63, 38, 0.2);
  for (const x of [-65, -42, -20]) tree(x, 9, 0, 0.7);
  for (let i = 0; i < 6; i++) {
    box(
      "buildings",
      P.solar,
      100 + (i % 3) * 12,
      50 + Math.floor(i / 3) * 9,
      3,
      10,
      6,
      0.3,
    );
  }

  const geometries = [];
  for (const batch of batches.values()) {
    const geometry = mergeGeometries(batch.parts, false);
    if (!geometry) throw new Error(`Cannot merge city batch ${batch.layer}`);
    geometries.push({ layer: batch.layer, color: batch.color, geometry });
    batch.parts.forEach((g) => g.dispose());
  }
  // Two landmark towers, a sports stand, a hill pavilion and the control tower.
  const specialBuildings = 5;
  return {
    geometries,
    stats: {
      buildings: buildings.length + campusBuildings.length + specialBuildings,
      trees: treeCount,
      bridges: CITY.bridgeX.length,
      areaKm2: 10.08,
    },
  };
}
