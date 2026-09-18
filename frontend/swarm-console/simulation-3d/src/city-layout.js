// All positions stay in the existing mission ENU frame (metres).
export const CITY = Object.freeze({
  name: "青岚市",
  bounds: [-1800, -1400, 1800, 1400],
  roadsX: [-1380, -1100, -820, -540, -280, 260, 540, 820, 1100, 1380],
  roadsY: [-1100, -820, -300, 210, 490, 770, 1050],
  bridgeX: [-820, 260, 1100],
});

export const CITY_VIEWS = Object.freeze({
  city: {
    label: "城市总览",
    target: [40, 0, 0],
    range: 3600,
    heading: -22,
    pitch: -49,
  },
  campus: {
    label: "测试园区",
    target: [0, 0, 0],
    range: 660,
    heading: -28,
    pitch: -47,
  },
  downtown: {
    label: "中央商务区",
    target: [815, 605, 55],
    range: 1150,
    heading: -36,
    pitch: -38,
  },
  river: {
    label: "滨河立交",
    target: [265, -580, 12],
    range: 1250,
    heading: 28,
    pitch: -43,
  },
  hills: {
    label: "西岭山林",
    target: [-1040, 850, 140],
    range: 1450,
    heading: 145,
    pitch: -35,
  },
});

export function seededRandom(seed = 2026) {
  return () => {
    seed = (Math.imul(1664525, seed) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

export function riverNorth(east) {
  return -571 + 65 * Math.sin(east / 520);
}

export function bridgeDeckHeight(east, north) {
  return (
    0.6 +
    17 *
      Math.max(0, Math.min(1, (245 - Math.abs(north - riverNorth(east))) / 145))
  );
}

export function createInterchangeRamp(side) {
  const endHeight = bridgeDeckHeight(260, -660);
  return Array.from({ length: 70 }, (_, i) => {
    const t = i / 69,
      angle = t * Math.PI * 1.5;
    return [
      260 + side * 115 + side * 115 * Math.sin(angle),
      -660 - 115 * Math.cos(angle),
      24 + t * (endHeight - 24),
    ];
  });
}

export function terrainHeight(east, north) {
  const edge = Math.max(0, Math.min(1, (north - 270) / 230));
  const peaks = [
    [-1100, 880, 270, 390],
    [-1510, 1140, 160, 300],
    [-700, 1170, 200, 280],
  ];
  return (
    edge *
    peaks.reduce(
      (height, [x, y, z, radius]) =>
        height +
        z * Math.exp(-((east - x) ** 2 + (north - y) ** 2) / radius ** 2),
      0,
    )
  );
}

export function createCityLayout() {
  const random = seededRandom();
  const buildings = [];
  const blocks = [];
  for (let ix = 0; ix < CITY.roadsX.length - 1; ix++) {
    for (let iy = 0; iy < CITY.roadsY.length - 1; iy++) {
      const x0 = CITY.roadsX[ix],
        x1 = CITY.roadsX[ix + 1];
      const y0 = CITY.roadsY[iy],
        y1 = CITY.roadsY[iy + 1];
      const x = (x0 + x1) / 2,
        y = (y0 + y1) / 2;
      if (
        y0 === -820 ||
        [
          [x0, y0],
          [x1, y0],
          [x0, y1],
          [x1, y1],
        ].some(([e, n]) => terrainHeight(e, n) > 5)
      )
        continue;
      if (x0 === -280 && y0 === -300) continue; // Existing campus footprint.
      const park = (ix === 3 && iy === 2) || (ix === 6 && iy === 2);
      const business = ix >= 5 && iy >= 3;
      const block = {
        id: `block-${ix}-${iy}`,
        x,
        y,
        width: x1 - x0 - 34,
        depth: y1 - y0 - 34,
        park,
      };
      blocks.push(block);
      if (park || (ix === 6 && iy === 5)) continue; // Landmark towers own this block.
      const columns = x1 - x0 > 350 ? 4 : 3;
      const rows = y1 - y0 > 350 ? 4 : 3;
      for (let cx = 0; cx < columns; cx++) {
        for (let cy = 0; cy < rows; cy++) {
          const cellW = block.width / columns,
            cellD = block.depth / rows;
          const bx = x0 + 17 + cellW * (cx + 0.5);
          const by = y0 + 17 + cellD * (cy + 0.5);
          const height = business
            ? 45 + Math.floor(random() * 135)
            : 14 + Math.floor(random() * 45);
          buildings.push({
            id: `${block.id}-${cx}-${cy}`,
            x: bx,
            y: by,
            width: cellW * (0.48 + random() * 0.18),
            depth: cellD * (0.45 + random() * 0.18),
            height,
            style: business
              ? "glass"
              : random() > 0.5
                ? "brick"
                : "residential",
            variant: Math.floor(random() * 4),
          });
        }
      }
    }
  }
  return { buildings, blocks };
}
