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
- 选择 UAV 后，Check Backend、Smoke Takeoff 和 Land 请求携带该节点的 `node_id`、endpoint、`system_id` 和 `component_id`。
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
POST /api/actions/smoke-takeoff
POST /api/actions/land
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

推荐请求示例：

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
  "connect_timeout_ms": 5000,
  "command_timeout_ms": 10000,
  "observe_timeout_ms": 25000,
  "threshold_ratio": 0.7,
  "auto_land": false
}
```

关键返回要求：

- `check-backend` 返回 `readiness` 或 `connect_probe.code`。
- `smoke-takeoff` 返回 `policy_decision`、`arm_ack`、`takeoff_ack`、`land_ack`、`max_altitude_m`、`altitude_observation.last_z`、`threshold_reached`、`result`。
- `replay` 返回最近审计事件数组。

## 当前已接入的按钮

- `任务规划 -> 生成请求`：调用 `/api/planner/plan-mission`。
- `Adapter / Backend -> Check Backend`：调用 `/api/backend/check`。
- `Adapter / Backend -> Smoke Takeoff`：调用 `/api/actions/smoke-takeoff`。
- `Adapter / Backend -> Land`：调用 `/api/actions/land`。
- `Audit / Replay -> 刷新事件`：调用 `/api/events?n=30`。

## 前端验证

```powershell
npm run check
npm test
```

`console-model.js` 是可独立测试的数据映射层，负责合并多机快照、判断动作权限和构造带
MAVLink identity 的请求。浏览器页面不直接连接 MAVLink、Gazebo Transport 或 DDS。

接口失败时页面会显示明确的 OFFLINE 或 HTTP 错误状态。静态页面仍可浏览，但 Smoke Takeoff 和 Land 在 Runtime API 或 PX4 Backend 未就绪时会被禁用。
