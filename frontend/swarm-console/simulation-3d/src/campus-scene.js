import {
  Cartesian2,
  Cartesian3,
  Color,
  DistanceDisplayCondition,
  HeadingPitchRoll,
  LabelStyle,
  Math as CesiumMath,
  NearFarScalar,
  Transforms,
  VerticalOrigin,
} from "cesium";

const COLORS = Object.freeze({
  ground: Color.fromCssColorString("#263238"),
  road: Color.fromCssColorString("#39474c"),
  marking: Color.fromCssColorString("#d3d9d7"),
  lawn: Color.fromCssColorString("#31533f"),
  water: Color.fromCssColorString("#286477").withAlpha(0.78),
  operations: Color.fromCssColorString("#dce2df"),
  laboratory: Color.fromCssColorString("#aebbc0"),
  hangar: Color.fromCssColorString("#82949b"),
  logistics: Color.fromCssColorString("#b3a88b"),
  energy: Color.fromCssColorString("#5a7d8c"),
  roof: Color.fromCssColorString("#354a51"),
  accent: Color.fromCssColorString("#36c7f4"),
  safety: Color.fromCssColorString("#f5b84c"),
  boundary: Color.fromCssColorString("#7da0a8"),
  tree: Color.fromCssColorString("#3e7150"),
  trunk: Color.fromCssColorString("#735f48"),
});

function entityLabel(text) {
  return {
    text,
    font: "600 12px Microsoft YaHei",
    fillColor: Color.WHITE,
    outlineColor: Color.fromCssColorString("#071015"),
    outlineWidth: 4,
    style: LabelStyle.FILL_AND_OUTLINE,
    pixelOffset: new Cartesian2(0, -20),
    verticalOrigin: VerticalOrigin.BOTTOM,
    scaleByDistance: new NearFarScalar(140, 1, 1800, 0.45),
    distanceDisplayCondition: new DistanceDisplayCondition(0, 2600),
    disableDepthTestDistance: Number.POSITIVE_INFINITY,
  };
}

export function createCampusScene(viewer, toWorld) {
  const entities = [];

  function add(entity) {
    const created = viewer.entities.add(entity);
    entities.push(created);
    return created;
  }

  function orientationAt(position, headingDeg = 0, pitchDeg = 0) {
    return Transforms.headingPitchRollQuaternion(
      position,
      new HeadingPitchRoll(
        CesiumMath.toRadians(headingDeg),
        CesiumMath.toRadians(pitchDeg),
        0,
      ),
    );
  }

  function addBox({
    id,
    center,
    dimensions,
    color,
    heading = 0,
    outline = true,
    label = "",
  }) {
    const position = toWorld([
      center[0],
      center[1],
      center[2] + dimensions[2] / 2,
    ]);
    return add({
      id: `campus:${id}`,
      position,
      orientation: orientationAt(position, heading),
      box: {
        dimensions: new Cartesian3(...dimensions),
        material: color,
        outline,
        outlineColor: Color.fromCssColorString("#142328").withAlpha(0.76),
      },
      label: label ? entityLabel(label) : undefined,
    });
  }

  function addBuilding({
    id,
    label,
    center,
    size,
    height,
    color,
    heading = 0,
    roofColor = COLORS.roof,
  }) {
    addBox({
      id,
      center: [center[0], center[1], 0.3],
      dimensions: [size[0], size[1], height],
      color,
      heading,
      label,
    });
    addBox({
      id: `${id}:roof`,
      center: [center[0], center[1], height + 0.3],
      dimensions: [size[0] + 1.4, size[1] + 1.4, 1.2],
      color: roofColor,
      heading,
      outline: false,
    });
    addBox({
      id: `${id}:accent`,
      center: [center[0], center[1] - size[1] / 2 - 0.18, 3.2],
      dimensions: [Math.min(size[0] * 0.72, 30), 0.5, 2.4],
      color: COLORS.accent.withAlpha(0.86),
      heading,
      outline: false,
    });
  }

  addBox({
    id: "ground",
    center: [0, 0, -0.45],
    dimensions: [420, 310, 0.8],
    color: COLORS.ground,
    outline: false,
  });

  for (const [id, center, dimensions, heading] of [
    ["road-main", [0, -18, 0.02], [360, 20, 0.18], 0],
    ["road-cross", [-48, 40, 0.03], [18, 230, 0.2], 0],
    ["road-east", [110, 44, 0.03], [18, 220, 0.2], 0],
    ["apron", [-132, -83, 0.04], [108, 72, 0.24], 0],
    ["logistics-yard", [125, -88, 0.04], [86, 76, 0.24], 0],
  ]) {
    addBox({
      id,
      center,
      dimensions,
      color: COLORS.road,
      heading,
      outline: false,
    });
  }

  for (let east = -155; east <= 155; east += 24) {
    addBox({
      id: `main-road-mark-${east}`,
      center: [east, -18, 0.16],
      dimensions: [10, 0.65, 0.08],
      color: COLORS.marking,
      outline: false,
    });
  }

  addBox({
    id: "north-lawn",
    center: [22, 108, 0.02],
    dimensions: [142, 62, 0.14],
    color: COLORS.lawn,
    outline: false,
  });
  addBox({
    id: "west-lawn",
    center: [-142, 66, 0.02],
    dimensions: [72, 62, 0.14],
    color: COLORS.lawn,
    outline: false,
  });

  add({
    id: "campus:retention-pond",
    position: toWorld([158, 112, 0.18]),
    ellipse: {
      semiMajorAxis: 34,
      semiMinorAxis: 18,
      height: 0.18,
      material: COLORS.water,
      outline: true,
      outlineColor: COLORS.boundary,
    },
    label: entityLabel("生态水池"),
  });

  addBuilding({
    id: "operations-center",
    label: "集群运行中心",
    center: [-10, 70],
    size: [68, 36],
    height: 20,
    color: COLORS.operations,
  });
  addBuilding({
    id: "autonomy-lab",
    label: "自主系统实验室",
    center: [-88, 84],
    size: [48, 30],
    height: 15,
    color: COLORS.laboratory,
  });
  addBuilding({
    id: "avionics-lab",
    label: "航电与通信实验室",
    center: [70, 78],
    size: [50, 30],
    height: 16,
    color: COLORS.laboratory,
  });
  addBuilding({
    id: "data-center",
    label: "边缘计算中心",
    center: [70, 126],
    size: [44, 24],
    height: 12,
    color: COLORS.energy,
  });
  addBuilding({
    id: "training-center",
    label: "仿真训练中心",
    center: [-80, 132],
    size: [52, 26],
    height: 13,
    color: COLORS.operations,
  });
  addBuilding({
    id: "hangar-a",
    label: "无人机库 A",
    center: [-142, -86],
    size: [72, 46],
    height: 16,
    color: COLORS.hangar,
  });
  addBuilding({
    id: "hangar-b",
    label: "无人机库 B",
    center: [-142, -30],
    size: [72, 34],
    height: 13,
    color: COLORS.hangar,
  });
  addBuilding({
    id: "maintenance",
    label: "维护保障中心",
    center: [42, -82],
    size: [58, 38],
    height: 14,
    color: COLORS.logistics,
  });
  addBuilding({
    id: "warehouse",
    label: "任务载荷仓",
    center: [126, -87],
    size: [62, 42],
    height: 12,
    color: COLORS.logistics,
  });
  addBuilding({
    id: "energy-station",
    label: "能源补给站",
    center: [142, 2],
    size: [44, 28],
    height: 10,
    color: COLORS.energy,
  });
  addBuilding({
    id: "admin",
    label: "园区管理中心",
    center: [2, 126],
    size: [42, 22],
    height: 11,
    color: COLORS.operations,
  });

  add({
    id: "campus:control-tower",
    position: toWorld([14, 18, 18]),
    cylinder: {
      length: 36,
      topRadius: 6,
      bottomRadius: 9,
      material: COLORS.operations,
      outline: true,
      outlineColor: COLORS.roof,
    },
    label: entityLabel("测控塔"),
  });
  add({
    id: "campus:control-tower-cap",
    position: toWorld([14, 18, 38]),
    cylinder: {
      length: 5,
      topRadius: 12,
      bottomRadius: 10,
      material: COLORS.accent,
    },
  });

  for (const [id, east, north, label] of [
    ["pad-a", -102, -73, "起降坪 A"],
    ["pad-b", -138, -73, "起降坪 B"],
    ["pad-c", -174, -73, "起降坪 C"],
  ]) {
    add({
      id: `campus:${id}`,
      position: toWorld([east, north, 0.32]),
      ellipse: {
        semiMajorAxis: 12,
        semiMinorAxis: 12,
        height: 0.32,
        material: Color.fromCssColorString("#25343a"),
        outline: true,
        outlineColor: COLORS.safety,
        outlineWidth: 3,
      },
      label: entityLabel(label),
    });
  }

  addBox({
    id: "runway",
    center: [18, -142, 0.06],
    dimensions: [278, 24, 0.18],
    color: Color.fromCssColorString("#2d393d"),
    outline: true,
  });
  for (let east = -95; east <= 130; east += 30) {
    addBox({
      id: `runway-mark-${east}`,
      center: [east, -142, 0.18],
      dimensions: [14, 0.8, 0.08],
      color: COLORS.marking,
      outline: false,
    });
  }

  for (let index = 0; index < 10; index += 1) {
    const east = 92 + (index % 5) * 13;
    const north = 28 + Math.floor(index / 5) * 10;
    addBox({
      id: `solar-${index}`,
      center: [east, north, 2.1],
      dimensions: [10, 5, 0.45],
      color: Color.fromCssColorString("#315b76"),
      heading: -12,
      outline: false,
    });
  }

  for (const [index, east, north] of [
    [0, -170, 118],
    [1, -145, 116],
    [2, -120, 118],
    [3, -170, 82],
    [4, -145, 80],
    [5, 122, 122],
    [6, 140, 138],
    [7, 170, 132],
    [8, 178, 96],
    [9, 156, 82],
    [10, -18, 104],
    [11, 18, 104],
  ]) {
    add({
      id: `campus:tree-trunk-${index}`,
      position: toWorld([east, north, 2.5]),
      cylinder: {
        length: 5,
        topRadius: 0.7,
        bottomRadius: 0.9,
        material: COLORS.trunk,
      },
    });
    add({
      id: `campus:tree-crown-${index}`,
      position: toWorld([east, north, 7]),
      ellipsoid: {
        radii: new Cartesian3(4.6, 4.6, 5.8),
        material: COLORS.tree,
      },
    });
  }

  add({
    id: "campus:boundary",
    polyline: {
      positions: [
        toWorld([-210, -155, 0.8]),
        toWorld([210, -155, 0.8]),
        toWorld([210, 155, 0.8]),
        toWorld([-210, 155, 0.8]),
        toWorld([-210, -155, 0.8]),
      ],
      width: 2,
      material: COLORS.boundary.withAlpha(0.82),
    },
  });

  return {
    entities,
    setVisible(visible) {
      entities.forEach((entity) => {
        entity.show = visible;
      });
    },
  };
}
