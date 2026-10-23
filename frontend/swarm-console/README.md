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

- `HTTP（浏览器→网关）连接中 / LIVE / OFFLINE`：只描述浏览器到 HTTP bridge 的可达性；HTTP 错误响应仍证明网关可达，不证明平台地面链路、任务或飞控就绪。
- `平台观测 LIVE`：关键状态接口均返回可用结构且 Telemetry 状态为 `ok`；单机是否过期还按平台上报值显示。
- `平台观测 STALE`：观测不可用或 Telemetry 已过期，页面保留最后上报状态，当前状态未知。没有缓存时显示“无数据”及 `unknown`。

### 断联与恢复（现有 API）

- 浏览器 HTTP 失败不改写最后平台 `connected / stale`、任务快照或动作结论；`observationStale` 是前端观测标记，不是 Runtime 新字段。页面显示 STALE、最后完整新鲜状态的本地接收时间 `lastObservationAt`，以及单机平台采样时间 `last_seen`（若无则 `unknown`）。上报的 sample age 明确标为“上报时”，不冒充当前年龄。
- `/health` 或 `/events` 恢复不解除观测过期。只有 Registry、Telemetry、vehicle snapshot 的本轮关键 GET 全部成功、结构可用且 Telemetry 状态为 `ok` 才恢复新鲜状态；部分 GET 成功不能覆盖最后完整的关键快照。
- 动作准入相对旧行为是收紧：即使 HTTP 已恢复，观测尚未完整同步时 TAKEOFF/LAND 都不开放。保留平台 `connected=true` 不放宽操作权限，也不修改飞行验收判据。已授权的平台任务是否继续执行由平台决定，前端不自动取消。
- 恢复沿用生命周期与动作查询 GET、原 request/action 身份和持久 pending 记录；不自动重发任何任务或动作 POST。原记录丢失仍显示结果未知。
- 给三维子页的新鲜快照原样转发；观测过期时仅在派生视图标记 `telemetry.stale=true`，不改写 `connected`、坐标、采样时间和原始缓存；不修改 `simulation-3d/`。
- 断联提示也会在输入框编辑期间刷新。现有动作生命周期不能代替独立平台任务状态；平台代理状态在 Agent Runtime 的只读面板中单独显示。

### 平台任务与事件（只读 v1.0）

Agent Runtime 页面新增独立平台面板，通过当前配置的地面网关每 3 秒读取：

```text
GET /api/platform/status
GET /api/platform/tasks/{task_id}
GET /api/platform/events?after_seq=N&store_id=S
```

- 展示平台 `ground_link.state`、最后心跳时间及上报时年龄，另列浏览器观测 LIVE/SYNCING/STALE/UNKNOWN、本地接收时间及飞控采样时间。后台心跳由地面 Runtime 负责，浏览器关闭不代表地面链路断开。
- `node_id`、`boot_id`、`store_id`、`run_id`、`task_version`、`execution_id` 均显示来源值；任务状态包括 `recovery_required`，不会根据旧动作成功、链路丢失或事件 ACK 推断任务成功。`model_configured` 仅说明平台报告已配置模型，不代表模型执行或任务通过验收。
- 平台面板不依赖旧 Registry：配置 `--exclude-node UAV-02` 后，旧载具列表可以只有 UAV-01/03，UAV-02 仍从 `/api/platform/status` 展示，不因此被判成 removed 或 failed。旧 snapshot/API 的契约保持不变。
- 首次打开从事件游标 0 只读重建；断联后从已提交的 `(store_id, seq)` 继续，按事件序号去重。同一存储的 `boot_id` 改变不清零游标；换库时将旧来源的最后确认记录单独保留，新库从 0 重建。浏览器刷新不持久化这个观测器游标，而是重新 GET 重建，不重放任何命令。
- 每轮最多取 5 页，保留最近 100 条事件的显示窗口；未追上 `checkpoint_seq/event_seq` 时显示 SYNCING，不冒充完整同步。事件页、任务 GET 和末次状态核对全部成功后才提交本轮游标和结果；请求期间换库、重启、身份不符、事件缺口、游标回退均保留最后确认结果并显示错误。
- 503 `platform_link_unavailable`、409 游标/存储冲突、404 任务记录缺失只让平台观测 stale/unknown，不将任务改成 failed，也不将旧 HTTP/Telemetry 的健康状态拿来覆盖平台状态。任务终态不被迟到的 executing 响应回退。
- `fake` 模式醒目标为“非飞行证据”；`sitl` 也不等于真机验收。该面板不提交任务，不调用 heartbeat、cancel、reconcile，不接触 Bearer token。当前采用游标 GET 对账；SSE 尚未接入，事件回补仅更新展示。

跨 Windows/Linux 部署时浏览器的 `127.0.0.1` 指向浏览器所在主机，需使用实际可达网关或同源代理。Bearer 与平台代理连接由地面 Runtime 配置；前端不直连平台代理执行器、不保存平台密钥。

### Fixture 与回归范围

`tests/fixtures/platform_autonomy_v1.json` 是 Runtime 提供的 `docs/fixtures/platform_autonomy_v1.json` 的消费端副本，保留其 `offline_fixture_not_flight_evidence` 标记。动态 boot/store/execution ID、任务响应和事件分页由 `tests/fixtures/platform-read-fixture.js` 的 `createFixture()` 合成，使用上述生产者字段，不是真实平台采样。

`tests/action-ui.test.js` 的 `installStateFixture()` 覆盖旧 API；`tests/platform-observer.test.js` 覆盖平台断联补收、重复事件、分页预算、换库、重启、缺口、身份冲突、迟到响应和 GET-only 恢复。定向运行：

```powershell
node --test tests/platform-observer.test.js tests/action-ui.test.js tests/runtime-api.test.js tests/console-model.test.js
```

这些结果属于前端消费端 fixture/unit 回归；尚不代表 SSE、真实网关/平台联调、跨线端到端或真实飞行验收。

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

- `任务规划 -> 生成请求`：调用 `/api/planner/plan-mission`。
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
