# 给 Algorithm Lab 的任务说明与数据交接

**来源**：Integration Owner（Runtime / 前端 / 仿真侧）
**日期**：2026-09-29
**对应 Runtime 提交**：`ca57eda`
**依据**：`algorithm_lab/INTELLIGENCE_HANDOFF/01_runtime_interface_requirements.md`、
`algorithm_lab/mission_llm_poc/docs/RUNTIME_EXECUTION_HANDOFF_20260928.md`

---

## 0. 先纠正一处我方此前的误解（记录在案）

我方一度把"三机巡检"当作你们的任务范围，并据此认为 `OBSERVE` 端点的缺失是主要阻塞。

**读了你们的 `01_runtime_interface_requirements.md` 后确认这是我方理解错误。** 该文件写明：

> 当前 `mission_llm_poc` 的实现是"闭环验证脚手架"（greedy 分配 + 严格校验器），
> 不是算法成果。它的价值在于冻结 I/O 契约、可复现、可审计。**真正的智能算法尚未开始。**

巡检只是 5 个合成样例之一。你们真正的核心诉求是第 1 节的**语义倒置**问题：
自然语言目标才是权威意图来源，结构化任务清单应当由它派生。**本文件按这个理解撰写。**

---

## 1. 场景选择：请面向 `simple_recon_v0_1`

**本机（目标机）当前运行的是 `simple_recon_v0_1`**，因此请以它为准：

| 项 | 值 |
| --- | --- |
| `scene_id` | `simple_recon_v0_1` |
| `map_version` | `simple_recon_v0_1-map-1` |
| 坐标框架 | 公开框架 `scene_ned`（`north_m` / `east_m` / `down_m`，down 向下为正） |
| 场景原点 | Gazebo 世界 ENU 原点 = 三台飞机的起降点（`north=0, east=0`） |
| 世界坐标锚点 | 47.3979709 N, 8.5461639 E, 0 m |

### 为什么不是 `qinglan_city_v1`

前端另有一套"青岚市"视觉场景（`scene_id = qinglan_city_v1`），但：

- 它的物理世界**尚未导入 Gazebo**（`task-area-export.js` 里 `physics_status: "not_imported"`）
- 它的交接文件自带说明：*"Not a calibrated transform to simple_recon_v0_1.
  Simulation must review takeoff protection, build collision assets and publish a
  new scene/map calibration before LIVE alignment."*

**所以：青岚市目前只是视觉展示，不能作为飞行依据。** 面向它产出的提案在本机提交会被
`scene_id_mismatch` 拒绝（这是校验按设计工作）。

---

## 2. Runtime 侧的现状（你们需要知道的接口前提）

### 2.1 已实现

| 项 | 状态 |
| --- | --- |
| **场景身份校验** | ✅ 已实现（`b12d037`）。`plan.scene_id` / `plan.map_version` 为**必填**，与 Runtime 实际加载的场景核对；不一致返回 `scene_id_mismatch` / `map_version_mismatch` / `scene_identity_unavailable`，**在任何一步起飞前拒绝整份计划** |
| **proposal → plan 转换器** | ✅ 已实现：`frontend/swarm-console/simulation-3d/tools/proposal-to-plan.mjs`（JS 模块，可直接 import） |
| **可执行动作** | `takeoff` / `goto` / `land`（+ `smoke_takeoff` 测试用） |
| **端到端闭环** | ✅ 已真飞验证：转换器产出 3 步 → Runtime `completed` → UAV-01 落在 `N=59.2 E=12.0`（目标 60/12，误差 0.8 m） |

### 2.2 转换器的拒绝语义（与你们的要求一致）

- 只展开 `TAKEOFF` / `GOTO` / `LAND`
- **任一不支持动作、缺失航点、缺失目标载具 → 拒绝整份提案**，并指出具体 task / action / waypoint
- **不静默跳过，不提交可执行子集**
- **`takeoffAltitudeM` 必须显式传入**，不从 `constraints.min_altitude_m` 推断
- 已用你们的真实样例验证：`flight_validation_only.json` 展开为 9 步；
  `base_context.json`（巡检样例）**整份拒绝**并同时指出 `OBSERVE` 与 `RETURN_HOME`

### 2.3 尚未实现

| 项 | 说明 |
| --- | --- |
| `OBSERVE` / `RETURN_HOME` / `HOLD` 端点 | 未实现。注册表已声明，但无执行端点 |
| 感知载荷接口定义 | **完全没有**（拍什么、存哪、如何判定"观察到"均未定义） |
| 多机协同时序接口 | **完全没有**（见第 5 节） |
| "场景可供性"数据接口 | **没有**（见第 3 节，这是你们 P0 的主要缺口） |

---

## 3. 你们 P0 数据需求的现状（**如实说明，包括没有的部分**）

你们在 `01_runtime_interface_requirements.md` 第 2 节列了三项 P0。逐项核对如下。

### P0-1 场景实体清单 —— ⚠️ **存在但不完整**

本机 `scenarios/simple_recon_v0_1/scene.json` 已有以下内容（**这是当前全部**）：

| 类别 | 内容 |
| --- | --- |
| `obstacles` | `building-001`：长方体，中心 `north=15, east=0`，尺寸 6×6×10 m |
| `no_fly_zones` | `nfz-001`：圆柱，中心 `north=10, east=10`，半径 5 m，高度 0~20 m |
| `mission_areas` | `recon-area-001`：圆，中心 `north=30, east=15`，半径 8 m |
| `targets` | `target-001`：`north=30, east=15`，半径 3 m，描述 "static recon target" |

**⚠️ 但它不完整。** 我方于 2026-09-28 向 Gazebo 导入了 `block-4-3` 城市街区
（12 栋楼，带碰撞体），**这批建筑尚未写进 `scene.json`**。以下是从世界文件
（物理真值）导出的清单，可直接使用：

**城市街区 `city-block-4-3`**（规整 4×3 网格，共 12 栋）

| 列（east_m） | 行（north_m） | 宽(东西) m | 深(南北) m | 高 m | 顶面 z m |
| --- | --- | --- | --- | --- | --- |
| -199.8 | 268.0 | 67.6 | 48.9 | 20 | 20 |
| -73.2 | 268.0 | 70.2 | 50.7 | 23 | 23 |
| 53.2 | 268.0 | 80.4 | 38.6 | 32 | 32 |
| 179.8 | 268.0 | 68.4 | 41.5 | 22 | 22 |
| -199.8 | 350.0 | 80.0 | 40.7 | 19 | 19 |
| -73.2 | 350.0 | 60.9 | 41.1 | 41 | 41 |
| 53.2 | 350.0 | 72.9 | 50.4 | **52** | 52 |
| 179.8 | 350.0 | 83.4 | 39.8 | 24 | 24 |
| -199.8 | 432.0 | 62.8 | 46.7 | 38 | 38 |
| -73.2 | 432.0 | 64.5 | 37.9 | 36 | 36 |
| 53.2 | 432.0 | 75.8 | 49.3 | 36 | 36 |
| 179.8 | 432.0 | 79.2 | 49.0 | **52** | 52 |

- 东西范围 `-199.8 ~ 179.8 m`，南北范围 `268.0 ~ 432.0 m`
- 街区中心 `east=-10, north=350`，距原点 **350 m**
- **最小东西向净距 48.4 m**（`2-1 ↔ 3-1` 之间）——可飞入的通道
- 每栋都带 `<collision>`，物理上会真实阻挡

**⚠️ 原点附近 250 m 内没有建筑**（`city-layout.js` 刻意保留了"测试园区"，
起降坪与 `building-001` 都在该空区内）。所以"在楼群中飞行"必须飞到 350 m 外的街区。

**⚠️ 我方未提供的东西**：区域的自然语言描述。当前只有 ID 与一句英文标签
（如 "static recon target"）。**我们确实没有"山谷东侧""上次失联那片区域"这类语义标注。**

### P0-2 载具能力语义 —— ❌ **缺失**

**如实说明：本机没有这项数据。**

`simulation/px4_gazebo/config/three_uav_sitl.json` 里每台飞机只有：

```
node_id / px4_instance / system_id / component_id / gazebo_model_name /
command_endpoint / telemetry_endpoint / px4_mavlink_local_port /
gcs_local_port / spawn_ned / runtime_dir
```

**没有**：续航、电池容量、最大速度、速度包线、传感器、相机、视场、分辨率、载荷。

唯一的机型信息是 `"px4_sim_model": "gz_x500"`（PX4 标准多旋翼 SITL 模型）
与 `"airframe_autostart": 4001`。三台**完全相同**。

`docs/hardware_capability_mapping_template.md` 是一份**空模板**（所有字段为 `TBD`），
不是已填写的清点。

**因此：你们目前无法区分"能拍"与"拍得清"——这项数据我方提供不了，
需要真机参数或明确的仿真假设。** 如果你们能接受"三台同型、能力等同"的假定并在
提案里显式标注该假定，我们可以在此基础上推进；**但请不要把假定当已知参数使用。**

### P0-3 任务/区域的语义描述 —— ❌ **基本缺失**

见 P0-1 末尾。只有 ID、几何、一句标签。**没有自然语言描述，也没有
"语义 → `region_id` / `waypoint_ids`"的映射数据。**

**这项的决定权在你们**：如果语义锚定是算法侧的核心职能（按你们文档的理解，
它确实是），那么映射应当由你们从 `objective` 生成，我方提供的是**可供性数据**
（有哪些实体、在哪、什么属性），而不是替你做好映射。

### 附带：一份可参考的清单格式

`frontend/swarm-console/simulation-3d/docs/samples/qinglan-campus-task-area.proposal.json`
（由 `src/task-area-export.js` 生成）展示了**规划端 → 仿真端的交接格式**，
含 `objects` / `roads` / `takeoff_candidates` / `inspection_candidates` /
`no_fly_candidates` / `coverage.omitted` / `handoff` 等字段。

**它的结构值得参考，但请注意三点**：

1. 它的 `scene_id` 是 `qinglan_city_v1`，**与本机不一致**
2. 它的 `physics_status` 是 `not_imported`（那些楼只在浏览器里画着）
3. 它的 `handoff.accepted` 是 `false`

**如果你们需要这个格式的 `simple_recon_v0_1` 版本**（即把上表 12 栋楼
+ `scene.json` 现有实体整理成同结构），请告知，我方可以产出。

---

## 4. 本轮的交付要求（**两件事**）

### 4.1 从自然语言目标生成任务清单（你们文档第 1 节的核心诉求）

这是本轮的重点。当前契约把 `tasks[]` 当权威输入、`objective` 当"不可信的附加数据"，
你们要求把这个关系倒过来。

**本轮请给出一个可运行的最小实现**：

- 输入：`objective`（自然语言）+ 集群快照 + 场景可供性数据
- 输出：`tasks[]`（含 `required_actions`、`waypoint_ids`、`region_id`）
- **`tasks[]` 由算法生成，不作为输入提供**
- 必须能说明：自然语言中的指代（区域、目标、顺序）是如何绑到具体 ID 的

**并请明确回答**（这是你们文档第 4 节问我们的，我方也反过来需要你们的立场）：

- 当 `objective` 与外部给定的 `tasks[]` 冲突时，谁权威？拒绝、请求澄清，还是以
  `objective` 为准并标记？

### 4.2 产出一份"本机可执行的提案"

用于打通集成闭环。要求：

| 项 | 要求 |
| --- | --- |
| `scene_id` | `simple_recon_v0_1` |
| `map_version` | `simple_recon_v0_1-map-1` |
| 动作 | **只含 `TAKEOFF` / `GOTO` / `LAND`** |
| 航点 | 放在上表真实存在的坐标附近；**不要发明航点** |
| 起飞高度 | 明确给出，不从 `constraints.min_altitude_m` 推断 |
| 目标载具 | 每项 assignment 必须带 `node_id` |
| `execution_authorized` | 恒为 `false` |

**建议航线**（一条安全的、可验证的）：

- 起飞到 3 m
- `goto` 到 `north=60, east=12, down=-20`（20 m 高，绕开 `building-001`）
- 降落

> 注：`goto` 的到达观测窗口约 **25 秒**，350 m 的街区一次飞不到（会 `arrival_timeout`）。
> 要么分段接力（再发一次同样的 goto 续飞），要么把目标设在 100 m 内。

### 4.3 自测方法（不必等我们）

```bash
# 转换器：proposal + context -> plan（拒绝时给出具体 task/action/waypoint）
node --input-type=module -e "
  import { proposalToPlan } from 'D:/2026UAVSwarm/frontend/swarm-console/simulation-3d/tools/proposal-to-plan.mjs';
  // ... 你的 proposal 与 context
"
```

转换器的契约测试在
`frontend/swarm-console/simulation-3d/tests/proposal-to-plan.test.js`，
其中包含用你们真实样例驱动的用例，可作为行为参照。

---

## 5. 多机协同时序接口（**目前完全没有，需要双方定义**）

你们指出：`assignments[]` 没有时间调度语义，数组顺序不构成协同时序。**我方确认这是事实。**

当前状态：

- Runtime 的 `/api/plans/execute` 按 **step 数组顺序串行执行**，**失败即中止整份计划**
  （operator 决定，2026-09-28）
- 转换器按 `assignments` 顺序把各机步骤依次排列
- **没有任何并发、时间窗、间隔保证**

**为避免双方各自假设，请你们明确**：

1. 提案里是否需要表达"时间"？如果需要，用什么字段、什么语义（相对时刻？时间窗？顺序约束？）
2. 谁负责可行性判定？按你们第 3 节的承诺，几何与调度归规划侧——那么**算法只表达意图，
   规划侧负责排程**，对吗？
3. 在时序接口定义出来之前，**多机提案是否只应表达"每机各自的动作序列"、
   明确声明"不构成协同保证"**？

---

## 6. Runtime 侧对你们第 4 节四个问题的答复

| 你们的问题 | 我方答复 |
| --- | --- |
| **权威来源**：`objective` 与 `tasks[]` 并存时谁权威？ | **我方支持转向"`objective` 权威、`tasks[]` 为派生结果"**。过渡期建议：提案里显式带 `authority` 字段声明本轮以谁为准；冲突时**拒绝并要求澄清**，而不是让模型自行判断。变更窗口：现在就可以开始，Runtime 侧不阻塞 |
| **数据供给**：P0 字段由 Runtime 提供还是算法侧推导？ | 分三种情况：**① 场景实体清单**——我方提供（本轮已给出 12 栋楼 + 现有实体）；**② 载具能力语义**——我方**没有**，需要真机参数或显式仿真假设；**③ 语义锚定映射**——按你们第 3 节的职能划分，这是算法侧的核心职能，我方提供可供性数据，不代为映射 |
| **职责确认**：第 0 节表格的归属划分是否一致？ | **完全一致**，无遗漏或重叠。特别确认：几何/避障/间距/调度**不归算法侧**，由规划/调度负责；算法输出必须能被其否决 |
| **接入方式**：提案进入主线的路径？ | 当前：**转换器（已实现）+ 人工审批 + `/api/plans/execute`**。转换器在拒绝时给出具体的 task/action/waypoint 与原因码。快照过期后的重新验证：**由 Runtime 负责**（每次执行前检查标定与场景身份），算法侧不必重复实现 |

---

## 7. 不要做的事（延续你们的承诺）

1. 不要为提高通过率而放宽校验或跳过检查
2. 不要把"提案字段一致"当作实时场景匹配证据（需 Runtime 在**执行前**与活动场景核对，
   这已实现）
3. 不要从 `constraints.min_altitude_m` 推断起飞高度
4. 不要把 `OBSERVE` / `RETURN_HOME` 静默丢弃后提交剩余子集
5. 不要在提案里使用我方标记为"没有"的数据（如载具续航）而不显式标注为假设
6. 不要把候选点（`*_candidates`）当作已确认的可用位置

---

## 8. 交付物与验收

**请交付**：

1. 从 `objective` 生成 `tasks[]` 的最小可运行实现 + 说明（4.1）
2. 一份面向 `simple_recon_v0_1` 的提案 JSON（4.2）
3. 对第 5 节三个问题的明确答复

**我方验收方式**：

- 用你们的提案走**真实转换器**，检查 `proposalToPlan` 的接受/拒绝行为与原因码
- 通过后提交 `/api/plans/execute`（**在你们确认允许真飞之前，我方只做转换与校验，不提交**）
- 结果（含 `step_outcomes` 与完成证据）回传给你们

---

**联系**：Integration Owner。相关文件：
`docs/algorithm_runtime_execution_contract_v0_1.md`（执行契约）、
`docs/TODO_city_world_import.md`（城市世界现状）。
