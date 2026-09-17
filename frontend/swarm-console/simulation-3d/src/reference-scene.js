import { Color, LabelStyle, Cartesian2, PolygonHierarchy } from "cesium";

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
  return { setVisible: show => entities.forEach(entity => { entity.show = show; }) };
}
