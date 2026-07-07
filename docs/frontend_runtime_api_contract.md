# Frontend Runtime API Contract

## 1. 前端位置和启动

前端本地路径：

```text
frontend/swarm-console
```

Windows 本地示例：

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console
npm run dev
```

默认 Runtime API Base URL：

```text
http://127.0.0.1:8765/api
```

## 2. 后端启动

```bash
python -m uav_runtime.http.server
```

服务健康检查：

```text
GET http://127.0.0.1:8765/api/health
```

## 3. 前端页面字段对应

| 前端能力 | HTTP API |
| --- | --- |
| Runtime API Base URL | `http://127.0.0.1:8765/api` |
| LIVE API / MOCK FALLBACK | 前端根据 `/api/health` 是否成功决定 |
| Check Backend | `POST /api/backend/check` |
| Smoke Takeoff | `POST /api/actions/smoke-takeoff` |
| Land | `POST /api/actions/land` |
| Telemetry 显示 | v0.1 暂不提供 websocket telemetry，可显示 action_result / replay |
| Action Result JSON | action route response |
| 最近动作记录 | `GET /api/replay?n=20` |
| Capability 列表 | `GET /api/capabilities` |
| Mission Plan | `POST /api/planner/plan-mission` |

## 4. SITL-only 约束

前端可以展示 Smoke Takeoff / Land 按钮，但后端只允许：

```json
{
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "backend_enabled": true
}
```

如果 `backend_mode` 不是 `sitl`，后端返回拒绝结果，不会执行真实 PX4/MAVLink command。

## 5. Capability dangerous 默认隐藏

`GET /api/capabilities` 默认不返回 dangerous actions。只有用于审计/说明时，前端才应显式调用：

```text
GET /api/capabilities?include_dangerous=true
```

即使显示 dangerous metadata，也不代表这些 action 可执行。

## 6. Replay

```text
GET /api/replay?n=20
```

如果 audit 文件不存在，返回空数组 `[]`，前端应显示“暂无记录”而不是错误。

## 7. 非目标

- 前端不直接调用 CLI。
- 前端不传 shell command。
- 不做公网部署。
- 不接真实无人机。
- 不做 websocket telemetry。
- 不开放 dangerous payload action。
