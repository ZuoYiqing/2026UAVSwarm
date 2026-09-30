# 给 Algorithm Lab 的下一轮任务说明

**来源**：Integration Owner（Runtime / 前端 / 仿真侧）
**日期**：2026-09-29
**对应 Runtime 提交**：`3209d99`
**上一轮我方文档**：`docs/algorithm_side_next_steps_20260929.md`
**你们上一轮交付**：`b0796b4`（`algorithm_lab/mission_llm_poc`）

---

## 0. 先说结论：你们上一轮的交付我方已核对通过

我**没有采信自述**，而是逐项实测复现（脚本：`_ops/verify-algorithm-handoff.py`、
`_ops/verify-grounder-rejections.py`）：

| 核对项 | 结果 |
| --- | --- |
| 真实转换器展开 `simple_recon_flight_handoff.json` | ✅ 3 步：`takeoff(3 m)` → `goto(N=60, E=12, D=-20)` → `land`，均在 UAV-01 |
| 场景身份 `simple_recon_v0_1` / `simple_recon_v0_1-map-1` | ✅ 与本机活动场景**一致** |
| 过 Runtime 请求体校验 | ✅ 3 个 step 通过 |
| 不过度声称（`execution_authorized` / `execution_ready`） | ✅ 均为 `false` |
| 输入**确实不含** `tasks[]`，只有 `objective` + `regions[]` | ✅ 已核对文件内容 |
| 你们的单元测试 | ✅ **29/29**（我实跑复现） |
| 转换器合约测试 | ✅ **15/15**（我实跑复现） |
| grounder 拒绝行为（7 个场景：外部 tasks／未知区域／指代不明／含否定／巡检／缺 regions） | ✅ **7/7 与自述一致** |
| 模型服务确实已停止 | ✅ 18080 空闲、无相关进程 |

**多机时序的三条答复我方接受**，尤其第三条第 3 点——

> 当前 Runtime 依次执行 step，不能把三机分配结果写成"三机协同飞行已验证"。

**主动否定自己结论的强度，比夸大它更有用。** 我方在文档与审计里也按这个口径表述。

### 一处我方自己搞错的地方，记录在案

我第一版验证脚本把"混入巡检意图"判为你们的缺陷（退出码 0，我以为该拒绝）。
深查后确认**是我方用例错了**：grounder 把它正确归类为 `intent_type=reconnaissance`
且 `assignments` 为 **0 项**，即**没有把巡检伪装成飞行验证**——这恰好是正确的行为。
判据已修正为"不得当作飞行验证通过"。

---

## 1. 你们要的场景可供性清单：已交付

你们在 `INTENT_GROUNDING_HANDOFF_20260929.md:33` 请求：

> `scene.json` 尚缺已导入 Gazebo 的 12 栋楼；当前不能把它当完整障碍物真值。
> 若需在自然语言里指代"楼群东侧"等地点，请集成侧提供带来源和版本的场景可供性清单。

**交付物**：`docs/fixtures/simple_recon_v0_1_scene_affordances.json`

### 内容

| 段 | 说明 |
| --- | --- |
| `scene_identity` | `scene_id` / `map_version` / 原点 / 坐标轴约定 |
| `coordinate_note` | **ENU→scene_ned 的换算规则**（世界文件是 ENU，`north_m = y, east_m = x, down_m = -z`） |
| `obstacles` | **12 栋楼的完整参数**：中心坐标、尺寸、高度、`base_down_m` / `top_down_m`、距原点距离、方位 |
| `obstacle_cluster` | 楼群整体：中心、范围、高度区间、最小净距、布局（4 列 × 3 行） |
| `declared_scene_entities` | `scene.json` 现有的障碍物／禁飞区／任务区／目标 |
| `infrastructure` | 起降坪与三台出生点 |
| `coverage` | **明确列出清单里没有什么** |

### 三个必须注意的点

**① 数据来源是物理真值。** 坐标从世界文件读出——那是 Gazebo 实际加载的那一份。
前端 `city-layout.js` 只是同一布局的视觉呈现，不一致时**以世界文件为准**。

**② 覆盖范围（这条直接回应你们的顾虑）：**

- 这 12 栋楼是**已经带碰撞体导入** Gazebo 的，可以用作障碍物判断
- 前端 `city-layout.js` 的**其余 255 栋楼视觉存在但物理未导入** —— 不能当障碍物
- `qinglan_city_v1` 的任何几何也未导入
- 地面是 2000×2000 m 平面（±1000 m），**之外没有地面**；地形处处为 0 m，无起伏

**③ 我方刻意不提供人工语义标签。** 文件里 `semantic_labels.provided` 为空。
理由是：**凭空命名会让你们把假设当已知**。清单只给可核查的事实与**由坐标直接推导**
的方位词。若你们需要"作业区甲"这类命名，须由负责方给出并标明来源与版本——
**请提出你们需要哪些命名，我方转交负责方。**

**方位词的使用限制（重要）**：推导规则是"某分量绝对值 ≥ 另一分量 × 0.25 才写方位词"，
即**偏角小于约 14° 时只报主方向**。楼群中心 `north=350.0 / east=-10.0`（偏西 1.6°）
判读为「北」，**该判读掩盖了那 10 m 偏移**。
**需要精确方位时请直接读 `center_north_m` / `center_east_m`，不要只依赖方位词。**

---

## 2. 你们的 objective 目前仍会被拒 —— 这是本轮的起点

我实测了三个 objective：

| objective | 结果 |
| --- | --- |
| `对 verified-flight-route-001 起飞、飞过去观察目标、再返回降落。` | ❌ `OBJECTIVE_INTENT_AMBIGUOUS` |
| `对 verified-flight-route-001 做巡检：起飞、前往观察、返回、降落。` | ⚠️ 通过但 `intent_type=reconnaissance`、**`assignments` 为 0** |
| `对 verified-flight-route-001 做飞行验证：起飞、前往已验证航点、降落。` | ✅ `flight_validation`，1 项分配 |

**也就是说：只有"飞行验证"这一类 objective 能产出可执行计划。**
任何含感知意图的目标——包括你们的核心研究内容——目前都产出 0 项分配，
或直接被拒。

**这就是"真正的智能算法尚未开始"在接口上的具体表现。** 下一步应从这里推进。

---

## 3. 本轮请你们做的事

### 3.1 用新的可供性清单，把"楼群"这类指代绑定起来（主任务）

现在有 `docs/fixtures/simple_recon_v0_1_scene_affordances.json`，
请让 `objective` 里的自然语言指代能绑到**上面这 12 栋楼及其方位**。

**具体要求**：

- 输入仍**不含** `tasks[]`（这条已冻结，继续保持）
- 输入新增该可供性清单（或它的子集），作为"供应方给出的标签来源"
- 目标示例（请自行设计更丰富的用例）："飞到北边那片楼群的东侧"、
  "绕楼群一圈"、"到最高的那栋楼旁边"
- **必须能说明**：指代是如何绑到具体实体 ID 与坐标的（沿用你们现在的
  `matched_text` / `target_id` / `source_reference` 记录方式即可）
- **指代无法确定绑定时应当拒绝**，不要猜一个近似的楼

**请特别注意**：清单里的方位词受第 1 节第③点的限制（偏角 <14° 只报主方向）。
如果你们的绑定依赖方位词，**必须同时读坐标**，否则会把"北偏西 10 m"当成"正北"。

### 3.2 感知类 objective 的处理口径

你们目前对含感知的意图产出 `assignments=0`。**这个行为我认可**（不伪装成飞验），
但请明确并写下来：

- 产出 0 项分配时，调用方（我方或人工）应当**如何区分**
  "目标是巡检、确实无动作可分" 与 "解析失败、什么都没想到"？
- 建议给出**明确的拒绝原因码**，而不是两种情况下都返回"通过但 0 项"

### 3.3 能力语义仍是空的（我方已上报定责，未定）

你们 P0 的"载具能力语义"我方**没有**，且已写成待定责文件交总体集成负责人：
`docs/OPEN_vehicle_capability_semantics_ownership.md`

**有一项进展对你们可能有用**（我方实测，可核查）：

```
我们配置的 gz_x500  →  x500/model.sdf 仅 <uri>model://x500_base</uri>
x500_base 的传感器  →  air_pressure / magnetometer / imu / navsat（无相机）
但同一 PX4 checkout 另有 x500_mono_cam / x500_depth / x500_gimbal / LiDAR 等变体
```

**所以"仿真里没有成像能力"是模型选型的结果，不是仿真做不到。**
若你们的感知算法需要成像数据，**请明确提出需求**（要什么、精度要求、用于什么判断），
我方评估换用带相机的仿真变体。
**但请注意**：换变体属仿真配置决定，且**仿真能成像不等于真机能成像**——
真机能力仍待机型负责人确认。

### 3.4 权威规则的一个具体问题

你们的 `grounding.authority = objective`，且已实现"外部 `tasks[]` 同存即拒绝"
（`EXTERNAL_TASKS_FORBIDDEN`）。我方认可。

**但请明确冲突处理的操作细节**：当 `objective` 与人工提供的结构化意图冲突时，
你们期望调用方怎么做？当前是"拒绝并要求澄清"——**澄清的通道是什么？**
（我方需要知道该把澄清请求呈现给谁、以什么形式。）

---

## 4. 版本落差提醒（重要）

你们的工作树检出于 `6116912`（2026-09-18），
**落后 main 37 个提交**，其中动了你们关心的文件的有：

| 文件 | 落后提交数 |
| --- | --- |
| `docs/algorithm_runtime_execution_contract_v0_1.md` | 3 |
| `tools/proposal-to-plan.mjs`（转换器） | 2 |
| `scenarios/.../simple_recon_v0_1.sdf`（城市几何） | 2 |

**你们的工作树里没有转换器、没有执行契约文档、世界文件还是旧版**
（旧版地面只有 100×100 m，且不含那 12 栋楼）。

我核对过：**这 37 个提交没有动 `algorithm_lab/` 下任何文件**，
所以合并**不会有冲突**。我方建议把 main 合并进你们的分支，
使工作树与主仓库一致。**是否合并请你们确认**（那是你们的分支）。

---

## 5. 验收方式（我方会怎么做）

1. 用**你们的**新 objective 与可供性清单，跑你们的 grounder，检查绑定记录
2. 用**真实转换器**展开你们产出的 proposal（不是复刻逻辑）
3. 过 Runtime 请求体校验与场景身份核对
4. 检查是否越界声称（`execution_authorized` / `execution_ready` / 完成证据）
5. **在你们确认可以真飞之前，我方只做转换与校验，不提交执行请求**

---

## 6. 不要做的事（延续你们已有的承诺，新增两条）

1. 不要为提高通过率而放宽校验或跳过检查
2. 不要把"提案字段一致"当作实时场景匹配证据（Runtime 在执行前会再核对）
3. 不要从 `constraints.min_altitude_m` 推断起飞高度
4. 不要把 `OBSERVE` / `RETURN_HOME` 静默丢弃后提交剩余子集
5. **不要把方位词当作精确方位**——偏角 <14° 只报主方向（见第 1 节）
6. **不要在没有来源的情况下给场景实体起名**——命名须由负责方给出并签字

---

## 7. 相关文件索引

| 用途 | 位置 |
| --- | --- |
| **场景可供性清单（本轮新增交付）** | `docs/fixtures/simple_recon_v0_1_scene_affordances.json` |
| 执行契约 | `docs/algorithm_runtime_execution_contract_v0_1.md` |
| 能力语义定责（待总体集成负责人裁定） | `docs/OPEN_vehicle_capability_semantics_ownership.md` |
| 上一轮我方任务说明 | `docs/algorithm_side_next_steps_20260929.md` |
| 转换器 | `frontend/swarm-console/simulation-3d/tools/proposal-to-plan.mjs` |
| 城市世界现状与待办 | `docs/TODO_city_world_import.md` |
| 你们上一轮的交接 | `algorithm_lab/mission_llm_poc/docs/INTENT_GROUNDING_HANDOFF_20260929.md` |
