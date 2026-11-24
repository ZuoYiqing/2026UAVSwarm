import {
  ArcType, Cartesian2, Color, ColorGeometryInstanceAttribute, GeometryInstance, LabelStyle,
  PolygonHierarchy, PolylineColorAppearance, PolylineGeometry, Primitive,
} from "cesium";
import entityCatalog from "../../../../scenarios/simple_recon_v0_1/entity_catalog.json" with { type: "json" };

export const REFERENCE_VIEW = Object.freeze({ headingDeg: -25, pitchDeg: -50, rangeM: 330 });

function addDemoMarkers(add, toWorld) {
  const outlines = [];
  for (const [id, row] of Object.entries(entityCatalog.geometry_by_entity_id)) {
    const { display, geometry } = row;
    if (!display) continue;
    const color = Color.fromCssColorString(display.color);
    if (display.kind === "ground_outline") {
      const { north_min_m: n0, north_max_m: n1, east_min_m: e0, east_max_m: e1 } = geometry.horizontal_bounds;
      const height = display.height_m - geometry.down_m;
      const corners = [[e0, n0, height], [e1, n0, height], [e1, n1, height], [e0, n1, height]].map(toWorld);
      add({
        id: `recon-${id}-fill`,
        polygon: { hierarchy: new PolygonHierarchy(corners), perPositionHeight: true, material: color.withAlpha(0.18) },
      });
      outlines.push(new GeometryInstance({
        id: `recon-${id}`,
        geometry: new PolylineGeometry({
          positions: [...corners, corners[0]], width: 4, arcType: ArcType.NONE,
          vertexFormat: PolylineColorAppearance.VERTEX_FORMAT,
        }),
        attributes: { color: ColorGeometryInstanceAttribute.fromColor(color) },
      }));
    } else if (display.kind === "numbered_post") {
      const { east_m: east, north_m: north, down_m: down } = geometry.position;
      add({
        id: `recon-${id}-post`,
        position: toWorld([east, north, display.height_m / 2 - down]),
        cylinder: {
          length: display.height_m, topRadius: display.radius_m,
          bottomRadius: display.radius_m, material: color,
        },
      });
      add({
        id: `recon-${id}`,
        position: toWorld([east, north, display.height_m - down]),
        point: { pixelSize: 12, color, outlineColor: Color.BLACK, outlineWidth: 2 },
        label: {
          text: display.number, font: "bold 20px sans-serif", fillColor: color,
          outlineColor: Color.BLACK, outlineWidth: 3, style: LabelStyle.FILL_AND_OUTLINE,
          showBackground: true, backgroundColor: Color.BLACK.withAlpha(0.7),
          pixelOffset: new Cartesian2(0, -21),
        },
      });
    }
  }
  return outlines;
}

export function createReferenceScene(viewer, toWorld) {
  const entities = [];
  const add = options => entities.push(viewer.entities.add({ ...options, show: false }));
  add({ polygon: { hierarchy: new PolygonHierarchy([[-120,-120,0],[120,-120,0],[120,120,0],[-120,120,0]].map(toWorld)), perPositionHeight: true, material: Color.fromCssColorString("#8b9b90") } });
  for (let v = -120; v <= 120; v += 20) {
    for (const points of [[[v,-120,0.2],[v,120,0.2]],[[-120,v,0.2],[120,v,0.2]]]) {
      add({ polyline: { positions: points.map(toWorld), width: 1, material: Color.fromCssColorString("#c9d5cb") } });
    }
  }
  for (const [text, point, color] of [["E / 东",[100,0,0.5],"#cf785a"],["N / 北",[0,100,0.5],"#447fa0"]]) {
    add({ polyline: { positions: [[0,0,0.5],point].map(toWorld), width: 3, material: Color.fromCssColorString(color) } });
    add({ position: toWorld(point), label: { text, font: "14px sans-serif", fillColor: Color.WHITE, outlineColor: Color.BLACK, outlineWidth: 2, style: LabelStyle.FILL_AND_OUTLINE, pixelOffset: new Cartesian2(0,-12) } });
  }
  // These outlines are reference overlays. Build them on the render thread
  // so they draw on the default reference view even without terrain geometry.
  const outlines = viewer.scene.primitives.add(new Primitive({
    geometryInstances: addDemoMarkers(add, toWorld),
    appearance: new PolylineColorAppearance({
      translucent: false, renderState: { depthTest: { enabled: false } },
    }),
    asynchronous: false,
    show: false,
  }));
  return { setVisible: show => {
    entities.forEach(entity => { entity.show = show; });
    outlines.show = show;
  } };
}
