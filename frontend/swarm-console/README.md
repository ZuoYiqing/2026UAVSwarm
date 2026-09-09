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

正式 `HOLD` 尚无 Runtime route。页面仅在非 Smoke TAKEOFF 的 `completion_evidence` 确认稳定高度后显示“起飞时曾确认高度稳定”，不是持续保持证明；当前飞行状态以实时遥测为准。正式 `GOTO/HOLD/RETURN_HOME` 要等 Runtime 契约和真实验收后再开放。

本轮动作功能依赖 Runtime PR #76 的 lifecycle 1.1 契约；基线旧服务缺少该接口时禁用正式动作。
主控制台不修改坐标，校验三维子应用既有快照契约后原样转发。Runtime/Simulation 的场景标识即使一致，Cesium 实际加载地图仍需独立确认。

浏览器回归可单独运行 `npm run dev:fixture-runtime`，仅监听 `127.0.0.1:8876`。
将控制台 API 改为 `http://127.0.0.1:8876/api` 可测试状态；该服务完全不连接 PX4，测试完成必须恢复 `http://127.0.0.1:8765/api`。
该静态 SPA 没有构建步骤；`npm run check` 为语法检查。真实四模块验收结果与 fixture 测试必须分开记录。

接口失败时页面会显示明确的 OFFLINE、STALE 或 HTTP 错误状态。静态页面仍可浏览，但 Runtime API、动作生命周期接口或目标 PX4 Backend 未就绪时，正式动作会被禁用。
