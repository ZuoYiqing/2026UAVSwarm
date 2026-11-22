# 2026UAVSwarm Console Frontend

这是一个独立于 `src/uav_runtime/` 的前端原型，用于展示无人机集群三维数字孪生运行平台。

当前主控制台是零依赖静态 SPA，方便快速预览并避免影响 Python runtime。CesiumJS 三维场景保持在独立的 `simulation-3d/` 子项目中，二者通过稳定的数据契约集成。

## 运行

在仓库根目录执行：

```bash
python -m http.server 5178 --directory frontend/swarm-console
```

打开：

```text
http://localhost:5178/
```

`5178` 是前端静态页面端口。关闭服务时，在运行命令的终端按 `Ctrl+C`。

## 任务态势与演示大屏

在左侧选择「总览驾驶舱」，再点右上角的「实时大屏」或「离线演习」。大屏顶部的「返回主控台」回到总览。

| 入口 | 数据来源 | 用途 |
| --- | --- | --- |
| `http://127.0.0.1:5178/` | Runtime 公共 API | 任务地图、关键指标、主时间轴与审计 |
| `http://127.0.0.1:5178/?mode=stage` | 内置离线脚本 | 三机分区、链路降级与接续、恢复与结果。约 60 秒播完，可暂停、按章节查看及从头播放 |
| `http://127.0.0.1:5178/?mode=stage&source=live` | Runtime 公共 API | 查看任务地图、关键指标、审计事件与三维态势。默认停在所选页，可开启自动轮播 |

离线演习同屏展示脚本里的任务地图、状态和事件，只需启动 5178 主控台。实时大屏的「三维态势」通过 5179 加载 Cesium，使用现有三维开发服务或 `ops/serve_3d_proxy.py`。

换到离线电脑时，将这一版本的 `frontend/swarm-console/` 和已构建的 `simulation-3d/dist/` 一起带过去。三维目录下的 `src/vehicle-contract.js` 也随主控台复制，供 LIVE 快照校验使用。从复制后的项目根目录开启两个终端：

```powershell
# 终端 1：主控台
python -m http.server 5178 --bind 127.0.0.1 --directory frontend/swarm-console

# 终端 2：三维态势（需要时启动）
python -m http.server 5179 --bind 127.0.0.1 --directory frontend/swarm-console/simulation-3d/dist
```

在离线电脑自己的浏览器打开上表地址。现场使用实时大屏时，另行启动 Runtime，并按现场部署方式提供 5179 的三维服务。浏览器窗口变窄时，主控台自动将三维、节点列表和遥测改为上下排列。

首屏的链路质量是 Runtime 上报的遥测接收新鲜度评分。任务地图分别显示已验证的航点完成度（已到达 / 总航点）和面积覆盖率（已覆盖面积 / 总面积）。缺少区域时，有同场景、同地图版本的新鲜共享坐标即可显示载具位置；区域、分工及覆盖率仍待上报。只有区域边界和面积汇总时，空间分布显示「覆盖未知」。目标发现和安全裕度缺少证据时显示等待或未知。

Runtime 提供 S7 的 `coverage.grid` 时，任务地图按 `scene_ned` 米绘制有覆盖记录的网格，并用 `coverage.polygon` 裁剪边缘。粗格内可能只有部分面积覆盖。面积覆盖率使用源网格累计面积。网格缺席时，可单独显示经校验的同图面积汇总。附带的网格无法校验，或上报的覆盖百分比与面积矛盾时，面积和网格同为未知。合法的空覆盖列表显示「已有观测，当前没有覆盖记录」。[仿真契约与示例](https://github.com/ZuoYiqing/2026UAVSwarm/pull/102)

时间轴读取 `/api/events?n=50`、`/api/policy/decisions?n=20`、`/api/actions/lifecycle?n=20` 和 `/api/replay?n=20`。点击记录查看原始 JSON。Policy Gate 可按载具和判定过滤，顶部裁决提示 2 秒后缩成徽章并支持关闭。

Runtime 启动时设置 `UAV_RUNTIME_DEMO_ENABLED=1` 并接入有可选载具的 Runtime 后，总览会显示独立的链路故障演习控件。详细配置和范围见 [Runtime 演示接口](../../docs/runtime_demo_readiness_v1.md)。

Runtime 支持时，主控台会读取 `/api/mission/progress` 和 `/api/demo/state`。显式启用 Runtime 演习后，可从首屏选中载具并发出 DEMO 注入或清除请求。注入分与实测分分别显示，模拟处置与分配记录标为 DEMO。默认 API 地址仍为 `http://127.0.0.1:8765/api`。

## 设备巡检的离线验收

| 阶段 | 输入与显示 |
| --- | --- |
| Runtime 模板预览 | 把任务原话以 `dry_run: true` 提交到 `/api/planner/plan-mission`。显示固定模板步骤和对应的预检回执。 |
| 可校验计划候选 | 等待算法提供已校验的场景版本、载具和航点。DOM 测试使用内存接口桩按任务原话返回导航候选，供操作员确认。 |
| 人工确认与执行 | 测试桩先展示候选航点，再由操作员填写 ID 并确认。提交体沿用 `{ plan, operator_id, decision: "approve" }`，Runtime 的准入、Policy 和动作生命周期保留在服务端验收中。 |
| Runtime 进度 | LIVE 首页和大屏消费 `GET /api/mission/progress` 的 `runtime_plan_executor` 记录。无任务、读取失败和缺少身份字段分别显示，旧进度停止显示。 |

进度关联使用 `mission_id = plan_id`、`run_id`、`scene_id` 和 `map_version`。Runtime 本地提交 `9398b10` 在执行回执提供与进度相同的 `run_id`。基线 `6a680fe` 的回执缺少该字段，规划页因此显示无法关联。航点百分比依照 Runtime 的已验证到达计数，覆盖率依照同场景同地图的覆盖样本。航点 100% 时仍按 Runtime 单独上报的执行状态展示。

在主控台目录运行 `node --test tests/mission-dashboard.test.js`。用例使用 [target-001 导航测试桩证据](tests/fixtures/equipment-inspection-lifecycle.json)。证据来自 `9398b10` 的 `test_plan_execution_progress_fake.py` 内存调度与假动作传输，使用仿真场景参考 `f6e5a1a`，并为覆盖试验显式配置区域 `three-uav-patrol-coverage-v1` 和 10 m 的夹具采样半径。证据包含完整运行、到达超时、未执行以及落地前航点全部到达的进度返回。普通浏览器入口提供模板预览和只读进度，执行控件仅由测试桩注入。

算法本地提交 `d752354` 已提供可复核的分工与航点候选，设备巡检中的 `OBSERVE` 在转换时明确受阻。导航测试桩的通过只证明导航、进度和失败显示。设备观测能力及其执行映射需由算法与 Runtime 共同确认，真实仿真验收还需同版本场景及当次有效标定。

## 页面

- 总览驾驶舱
- 任务规划
- 三维集群态势
- 单机详情
- Agent Runtime
- Policy Gate
- Skills 能力库
- Adapter / Backend
- 仿真中心
- 观察复核
- 澄清待办
- 硬件资产
- Audit / Replay
- 模型与知识
- 系统设置

Cesium 三维子项目需要单独启动：

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d
npm run dev
```

三维页面默认运行在 `http://127.0.0.1:5179/`。主控制台会将其作为 iframe 嵌入，并成为
`vehicle-snapshot` 的唯一轮询方和消息发送方。

## LIVE 数据接入

- `runtime-api.js` 是前端到 runtime HTTP 服务的唯一适配层。
- `app.js` 启动后轮询 Runtime snapshot、Registry、Telemetry、Agent、Simulation 和 Cesium vehicle snapshot。
- 载具列表由 `/api/vehicles`、`/api/telemetry/latest` 和 `/api/vehicle-snapshot` 合并，不再使用固定八机数组。
- 选择 UAV 后，Check Backend、正式起飞、Smoke Test 和受控降落请求携带该节点的 `node_id`、endpoint、`system_id` 和 `component_id`。
- 正式动作同时携带稳定的 `request_id`、`trace_id`、`idempotency_key` 和 `command_source=ground_station`；页面刷新后只通过 GET 查询原请求，绝不自动重发 POST。Runtime 重启丢失记录时显示结果未知，保留重复起飞锁；LAND 仍按节点和 Runtime 状态受控开放。
- 动作结果绑定发起时的节点。处理中切换节点只切换视图，不会把原节点结果写到新节点。
- Policy 放行、MAVLink ACK 接受、执行中和遥测确认成功分别显示，ACK 不等于飞行完成。
- Runtime 离线、节点未启用、遥测过期或 identity 缺失时，飞行动作保持禁用。
- `simulation-3d/` 通过严格来源的 `postMessage` 接收主控制台轮询到的完整快照。
- Agent、Policy、Skills、Audit / Replay 页面只展示后端已提供的数据，缺失指标显示为未提供，不生成成功率和延迟等假数据。

## Runtime API 配置

默认 API 地址：

```text
http://127.0.0.1:8765/api
```

`8765` 是 WSL/Python `uav_runtime_http_bridge` 的 HTTP 端口，不是前端页面端口，也不是 MAVLink 端口。`/api` 是该服务的固定路由前缀；各 PX4 SITL MAVLink endpoint 由 Runtime Registry 返回，前端不写死端口。

可在页面 `Adapter / Backend -> Runtime API 与传输端点 -> Runtime API Base URL` 中修改，配置会保存到浏览器 `localStorage`。

顶部状态栏显示：

- `Runtime API 连接中`：页面正在探测 `/api/health`。
- `Runtime API LIVE`：浏览器可以访问 HTTP bridge。
- `Runtime API OFFLINE`：HTTP bridge 未启动、地址错误或请求超时。
- `数据源 LIVE`：Telemetry 快照新鲜。
- `数据源 STALE`：Runtime API 断开或 Telemetry 已过期，页面保留最后快照。
- `数据源 无数据`：Runtime 可达但还没有 Telemetry，或 Runtime 完全不可达且无缓存。

## 前端期望的后端接口

浏览器不能直接执行 `python -m uav_runtime.console.cli ...`，需要 WSL/Python 侧增加一个轻量 HTTP bridge。前端当前约定以下接口：

```text
GET  /api/health
POST /api/backend/check
POST /api/actions/takeoff
POST /api/actions/smoke-takeoff
POST /api/actions/land
GET  /api/actions/{action_id}
GET  /api/actions/lifecycle?n=20
POST /api/planner/plan-mission
GET  /api/replay?n=20
GET  /api/capabilities
GET  /api/events?n=50
GET  /api/actions/recent?n=20
GET  /api/policy/decisions?n=20
GET  /api/skills
GET  /api/vehicles
GET  /api/telemetry/latest
GET  /api/snapshot
GET  /api/vehicle-snapshot
GET  /api/agent/status
GET  /api/simulation/status
```

正式起飞请求示例：

```json
{
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "backend_enabled": true,
  "node_id": "UAV-02",
  "system_id": 2,
  "component_id": 1,
  "transport_endpoint": "udpin:127.0.0.1:14541",
  "altitude_m": 3,
  "command_timeout_ms": 10000,
  "observe_timeout_ms": 25000,
  "altitude_tolerance_m": 0.3,
  "stable_duration_ms": 1000,
  "request_id": "req-console-uav02-001",
  "trace_id": "trace-console-uav02-001",
  "idempotency_key": "console-uav02-takeoff-001",
  "command_source": "ground_station"
}
```

关键返回要求：

- `check-backend` 返回 `readiness` 或 `connect_probe.code`。
- 正式动作返回并持久化 Runtime lifecycle 1.1：`requested`、`policy_rejected`、`accepted`、`executing`、`succeeded`、`failed`、`timed_out`。
- `ack_evidence` 只表示命令阶段 ACK；`completion_evidence` 才是起飞稳定高度或降落落地且解除武装的完成依据。
- Smoke Test 保留兼容测试语义，可能按请求自动降落；人工“正式起飞”不会设置 `auto_land`。
- `replay` 返回最近审计事件数组。

## 当前已接入的按钮

- `任务规划 -> 预览巡检模板`：把输入的任务目标随 `inspection_snapshot` 和 `dry_run: true` 提交到 `/api/planner/plan-mission`，展示 Runtime 返回的步骤、逐步策略预检和动作风险级别。航线和完整任务下发尚未接入该页。
- `任务规划 / 三维集群态势 -> 本地试推理`：选择 32 米、22 米或 47 米题以填入原话，再点「本地试推理」，请求本机 Lab 的 `POST http://127.0.0.1:18118/lab/semantic-preview`。目前仅支持导出目录北侧首排东半幅的限定楼栋题。Lab 和模型需另行就绪，主控台从 `http://127.0.0.1:5178` 或 `http://localhost:5178` 打开。
  - 「检查 Lab」只读取 `/lab/semantic-preview/health`。`ready` 表示 Lab 可接收请求，`model_status: not_checked` 显示为「模型状态未检查」。
  - 实时结果显示原话、模型原始回复、算法结论和 Lab 上报耗时。沿用预览 schema 0.1，检查响应和预览的 `execution_authorized=false`，核对 `evidence_json` 的 UTF-8 SHA-256 及原话、模型回复和结论。原始证据可在「来源与限定条件」展开查看。
  - 实时、回放、导入各自标源。实时请求期间禁用重复提交，HTTP 错误、网络故障、25 秒超时或响应不符会清空旧实时结果并显示原因。用户可手动重试。前端只调用上述 Lab 回环地址，同屏复用现有三维 iframe。
- `任务规划 -> 离线算法证据 · 只读预览`：可加载规则样例、选择「模型实测回放（不触发推理）」或导入 `*.preview.json`。「三维集群态势」在现有三维窗旁显示同一份证据，也可从那里切换。回放只读静态文件，试测者只需启动本页，不需要模型、Runtime 或三维服务。
  - 模型回放源于本地 Qwen3.5-0.8B 的三条录制响应：32 米题核对通过，22 米和目录范围内无 47 米匹配的两题被挡下。展开「来源与限定条件」可查看证据文件名、目录版本和 SHA-256；同目录的 `*.raw.json` 保留实际模型输入及原始响应。
  - 「并列澄清」「明确实体后的绑定」是离线规则样例，模型未运行。所有记录均使用 `simple_recon_v0_1 / simple_recon_v0_1-map-1` 的待审核物理导出目录；预览不标注实时地图，不生成航线或动作，也不构成执行授权。
- `Adapter / Backend -> Check Backend`：调用 `/api/backend/check`。
- `飞行控制与 Runtime -> 正式起飞`：调用 `/api/actions/takeoff`。
- `飞行控制与 Runtime -> Smoke Test`：调用 `/api/actions/smoke-takeoff`，与人工起飞明确分开。
- `飞行控制与 Runtime -> 受控降落`：调用 `/api/actions/land`；是否抢占空中动作以 Runtime 返回为准。
- `Audit / Replay -> 刷新事件`：调用 `/api/events?n=30`。

## 前端验证

```powershell
npm run check
npm test
```

`console-model.js` 是可独立测试的数据映射层，负责合并多机快照、判断动作权限和构造带
MAVLink identity 的请求。浏览器页面不直接连接 MAVLink、Gazebo Transport 或 DDS。

Runtime 已实现 `takeoff / goto / land / hold_position / return_home` 五种动作，并注册 `/api/actions/takeoff`（另有独立的 `/api/actions/smoke-takeoff`）、`/api/actions/goto`、`/api/actions/land`、`/api/actions/hold-position`、`/api/actions/return-home` 路由。

真实验证状态按项目负责人提供的记录分层列出（截至 2026-10-09；不含 fixture 测试）：

| 动作 | 真实验证状态 |
| --- | --- |
| `takeoff / land` | 三机巡逻验证通过 |
| `goto` | 已实测 |
| `hold_position`（别名 `hold`） | 已实测：`max_drift_m=0.054 m`，容差 `2.0 m`，`completion_state=stable_within_tolerance` |
| `return_home` | 后端已实现，尚未完成有效真飞验证；本次垂直起飞未离开 home，无法检验“距离缩小 ≥5 m”的判据 |

主控台本轮不新增 `GOTO/HOLD/RETURN_HOME` 按钮：`goto / hold_position` 已有实测记录，前端操作入口尚未接入；`return_home` 等有效真飞验收后再开放。页面仅在非 Smoke TAKEOFF 的 `completion_evidence` 确认稳定高度后显示“起飞时曾确认高度稳定”，不是持续保持证明，也不是当前所选节点已执行 HOLD 的证明；当前飞行状态以实时遥测为准。

本轮动作功能依赖 Runtime PR #76 的 lifecycle 1.1 契约；基线旧服务缺少该接口时禁用正式动作。
主控制台不修改坐标，校验三维子应用既有快照契约后原样转发。Runtime/Simulation 的场景标识即使一致，Cesium 实际加载地图仍需独立确认。

浏览器回归可单独运行 `npm run dev:fixture-runtime`，仅监听 `127.0.0.1:8876`。
将控制台 API 改为 `http://127.0.0.1:8876/api` 可测试状态；该服务完全不连接 PX4，测试完成必须恢复 `http://127.0.0.1:8765/api`。
该静态 SPA 没有构建步骤；`npm run check` 为语法检查。真实四模块验收结果与 fixture 测试必须分开记录。

接口失败时页面会显示明确的 OFFLINE、STALE 或 HTTP 错误状态。静态页面仍可浏览，但 Runtime API、动作生命周期接口或目标 PX4 Backend 未就绪时，正式动作会被禁用。
