# 简易巡检场景实体目录

[实体目录](entity_catalog.json) 对应 `simple_recon_v0_1 / simple_recon_v0_1-map-1`。
`catalog` 沿用识别器合成夹具的条目形状 `entity_id / label / aliases / exclusive_group`。
仿真侧提供稳定 ID 和 `geometry_by_entity_id`，由算法侧填入可供识别的名称、别名与互斥组。
本版已审核七个演示条目的语义。其余条目保留空字段，暂不供识别器绑定。
车辆 ID 不作为场景实体 ID。

坐标为公共 `scene_ned`，单位米，分量为北、东、下。实际模型来自
[SDF 世界](worlds/simple_recon_v0_1.sdf)，声明的任务、覆盖和禁飞区域来自
[场景文件](scene.json)。12 栋导入建筑沿用其 SDF link 名，楼群范围覆盖建筑外缘。
禁飞区是策略区域，起降坪及目标是视觉标记，地面和楼体有各自的碰撞几何。

| 演示目的 | 建议使用的实体 ID | 几何来源 |
| --- | --- | --- |
| 同任务类型换目标 | `demo-area-001`、`target-001` | 西侧青色地面边框、已有绿色目标标记 |
| 同名追问 | `demo-anchor-001`、`demo-anchor-002` | 蓝色 001、橙色 002，公共位置分别为 `(4,-15,0)`、`(4,16,0)` |
| 冲突追问 | `demo-sector-001`、`demo-sector-002` | 南侧同色系的两块紫色边框，共用 `demo-sector-single-choice` 互斥组 |
| 只用于定位 | `building-001` | 已有实体建筑，中心为 `(15,0,-5)` |

五个演示槽位均有对应的 Gazebo 视觉模型，`source` 为 `gazebo_visual`。
它们沿用原目录的点位和边界。三维参考场景从目录的 `display` 读取颜色和编号。
Gazebo 的边框和编号柱均为无碰撞视觉物体，高度仅用于渲染。圆盘与飞行用几何保持原样。
机载前视相机需在能覆盖对应地物的航向和取景位置观测。Gazebo 模型的编号牌朝上，
数字顶端朝北，便于从南侧飞行视角查看。标记不会产生航点或执行授权。

`recon-area-001` 是围绕 `target-001` 的任务范围。两者同心于 `(30,15,0)`，
任务区半径 8 m，绿色可视标记半径 3 m。它们有不同的 ID 和角色，不能从这两个 ID
推导出两个独立的巡检目标。

这次只新增视觉物体，公共坐标、碰撞几何和 `map_version` 保持原值。
SDF 内容摘要必须使用当次启动的版本，旧的观察证据仍绑定其历史世界。

## Runtime 意图预览

`entity_catalog.json` 是仿真与算法共用的维护源。场景中的 `intent_catalog` 使用
契约版本 `1.0`，包含 `scene_id`、`map_version`、`catalog_id`、`entries` 和两份角色清单。
七条已审核的 `entries` 各保留 `entity_id`、`label`、`aliases`、`exclusive_group`。
Runtime 从所加载的 `scene.json` 读取这些字段。完整几何、来源和显示信息保存在独立目录。

- `scene.targets` 中的 `target-001` 保留物理目标资格。
- `preview_only_entity_ids` 中的五个演示实体可出现在只读计划的 `preview_only_targets` 绑定里。
- `reference_only_entity_ids` 中的 `building-001` 可用于定位或排除。把它列为正向目标时，
  Runtime 应返回 `TARGET_REFERENCE_ONLY` 并等待澄清。

更新维护源后，执行以下命令刷新场景中的语义目录。校验可作为提交前检查。

```powershell
python -B scenarios/simple_recon_v0_1/sync_intent_catalog.py --write
python -B scenarios/simple_recon_v0_1/sync_intent_catalog.py
```

互斥台词使用「巡检西南和东南」。后置动词「西南和东南都巡检」待识别器支持。
