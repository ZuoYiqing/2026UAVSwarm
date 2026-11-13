# 给三位负责人的任务书 · 演示能力提升

**日期**：2026-11-12
**背景**：weier 离线环境已跑通（Gazebo 8.15.0 + PX4 SITL 三机 + Runtime + 主控台 + 三维态势），
三架无人机在前端已有真实遥测。
**现在的问题**：**系统能做很多事，但演示时看不出来。**
**这次的目标**：不改控制面协议，把已有能力接上舞台，并补齐"降级场景"这一条主线。

---

# 〇、读之前：一句话说清这次要什么

现在的演示是"**逐个点开 15 个模块看指标**"，
要变成"**一条 3 分钟的故事线自己演完**"。

具体故事线（后续再细化，但方向定了）：

> 三机执行区域侦察 → **通信质量下降** → 系统自己检测到 → 策略闸门自主降级处置
> → 任务重新分配 → 部分完成但全员安全 → 全过程可回溯

**这条链跑通，一个功能顶十个模块。**

---

# 一、给【前端 / 主控台】负责人的任务书

## 1.1 现状（你可以先自己看）

- 左侧 15 个模块：总览驾驶舱 / 任务规划 / 三维集群态势 / 单机详情 / Agent Runtime /
  Policy Gate / Skills 能力库 / Adapter·Backend / 仿真中心 / 观察复核 / 澄清待办 /
  硬件资产 / Audit·Replay / 模型与知识 / 系统设置
- 首屏（总览驾驶舱）是「指标卡 + 一块空画布 + 事件流」
- 「实时集群状态预览」目前只在后端起来后显示几个图标，**没有信息量**
- 后端 26 个接口，前端接了 18 个（**覆盖 65%**），见本文件附录 A

## 1.2 目标（按这个判断做对了没有）

**观众在 30 秒内要能说出三句话**：
1. "这是个管无人机集群的系统"
2. "它在管，不是遥控"
3. "它出问题时自己能处置"

## 1.3 任务清单

### F1 ★★★ 首屏重构：从「指标墙」改成「任务态势」

**要做什么**
- 顶部保留一行**关键指标条**（在线节点数 / 执行中动作 / 最近拒绝 / Runtime API 状态 / 数据源状态）
  —— 这几项信息密度高，**保留**，但压缩成一条，不要占 1/4 屏
- 主区域换成**任务态势**：
  - 一块**任务地图**（俯视，显示侦察区域、已覆盖/未覆盖、三架飞机的任务归属与进度）
  - 一条**主时间轴**（见 F2）
  - 一个**任务完成度大数字**（见 F3）

**关于"任务地图会不会和三维重复"——不会重，分工不同**

| 视图 | 视角 | 回答什么问题 |
|---|---|---|
| **任务地图**（新增，首屏） | 俯视、抽象、符号化 | **任务做到哪一步了？谁负责哪块？哪里没覆盖？** |
| **三维态势**（已有，5179） | 斜视/第一人称、真实几何 | **现场长什么样？飞机姿态如何？** |

**同一个任务的两个切面。** 地图看"任务"，三维看"实体"。**两个都要，不合并。**

**验收**
- 首屏首屏不再出现大面积空白
- 不点任何东西，就能看出"任务在跑、进度在涨"

---

### F2 ★★★ 主时间轴（这是投入产出比最高的一条）

**要做什么**
- 把下面这些事件**按时间排成一条轴**，颜色区分：
  - 绿：`policy_decision = allow`
  - 红：`policy_decision = deny`
  - 黄：**降级 / 健康告警**
  - 蓝：**恢复**
  - 灰：`action_result`
- 每个节点可点，点开显示完整 `policy_decision_event` / `adapter` / `action_result`
- 数据来源（都有现成接口）：
  - `GET /api/events?n=50`
  - `GET /api/policy/decisions?n=20`
  - `GET /api/actions/lifecycle?n=20`
  - `GET /api/replay?n=20`（完整回放）

**为什么要做**
观众看到"因果"，才会觉得系统有脑子。**一堆数字不构成因果，一条时间轴构成因果。**

**验收**
- 点一次 takeoff，时间轴上依次出现 allow → adapter → result 三个节点
- 出现 deny 时，时间轴上有红色节点且可点开看判定理由

---

### F3 ★★ 降级大屏：让"变化"可见

**要做什么**
- 三个**大数字 + 趋势箭头 + 颜色**，常驻可见：

```
链路质量        任务完成度        剩余安全裕度
   42 ▼             78% ▲             正常
  （红色）         （青色）          （绿色）
```

- `链路质量` 从 `GET /api/vehicle-snapshot`（或新接口）取，**下降时要明显**
- `任务完成度` 从任务层取（见 F4），**要有进度条**

**为什么要做**
**"掉下去的那一刻"是全场注意力最集中的时刻。** 这是整个演示的高潮点，必须有视觉承载。

**验收**
- 注入降级后，`链路质量` 在屏幕上肉眼可见地掉下去并变红

---

### F4 ★★ 任务完成度 KPI

**要做什么**
- 把后端的覆盖/完成度数据变成**大数字**：
```
任务完成度   78%
已侦察区域   6.2 / 8.0 km²
目标发现     4 / 5
```
- **依赖后端**：见任务书三（S3），需要后端提供"任务完成度"接口

**验收**
- 数字随任务推进真实增长（不是假动画）

---

### F5 ★★ 策略裁决「横幅 + 可溯源面板」

**你的要求（原话）**：策略决策太多，要么在某个页面一直出现然后可以换页面不看，这个可以。
**所以设计成两个东西：**

**F5-1 横幅（抢眼，但不挡路）**
- 出现在顶部，2 秒后缩成一个小徽章
- 内容示例：`UAV-02 link_quality=18 → hold-position (policy: degraded_link)`
- **可以一键关闭**

**F5-2 溯源面板（常驻可查）**
- 放在「Policy Gate」或「Audit·Replay」模块里
- 一张表：时间 / 载具 / 动作 / 判定 / 规则名 / 完整事件 JSON
- 支持按载具、按判定结果过滤
- **换页面就不看，回来看还在**

**验收**
- deny 发生时，不看日志也能在屏幕上看到提示
- 事后能在这个面板里找到那一条，并看到完整理由

---

### F6 ★★ 「LIVE / DEMO」双模式 + 演示大屏（重要）

**你的判断（原话）**："真正的无人机群智能化不需要任何操作"
**所以做一个零操作的展示模式：**

**F6-1 演示大屏（`?mode=stage`）**
- 全屏、无侧边栏、无多余按钮
- 自动轮播关键画面：任务地图 → 降级大屏 → 时间轴 → 三维态势
- 每 15~20 秒切一次，**零操作**

**F6-2 明确标注数据来源**
- 界面上始终有 `LIVE`（真实遥测）或 `DEMO`（内置演习数据）标记
- **不要让演示数据看起来像真实数据** —— 这既是诚信，也是避免被质疑

**验收**
- 打开 `?mode=stage`，不碰鼠标，能看到完整故事线自动播完

---

### F7 ★ 「没实现」显式化（成本最低，收益很高）

**要做什么**
- 未接的模块：**灰掉 + 小标签「规划中」**
- 已接但无数据：显示 `等待数据`，不要空白
- 点了没实现的按钮：弹提示「该能力接口已通（`/api/actions/goto`），界面规划中」

**为什么**
观众点到空白页，印象是"没做完"。
看到"他们清楚知道自己在哪一步"，印象是"工程管理清晰"。
**诚实是最便宜的完成度。**

**验收**
- 全站点不出"无反应的按钮"或"纯空白页"

---

## 1.4 前端**不要**做什么

- ❌ 不要为了视觉效果造假数据（必须标 `DEMO`）
- ❌ 不要重写三维渲染管线（Cesium 那套能跑就别动）
- ❌ 不要在本次改动里重构技术栈（还是原生 JS，不引入框架）
- ❌ 不要动 `runtime-api.js` 的默认 base URL（`http://127.0.0.1:8765/api` 是对的）
- ❌ **本次不动左侧导航结构、不做模块合并、不改信息架构**
  （这一项另行讨论，本次范围只有 F1~F7；请你先按现有 15 个模块的骨架做上面的事）

---

# 二、给【Runtime】负责人的任务书

> Runtime 这次是**配合方**，但有两件事必须做，否则前端做得再好也演不出来。

## R1 ★★★ 链路质量指标（不是布尔）

**现状**
`simulation/px4_gazebo/health.py` 已经有：
- `heartbeat_fresh` / `telemetry_fresh`（布尔）
- `last_heartbeat_age_s` / `last_telemetry_age_s`
- `heartbeat_count` / `heartbeat_span_s`

**缺的是**：一个**连续的 0~100 分**。

**要做什么**
- 新增 `link_quality`（0~100），由现有 age 数据推算即可，例如：
  - 由 `telemetry_age` 与预期更新周期（50 Hz 流 → 20 ms）算超期倍数
  - 由 `heartbeat_age` 算心跳健康度
  - 由最近 N 秒的 `heartbeat_span` 算抖动
- **不要把现有布尔字段删掉**（有测试和审计依赖它们），只做**新增**
- 暴露到已有接口（`/api/vehicle-snapshot` 或 `/api/telemetry/latest`），**不要新增一个只给前端用的临时接口**

**验收**
- `curl /api/vehicle-snapshot` 能看到每架机的 `link_quality`
- 正常状态下在 80~100 之间波动
- PX4 停掉时 5 秒内掉到 0

---

## R2 ★★★ 故障注入（演示专用，必须可控可逆）

**要做什么**
- 新增一组**演示专用**接口（命名上要明确是 demo，避免误用于生产）：

```
POST /api/demo/inject    {"node_id":"UAV-02","kind":"link_degraded","value":18,"duration_s":60}
POST /api/demo/inject    {"node_id":"UAV-02","kind":"link_lost"}
POST /api/demo/clear     {"node_id":"UAV-02"}
GET  /api/demo/state
```

- `kind` 只支持三种：`link_degraded` / `link_lost` / `recover`
- **必须可逆**：`clear` 之后 1 秒内恢复正常
- **必须幂等**
- **必须在审计里留痕**（`demo_inject` / `demo_clear` 事件），否则回放时说不清

**硬性要求**
- ❌ **绝不能真的改网络配置**（不要碰 `tc` / `iptables`）
- ✅ 在 Runtime 内部对 `link_quality` 做覆盖（override），**不影响 PX4 和 Gazebo**
- ✅ 注入可以带 `duration_s`，到点自动撤销（防止演示中途忘了清）

**验收**
- 注入后前端 `link_quality` 立刻变
- `clear` 后立刻恢复
- 审计里能看到注入和撤销两条事件
- **PX4 和 Gazebo 完全不受影响**

---

## R3 ★★ 降级策略规则（让系统"自己会处置"）

**要做什么**
在 policy 里加针对 `link_quality` 的规则（**这是从"能拒绝危险动作"升级到"能处理系统级降级"**）：

```
link_quality < 40 且 任务未完成  → 该机 hold-position，任务重分配
link_quality < 10                → 该机 return-home
恢复后 link_quality ≥ 60          → 允许重新入队
```

**要求**
- 规则命中要在 `policy_decision_event` 里有**明确的规则名**（例如 `degraded_link_hold`）
- `reason` 字段要人能看懂
- 需要走现有的统一裁决入口，**不要旁路 policy gate**

**验收**
- 注入 `link_degraded=18` 后，**不做任何操作**，几秒内出现 `hold-position` 的 policy 决策与执行结果
- 决策里能看到规则名和触发条件

---

## R4 ★★ 任务完成度接口

**要做什么**
- 提供 `GET /api/mission/progress`（或并入 `/api/snapshot`）：
```
{"mission_id":"...", "completion_pct":78, "area_total_km2":8.0,
 "area_covered_km2":6.2, "targets_found":4, "targets_total":5,
 "degraded":true, "vehicles_active":2}
```
- 数据来源：`simulation/px4_gazebo/patrol.py` 里已有航点到达、`sample_coverage` 等逻辑，
  **不要重写**，把已有的内部量**暴露出来**

**验收**
- 三机起飞并巡逻后，`completion_pct` 单调增长（允许平台期）
- 有一架 `return-home` 后，`vehicles_active` 变成 2，且 `degraded: true`

---

## R5 ★ 失败归因进审计

**现状**：`mavlink_backend_session.py` 里已有 `classify_incomplete_evidence`
（能区分"落地了但超时"和"坠了永远等不到"）—— 这是好东西。

**要做什么**
- 把它产出的分类结果**写进 `action_result` 的审计字段**
- 前端才能在 Audit·Replay 里展示"为什么判定未完成"

**验收**
- 一次超时的降落动作，审计里能看到具体分类，而不只是 `timeout`

---

# 三、给【仿真 / PX4】负责人的任务书

## S1 ★★★ 三架飞机必须真的能飞（**这是整个演示的硬前提**）

**现状**
三架 x500 在 Gazebo 里**停在地面、未 arm**。前端能看到遥测（mode / armed / 位置），
但**位置不变** —— 所以"任务完成度"和"降级表现"都无从演示。

**要做什么**
1. 三机都能正常 `arm` + `takeoff` + 按航点飞
2. `local_position` **持续变化**，并被 Runtime 的遥测接口读到
3. 支持 `hold-position` / `return-home` / `land` 三个降级动作在三机上都可用

**验收（硬性）**
```bash
# 连续两次采样，位置必须变
curl -s http://127.0.0.1:8765/api/telemetry/latest | grep -o '"local_position[^}]*"'
```
- 起飞后 `z` 从 0 变到正值
- 巡航时 `x`/`y` 持续变化
- 三架各自独立

> **如果这一条做不到，前端和 Runtime 做的一切都没有意义。** **优先级最高。**

---

## S2 ★★★ Gazebo 世界 ↔ 前端 Cesium 城市的场景一致性

**背景澄清（这条很重要，避免走错方向）**

| | 是什么 | 在哪 |
|---|---|---|
| **Cesium** | **前端**三维引擎（地球/城市渲染） | `frontend/.../simulation-3d/dist/cesium-static/` |
| **Gazebo** | **后端**物理世界（`.sdf`） | `scenarios/simple_recon_v0_1/worlds/*.sdf` |

**也就是说：前端展示的"青岚市"，和后端飞机实际飞的世界，目前是两个不同的世界。**
飞机在 Gazebo 的 `simple_recon_v0_1` 里飞，却显示在 Cesium 的青岚市里。
**这会导致观众发现"建筑和飞行轨迹对不上"。**

**要做什么（按优先级，能到哪一步算哪一步）**

**S2-a 最低要求：坐标对齐**
- 用现有的 `calibration.py`（18 KB）+ `scenarios/simple_recon_v0_1/scene.json`，
  把 Gazebo 世界的**原点、朝向、尺度**与 Cesium 场景标定一致
- 验收：在 Gazebo 里把一架机挪到 NED(100, 0, 0)，前端三维里的位置**方向和距离都对**

**S2-b 进阶：几何对齐（能省则省）**
- 让 Gazebo 世界里的**主要地物**（河、主干道、几个街区）和 Cesium 城市**大致对应**
- 不需要建筑级 1:1，**能看出"在同一条河的两岸"就够了**

**S2-c 如果做不动，就明确降级（也是可接受的方案）**
- 承认"物理世界与展示世界不一致"
- 前端改用**抽象表示**：不显示具体建筑，只显示网格地面 + 区域多边形 + 飞机
- **"用真实城市数据做模拟"** 是另一个方向：用现成的 3D Tiles 城市（Cesium 已有能力）
  做**纯展示**，明确标 `DEMO`，不要声称是物理仿真

**需要你回复的问题**
1. 现在 `simple_recon_v0_1.sdf` 里有哪些地物？和前端青岚市有没有共同参照物？
2. `calibration.py` 现在标定的是哪两个坐标系？能否直接用于 Gazebo ↔ Cesium？
3. 要做到 S2-a 需要多久？S2-b 呢？

---

## S3 ★★ 提供"任务完成度"的原始数据

**要做什么**
- `patrol.py` 里已有航点到达、最小间距、`sample_coverage` 等逻辑
- 需要把"**已覆盖区域 / 总区域**"变成可读的量，供 Runtime 的 `/api/mission/progress` 使用
- 侦察区域建议用**多边形**定义（放在 `scene.json` 里），便于前端任务地图直接画

**验收**
- 提供一个能算出 `area_covered_km2` 的稳定接口或函数

---

## S4 ★ 起停可靠性

**要做什么**
- `start_three_uav.sh` 重复执行要**幂等**（已启动就提示，不报错也不重复起）
- `stop_three_uav.sh` 要能**清干净**（三个 PX4 + Gazebo 全部退掉，端口释放）
- 起不来时要给出**明确的失败原因**（端口占用 / 模型缺失 / 世界文件缺失）

**为什么**
演示当天最怕"起不来又不知道卡在哪"。

**验收**
```bash
bash scripts/start_three_uav.sh --config ... ; bash scripts/start_three_uav.sh --config ...   # 不报错
bash scripts/stop_three_uav.sh
ss -lunp | grep -E '1454|1458' || echo "端口已释放"
```

---

# 四、三位之间的接口约定

| 谁给谁 | 什么 | 形态 |
|---|---|---|
| 仿真 → Runtime | 三机遥测（位置持续变化） | 现有 MAVLink 14540/41/42 |
| 仿真 → Runtime | 覆盖面积 | 函数或文件 |
| Runtime → 前端 | `link_quality` | 并入 `/api/vehicle-snapshot` |
| Runtime → 前端 | `/api/demo/inject` `/clear` | 新增（演示专用） |
| Runtime → 前端 | `/api/mission/progress` | 新增 |
| Runtime → 前端 | 降级 policy 决策 | 现有 `/api/policy/decisions` |
| 前端 → Runtime | 注入/清除按钮 | 调 `/api/demo/*` |

**所有新增字段/接口：向后兼容，不删旧字段。**

---

# 五、优先级（如果时间不够，从上往下砍）

| 序 | 任务 | 负责人 | 为什么排这个位置 |
|---|---|---|---|
| 1 | **S1 三机真能飞** | 仿真 | **没有这个，其他全是空谈** |
| 2 | **R1 链路质量分** | Runtime | 注入器需要它才能"显示下降" |
| 3 | **R2 故障注入** | Runtime | 一个东西就能让演示有戏剧性 |
| 4 | **R4 任务完成度接口** | Runtime | 观众需要一个会变的百分比 |
| 5 | **F1 首屏重构 + F2 时间轴** | 前端 | 因果可见，投入产出最高 |
| 6 | **R3 降级策略规则** | Runtime | 有了注入器，规则就是几个 if |
| 7 | **F5 横幅 + 溯源面板** | 前端 | 让"自主处置"被看见 |
| 8 | **F3 降级大屏 + F4 KPI** | 前端 | 演示高潮的视觉承载 |
| 9 | **F6 演示大屏** | 前端 | 零操作展示 |
| 10 | **F7 显式化（没实现的别假装能点）** | 前端 | 诚实是最便宜的完成度 |
| 11 | **S2 场景一致性** | 仿真 | 重要但可降级 |

---

# 六、验收：一次演示要能走完这条路

```
1. 三机起飞，位置在变                          ← S1
2. 首屏任务地图上三架飞机的进度在涨            ← F1 + F4
3. 任务完成度 0% → 35%                         ← R4 + F3
4. 点「注入链路降级」                          ← R2
5. 链路质量 95 → 42 → 18（红色下坠）           ← R1 + F3
6. 不做任何操作，几秒内出现降级处置             ← R3
7. 顶部横幅显示判定与规则名                    ← F5
8. 时间轴出现黄色降级节点                      ← F2
9. 一架 hold-position，任务重分配，完成度继续涨 ← R3 + R4
10. 点「恢复链路」，恢复为蓝色节点              ← R2 + F2
11. 打开 Audit·Replay，整条链按时间重建         ← F5 + R5
```

**这 11 步走完，就是一次完整、有说服力的演示。**

---

# 附录 A：后端 26 个接口 vs 前端覆盖情况

| 接口 | 前端 | CLI/curl |
|---|:---:|:---:|
| `/api/health` `/api/vehicles` `/api/telemetry/latest` `/api/vehicle-snapshot` `/api/snapshot` | ✅ | |
| `/api/events` `/api/policy/decisions` `/api/actions/recent` `/api/actions/lifecycle` `/api/actions/{id}` | ✅ | |
| `/api/actions/takeoff` `/api/actions/land` `/api/actions/smoke-takeoff` | ✅ | ✅ |
| `/api/backend/check` `/api/planner/plan-mission` `/api/skills` `/api/agent/status` `/api/simulation/status` | ✅ | ✅ |
| **`/api/capabilities`** | ❌ | ✅ `cli list-capabilities` |
| **`/api/preflight`** | ❌ | ✅ curl |
| **`/api/replay`** | ❌ | ✅ `cli replay-last` |
| **`/api/actions/goto`** | ❌ | ✅ `cli submit-action` |
| **`/api/actions/hold-position`** | ❌ | ✅ `cli submit-action` |
| **`/api/actions/return-home`** | ❌ | ✅ `cli submit-action` |
| **`/api/plans/execute`** | ❌ | ✅ `cli submit-mission` |
| **`/api/simulation/evidence`** | ❌ | ✅ curl |
| **`/api/coordinates/calibration`** | ❌ | ✅ curl |

**前端覆盖 17/26 ≈ 65%，但 26 个接口全部有 CLI 或 curl 可达 —— 没有能力"只能看代码"。**

---

# 附录 B：现状速查（给不熟悉的人）

## 启动顺序（4 个终端，全在 WSL）

```bash
# 终端 1：三机仿真
cd /root/uavswarm && bash simulation/px4_gazebo/scripts/start_three_uav.sh \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json --gui

# 终端 2：Runtime（必须 /usr/bin/python3 = 3.10）
cd /root/uavswarm && PYTHONPATH="$PWD/src" /usr/bin/python3 -m uav_runtime.http.server

# 终端 3：主控台 5178
cd /root/uavswarm/frontend/swarm-console && python3 -m http.server 5178 --bind 0.0.0.0

# 终端 4：三维 5179（必须用反代脚本，不能用 http.server）
cd /root/uavswarm && python3 /mnt/d/weier-offline/serve_3d_proxy.py \
  --dir frontend/swarm-console/simulation-3d/dist
```

## 端口

| 端口 | 用途 |
|---|---|
| 8765 | Runtime API |
| 5178 | 主控台 |
| 5179 | 三维（含 `/api` 反代） |
| 14540-14542 | PX4 → Runtime（遥测），`14540 + 实例号` |
| 14580-14582 | Runtime → PX4（指令），`14580 + 实例号` |

## 关键代码位置

| 路径 | 是什么 |
|---|---|
| `src/uav_runtime/http/routes.py` | 所有 API 路由（26 个） |
| `src/uav_runtime/adapters/px4_sitl_backend.py` | PX4 adapter，靠 `find_spec("pymavlink")` 判可用 |
| `simulation/px4_gazebo/health.py` | 心跳/遥测新鲜度（`link_quality` 的原料） |
| `simulation/px4_gazebo/patrol.py` | 巡逻任务引擎（48.8 KB，航点/间距/覆盖） |
| `simulation/px4_gazebo/calibration.py` | 坐标标定（S2 要用） |
| `frontend/swarm-console/app.js` | 主控台全部逻辑（113 KB） |
| `frontend/swarm-console/runtime-api.js` | API 封装，默认 base = `http://127.0.0.1:8765/api` |
