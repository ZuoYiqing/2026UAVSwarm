import {
  BoundingSphere,
  Cartesian2,
  Color,
  ColorGeometryInstanceAttribute,
  ComponentDatatype,
  Geometry,
  GeometryAttribute,
  GeometryInstance,
  LabelStyle,
  NearFarScalar,
  PerInstanceColorAppearance,
  Primitive,
  PrimitiveType,
  ShadowMode,
} from "cesium";
import { buildCityGeometry } from "./city-geometry.js";
import { CITY_VIEWS, terrainHeight } from "./city-layout.js";

export function createCityScene(viewer, modelMatrix, toWorld) {
  const { geometries, stats } = buildCityGeometry();
  const layers = new Map();
  for (const batch of geometries) {
    const { geometry: mesh, color, layer } = batch;
    const positions = new Float64Array(mesh.attributes.position.array);
    const geometry = new Geometry({
      attributes: {
        position: new GeometryAttribute({
          componentDatatype: ComponentDatatype.DOUBLE,
          componentsPerAttribute: 3,
          values: positions,
        }),
        normal: new GeometryAttribute({
          componentDatatype: ComponentDatatype.FLOAT,
          componentsPerAttribute: 3,
          values: mesh.attributes.normal.array,
        }),
      },
      indices: mesh.index.array,
      primitiveType: PrimitiveType.TRIANGLES,
      boundingSphere: BoundingSphere.fromVertices(positions),
    });
    if (!layers.has(layer)) layers.set(layer, []);
    layers
      .get(layer)
      .push(
        new GeometryInstance({
          geometry,
          attributes: {
            color: ColorGeometryInstanceAttribute.fromColor(
              Color.fromCssColorString(color),
            ),
          },
        }),
      );
    mesh.dispose();
  }
  const primitives = new Map();
  for (const [layer, geometryInstances] of layers) {
    primitives.set(
      layer,
      viewer.scene.primitives.add(
        new Primitive({
          geometryInstances,
          modelMatrix,
          appearance: new PerInstanceColorAppearance({
            translucent: false,
            closed: true,
          }),
          asynchronous: false,
          allowPicking: false,
          shadows: ShadowMode.ENABLED,
        }),
      ),
    );
  }
  const labels = [];
  for (const [id, text, position] of [
    ["campus", "无人系统测试园区", [0, 80, 35]],
    ["downtown", "中央商务区", [850, 630, 240]],
    ["river", "青岚河 / 滨河立交", [360, -540, 70]],
    ["hills", "西岭森林公园", [-1040, 850, terrainHeight(-1040, 850) + 45]],
    ["homes", "南岸生活区", [-250, -990, 75]],
  ])
    labels.push(
      viewer.entities.add({
        id: `city-label:${id}`,
        position: toWorld(position),
        label: {
          text,
          font: "500 14px Microsoft YaHei",
          fillColor: Color.WHITE,
          outlineColor: Color.fromCssColorString("#24392f"),
          outlineWidth: 4,
          style: LabelStyle.FILL_AND_OUTLINE,
          scaleByDistance: new NearFarScalar(300, 1, 6000, 0.65),
          pixelOffset: new Cartesian2(0, -10),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      }),
    );
  let visible = true;
  const enabled = new Set([...primitives.keys(), "labels"]);
  const sync = () => {
    primitives.forEach((primitive, key) => {
      primitive.show = visible && enabled.has(key);
    });
    labels.forEach((entity) => {
      entity.show = visible && enabled.has("labels");
    });
    viewer.scene.requestRender();
  };
  return {
    stats,
    views: CITY_VIEWS,
    setVisible(value) {
      visible = value;
      sync();
    },
    setLayer(key, value) {
      if (value) enabled.add(key);
      else enabled.delete(key);
      sync();
    },
    destroy() {
      primitives.forEach((p) => viewer.scene.primitives.remove(p));
      labels.forEach((e) => viewer.entities.remove(e));
    },
  };
}
