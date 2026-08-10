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

## 后续接入点

- `runtime-api.js` 是前端到 runtime HTTP 服务的唯一适配层。
- `app.js` 启动时自动调用 `/api/health`，并显示 `连接中 / LIVE / OFFLINE`。
- 静态总览数据保留作 DEMO，但飞行动作不会在后端离线时伪装成成功。
- `simulation-3d/` 是独立的 CesiumJS 场景，后续通过 vehicle snapshot 契约嵌入主控制台。
- `Policy Gate`、`Adapter / Backend`、`Audit / Replay` 页面字段按当前 Python runtime 的 contract 设计。

## Runtime API 配置

默认 API 地址：

```text
http://127.0.0.1:8765/api
```

`8765` 是 WSL/Python `uav_runtime_http_bridge` 的 HTTP 端口，不是前端页面端口，也不是 MAVLink 端口。`/api` 是该服务的固定路由前缀；PX4 SITL 的 MAVLink 数据仍使用 `udpin:127.0.0.1:14540`。

可在页面 `Adapter / Backend -> Runtime API 与传输端点 -> Runtime API Base URL` 中修改，配置会保存到浏览器 `localStorage`。

顶部状态栏显示：

- `Runtime API 连接中`：页面正在探测 `/api/health`。
- `Runtime API LIVE`：浏览器可以访问 HTTP bridge。
- `Runtime API OFFLINE`：HTTP bridge 未启动、地址错误或请求超时。
- `数据源 DEMO`：页面仍在显示静态演示指标。
- `数据源 LIVE PARTIAL`：事件、动作结果等已由真实 Runtime API 部分覆盖。
- `数据源 CACHED`：Runtime API 已断开，页面保留的是最近一次真实数据快照。

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
```

推荐请求示例：

```json
{
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "backend_enabled": true,
  "transport_endpoint": "udpin:127.0.0.1:14540",
  "altitude_m": 3,
  "connect_timeout_ms": 5000,
  "command_timeout_ms": 10000,
  "observe_timeout_ms": 25000,
  "threshold_ratio": 0.7,
  "auto_land": false
}
```

后端可先把这些 HTTP 请求映射到现有 CLI/runtime 能力：

- `/api/backend/check` -> `check-backend`
- `/api/actions/smoke-takeoff` -> `smoke-takeoff`
- `/api/planner/plan-mission` -> `plan-mission`
- `/api/replay` -> `replay-last`
- `/api/capabilities` -> `list-capabilities`

最小返回要求：

- `check-backend` 返回 `readiness` 或 `connect_probe.code`。
- `smoke-takeoff` 返回 `policy_decision`、`arm_ack`、`takeoff_ack`、`land_ack`、`max_altitude_m`、`altitude_observation.last_z`、`threshold_reached`、`result`。
- `replay` 返回最近审计事件数组。

## 当前已接入的按钮

- `任务规划 -> 生成请求`：调用 `/api/planner/plan-mission`。
- `Adapter / Backend -> Check Backend`：调用 `/api/backend/check`。
- `Adapter / Backend -> Smoke Takeoff`：调用 `/api/actions/smoke-takeoff`。
- `Adapter / Backend -> Land`：调用 `/api/actions/land`。
- `Audit / Replay -> 播放`：调用 `/api/replay?n=20`。

接口失败时页面会显示明确的 OFFLINE 或 HTTP 错误状态。静态页面仍可浏览，但 Smoke Takeoff 和 Land 在 Runtime API 或 PX4 Backend 未就绪时会被禁用。
