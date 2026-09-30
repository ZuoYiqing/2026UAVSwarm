# 待办：城市导入 Gazebo + 青岚市对齐

建立日期：2026-09-28
状态：**阶段 1 已完成并实测**；阶段 2/3/4 未开始
相关提交：`cbcf565`（城市几何导入）、`b2f0882`（前端 iframe 保活与选择同步）

本文件是为了让这项工作**不依赖对话上下文**也能继续。所有结论都附了来源位置。

---

## 零、阶段 1 已完成（2026-09-28）

| 项 | 结果 |
| --- | --- |
| 生成器支持合并 | `tools/generate-city-world.mjs --block <id> --merge-into <world.sdf>`，**幂等** |
| 校验器 | `tools/validate-city-world.mjs <world.sdf>`，11 项检查全过 |
| 已导入街区 | `block-4-3`（12 栋，高 19~52 m），世界文件 4,351 B → 约 14 KB |
| Gazebo 确认加载 | `gz model --list` 输出含 `city-block-4-3` ✅ |
| 飞行实测 | UAV-01 从原点飞到该街区中心，**偏差 0.53 m**，高度 25.1 m，稳定悬停 2 s ✅ |

### 实测发现的两个运维要点（重要）

1. **goto 的到达超时约 25 秒，飞不完长距离。**
   350 m 的航线在 25 秒内只飞了约 283 m（`arrival_timeout`，`last_error_m=99`）。
   解法：**分段接力**（再发一次同样的 goto 即可续飞），或传入更大的
   `observe_timeout_ms`。实测第二次 goto 走完剩余 67 m 并成功到达。
2. **降落也用同一个观测窗口，长距离返航后降落可能报 `completion=timed_out`。**
   实测：`land_ack=MAV_RESULT_ACCEPTED`、飞机**确实落地**（高度 0、disarm），
   但完成观测超时。**不要把 `timed_out` 直接当作"没降落"**，应同时看遥测。

### 当前位置副作用

飞行验证后 UAV-01 停在 `N=349.5, E=-10.0`（城市街区里），不再在原点起降坪。
重启仿真即可复原（`ops.sh restart`）。

---

## 一、目标

让**物理仿真世界**与**三维视图**描述同一座城市，从而使：

1. 撞墙是真的撞墙（Gazebo 里有碰撞体），不是前端画着一栋楼、后端其实在空地
2. 三维视图在「青岚市」场景下能正常显示载具（当前因 `scene_id` 不匹配被过滤）
3. 后续可以演示「无人机在街道间/楼宇间飞行」

---

## 二、当前状态（已查证，勿重复调查）

### 2.1 两边的世界内容不同

| | 内容 | 来源 |
| --- | --- | --- |
| **Gazebo（物理）** | 只有 1 栋 `6×6×10 m` 的方盒（`building-001`）+ 地面 + 3 个起降坪 + 标记 | `scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf`（4,351 字节） |
| **三维视图（视觉）** | 267 栋建筑、2,605 株乔木、10.08 km² 城市 + 山地 | 前端用 three.js 几何拼出，数据来自 `frontend/swarm-console/simulation-3d/src/city-layout.js` |

**结论：同一个坐标原点，不同的世界内容。** 所以「前端看着要撞墙、后端其实在空地」。

### 2.2 坐标其实是同一套（这一点很重要，别被误导）

- 城市场景由 `main.js` 用 `missionFrame` 放置
- `city-layout.js` 第 1 行明确写着：`All positions stay in the existing mission ENU frame (metres)`
- **Gazebo 世界也是 ENU**（x=东, y=北, z=上）

**所以布局坐标可以直接当作 Gazebo 世界坐标，零换算。**
`scene_ned` 只是同一组轴的另一种命名：`north=y, east=x, down=-z`。

### 2.3 城市布局是确定性的

`city-layout.js` 第 48 行：`seededRandom(seed = 2026)`。
**因此可以让它成为唯一事实来源** —— 同一份数据既画前端、也生成 Gazebo 世界，
前后端必然对齐，不需要人工同步两份几何。

### 2.4 原点附近没有建筑（这是设计，不是 bug）

`city-layout.js` 第 120 行：

```javascript
if (x0 === -280 && y0 === -300) continue; // Existing campus footprint.
```

原点所在的街区被**刻意留空**，对应前端的「测试园区」视图与 Gazebo 里的三台起降点。
实测：**原点 250 m 内 0 栋建筑**，最近的建筑在 300 m 外。

**因此「在楼中间看到无人机」必须飞到相邻街区，或调整这项保留。**

### 2.5 已就绪的生成器（未接入）

`frontend/swarm-console/simulation-3d/tools/generate-city-world.mjs`

```bash
cd D:/2026UAVSwarm/frontend/swarm-console/simulation-3d
node tools/generate-city-world.mjs --list                    # 列出候选街区
node tools/generate-city-world.mjs --block block-4-3 --out <路径>.sdf
```

已实测输出（`block-4-3`）：中心 ENU(-10, 350)，距原点 350 m，**12 栋楼，高 19~52 m**，
楼间通道约 30~60 m，XML 合法、每栋带 `<collision>`、底面贴地。

生成的 SDF 是一个可直接 `<include>` 或合并进现有世界的 model 片段，
坐标与前端 `CITY.layout` 完全一致。

### 2.6 青岚市对齐的真实原因

`frontend/swarm-console/simulation-3d/src/scene-alignment.js` 第 24 行：

```javascript
if (snapshot.sceneId !== scene.scene_id || s.scene_id !== scene.scene_id) return "scene_id 不匹配";
```

- 后端（Runtime/标定）报的 `scene_id` = `simple_recon_v0_1`
- 青岚市场景要求的 `scene_id` = `qinglan_city_v1`（`QINGLAN_SCENE`）

**因此青岚市视图永远无法对齐 → 载具被过滤 → 看不到飞机。**

---

## 三、**关键决策（务必先读）**

> **不要为了让青岚市显示载具而放宽对齐判据。**

`alignmentReason()` 里的 `scene_id` 匹配是在回答「这份坐标是否可信」。
放宽它 = 允许用 A 场景的坐标在 B 场景里画飞机 —— 这是安全判据。

本项目已经因为**放宽安全判据**出过一次事故：
2026-09-28 的 goto 收尾把 `AUTO/RTL` 当成安全悬停，导致动作报 `pass`
而载具实际在自主返航（详见 `_ops/MANUAL_STARTUP.md` 6.12 缺陷二）。

**正确顺序是：先让 Gazebo 世界真的变成青岚市，再把 `scene_id` 改对。**
届时对齐判据一个字都不用改。

---

## 四、待办清单

### 阶段 1：把城市几何导入 Gazebo ✅ 已完成

- [x] 1.1 导入范围：先做 1 个街区（`block-4-3`）。全量 267 栋的碰撞开销**仍未评估**
- [x] 1.2 接入方式：**生成 model 片段合并进现有世界文件**，引用与 `scene_id` 都不用动
      （`three_uav_sitl.json:10` 的 `world_path` 与 `scene.json:107` 的 `gazebo_world`
      都指向 `scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf`）
- [x] 1.3 生成器已纳入版本管理；几何不手工编辑，改 `city-layout.js` 后重跑
- [ ] 1.4 **目视核对**：在 Gazebo 里看导入的楼与三维视图是否一致（需带 GUI 启动）
- [ ] 1.5 评估全量导入（267 栋）的实时性影响，再决定是否扩大

### 阶段 2：让后端声明正确的场景身份 ❌ 未开始


- [ ] 2.1 为新的物理世界确定 `scene_id` / `map_version`
      - 目标：让青岚市视图要求的身份与后端一致
      - 需要改的地方（**先只读确认，再动**）：
        `scenarios/<scene>/scene.json`（`scene_id` / `map_version`）
        + 仿真侧 manifest + 前端 `QINGLAN_SCENE`
      - ⚠️ 标定契约里带着 `scene_id`/`map_version`，改它会**让已发布的标定失效**。
        这本身是期望行为（身份变了旧标定不该继续用），但要为此更新文档与操作流程。
- [ ] 2.2 确认 `axis_alignment`、`origin_continuity` 等其余对齐字段在新身份下仍然成立
- [ ] 2.3 **验证**：切到青岚市场景后载具能显示，且位置与「后端任务坐标」场景一致
      （同一台飞机在两个场景里的实际位置应相同，只是视觉背景不同）

### 阶段 3：端到端验证（需用户在场）

- [ ] 3.1 起飞 → 飞到 `block-4-3` 楼群间 → 悬停 → 降落（用 `goto`，端点已验证）
- [ ] 3.2 **撞墙测试**：故意派往一栋楼，确认被真实阻挡（不是穿模）
      - 这是「物理世界真的有楼」的最终证明
- [ ] 3.3 记录证据到 `_ops/logs/`，并更新 `_ops/MANUAL_STARTUP.md`

### 阶段 4：文档

- [ ] 4.1 更新 `_ops/MANUAL_STARTUP.md`：
      - 新增「城市物理世界」一节：世界文件位置、如何重新生成几何、如何核对前后端一致
      - 更新 7.4 技术债中「青岚市物理场景未导入」一条
- [ ] 4.2 若改了 `scene_id`，同步更新标定相关说明与迁移清单

---

## 五、已知风险与注意事项

1. **碰撞计算量**：267 栋楼的静态碰撞体可能显著影响 Gazebo 实时性。
   先小规模导入并测量，再决定是否全量。**不要一次性全量导入后才发现跑不动。**
2. **不要放宽对齐判据**（见第三节）。
3. **改 `scene_id` 会让已发布的标定失效** —— 这是对的，但要按流程走并通知使用者。
4. **生成器是唯一事实来源**：几何不一致时改生成器重跑，不要手改 SDF。
5. **前端 `city-layout.js` 与 `CITY.bounds`**（`[-1800, -1400, 1800, 1400]`，单位米）
   是坐标真值；任何导入都应与它对账。

---

## 六、相关文件与命令索引

| 用途 | 位置 |
| --- | --- |
| 城市布局（坐标真值） | `frontend/swarm-console/simulation-3d/src/city-layout.js` |
| 城市几何构建 | `frontend/swarm-console/simulation-3d/src/city-geometry.js` |
| 三维视图场景放置 | `frontend/swarm-console/simulation-3d/src/main.js`（`missionFrame`） |
| 对齐判据 | `frontend/swarm-console/simulation-3d/src/scene-alignment.js` |
| 场景定义 | `frontend/swarm-console/simulation-3d/src/main.js` 的 `sceneDefinitions` |
| 现有 Gazebo 世界 | `scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf` |
| 世界生成器 | `frontend/swarm-console/simulation-3d/tools/generate-city-world.mjs` |
| 密度勘察脚本 | `.../tests/city-density-probe.mjs`、`.../tests/city-block-probe.mjs` |
| goto 使用与已知缺陷 | `_ops/MANUAL_STARTUP.md` 6.12 |
| 操作手册 | `_ops/MANUAL_STARTUP.md` |

### 复现当前状态的命令

```bash
# 城市建筑密度（结论：原点 250 m 内无建筑）
cd D:/2026UAVSwarm/frontend/swarm-console/simulation-3d
node tests/city-density-probe.mjs

# 候选街区（结论：block-4-3 最合适）
node tests/city-block-probe.mjs

# 生成街区几何
node tools/generate-city-world.mjs --block block-4-3 --out /tmp/city-block-4-3.sdf
```
