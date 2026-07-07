# Runtime HTTP Bridge v0.1

## 1. 目标

Runtime HTTP Bridge v0.1 为本地前端 `frontend/swarm-console` 提供最小 REST API，把浏览器请求映射到现有 uav_runtime 能力：backend check、smoke-takeoff、land、plan-mission、replay 和 capabilities。

它是本地开发 bridge，不是新的 Runtime，不是公网服务，也不是 shell command proxy。

## 2. 为什么需要 HTTP bridge

浏览器前端不适合直接调用 CLI：

- 浏览器不能安全地执行本机 shell command。
- CLI 输出/错误处理不适合作为稳定前端 API contract。
- 直接把命令行暴露给浏览器容易引入任意命令执行风险。
- 前端需要 JSON API、CORS、稳定路由和明确的安全边界。

HTTP bridge 只暴露固定 allowlist 路由，每个路由调用已有 Python API，不接受任意 shell command。

## 3. 边界

### 3.1 与 Runtime / Policy

HTTP bridge 不绕过 Runtime / Policy Gate。`smoke-takeoff` 和 `land` 路由先走 RuntimeOrchestrator 的 Policy Gate helper，再调用 PX4 SITL backend 的 action guard。

### 3.2 与 Planner

`/api/planner/plan-mission` 只调用 Intent Router + Template Agent Planner，返回 PlanResult JSON。它不执行 action，不调用 PX4，不调用 adapter。

### 3.3 与 PX4 Backend

PX4 相关 HTTP 路由只面向 SITL 本地开发。`backend_mode != "sitl"` 时，`smoke-takeoff` 和 `land` 必须拒绝，不允许真实无人机控制。

### 3.4 本地开发服务

本阶段只用于本地前端联调，默认监听 `127.0.0.1:8765`。不要将它作为公网服务部署；公网部署需要认证、授权、TLS、审计隔离和更严格的网络策略。

## 4. 启动方式

后端：

```bash
python -m uav_runtime.http.server
```

或使用等价的 Python 入口启动本地 server。当前实现使用 stdlib HTTP server，不要求 FastAPI / uvicorn 依赖。

前端：

```bash
cd frontend/swarm-console
npm run dev
```

前端 API Base URL：

```text
http://127.0.0.1:8765/api
```

## 5. CORS

允许的本地开发 origin：

- `http://localhost:5178`
- `http://127.0.0.1:5178`
- `http://localhost:5173`
- `http://127.0.0.1:5173`

不默认允许公网任意 origin。

## 6. 路由列表

| Method | Path | 用途 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/backend/check` | PX4 SITL backend readiness check |
| `POST` | `/api/actions/smoke-takeoff` | SITL-only smoke takeoff |
| `POST` | `/api/actions/land` | SITL-only land |
| `POST` | `/api/planner/plan-mission` | dry-run mission plan |
| `GET` | `/api/replay?n=20` | 最近 audit/replay events |
| `GET` | `/api/capabilities` | Capability manifest |

## 7. 请求示例

### GET /api/health

响应：

```json
{
  "status": "ok",
  "service": "uav_runtime_http_bridge",
  "version": "0.1",
  "mode": "local_dev"
}
```

### POST /api/backend/check

```json
{
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "backend_enabled": true,
  "transport_endpoint": "udpin:127.0.0.1:14540",
  "connect_timeout_ms": 5000
}
```

`transport_endpoint` 会原样保留；不要把 `udpin:127.0.0.1:14540` 改写成 `udp://127.0.0.1:14540`。

### POST /api/actions/smoke-takeoff

```json
{
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "backend_enabled": true,
  "transport_endpoint": "udpin:127.0.0.1:14540",
  "altitude_m": 3.0,
  "connect_timeout_ms": 5000,
  "command_timeout_ms": 10000,
  "observe_timeout_ms": 25000,
  "threshold_ratio": 0.7,
  "auto_land": true
}
```

### POST /api/actions/land

```json
{
  "backend": "px4_sitl",
  "backend_mode": "sitl",
  "backend_enabled": true,
  "transport_endpoint": "udpin:127.0.0.1:14540",
  "command_timeout_ms": 10000
}
```

### POST /api/planner/plan-mission

```json
{
  "mission_type": "inspection_snapshot",
  "source": "ground_station",
  "profile": "standard",
  "dry_run": true
}
```

### GET /api/capabilities

默认隐藏 dangerous action：

```text
GET /api/capabilities?domain=payload
GET /api/capabilities?adapter=mavlink
GET /api/capabilities?fallback_only=true
```

只有显式指定时才显示 forbidden metadata：

```text
GET /api/capabilities?include_dangerous=true
```

## 8. WSL / Windows 访问注意事项

如果后端在 WSL 中运行，前端在 Windows 浏览器中运行：

- 优先尝试 `http://127.0.0.1:8765/api`。
- 如访问失败，检查 WSL 端口转发、防火墙和浏览器 CORS 报错。
- PX4 endpoint 仍使用 MAVLink 验证过的 `udpin:127.0.0.1:14540`。

## 9. 安全边界

- HTTP bridge 不接受任意 shell command。
- 不暴露真实硬件控制。
- `smoke-takeoff` / `land` 只允许 SITL。
- dangerous payload action 不开放为 action route。
- `plan-mission` 只 dry-run，不执行。
- capabilities 默认隐藏 dangerous action。
- action route 仍经过 Runtime / Policy Gate。
- 不绕过 policy。
- 不修改 protocol contract。

## 10. 非目标

- 不做公网部署。
- 不做认证系统。
- 不做 GUI 重写。
- 不接真实无人机。
- 不做多机。
- 不做 websocket telemetry。
- 不做复杂任务执行。
- 不做危险 payload。
- 不允许浏览器传 shell command。
- 不绕过 Policy Gate。
- 不改 protocol contract。
