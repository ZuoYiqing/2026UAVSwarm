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
| Runtime API availability | `GET /api/health`; a failed health check is reported as Runtime unavailable |
| Check Backend | `POST /api/backend/check` |
| Smoke Takeoff | `POST /api/actions/smoke-takeoff` |
| Land | `POST /api/actions/land` |
| Telemetry 显示 | `GET /api/telemetry/latest` and `GET /api/vehicle-snapshot` are implemented polling APIs |
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

## 8. Read-only console APIs added in v0.1

The backend now exposes a small set of read-only console APIs so the frontend can
consume Runtime-owned Skills, Policy, Audit/Replay, and Recent Actions without
triggering PX4 or adapter execution.

| 前端页面 | HTTP API | 数据来源 | 说明 |
| --- | --- | --- | --- |
| Audit / Replay / Timeline | `GET /api/events?n=50` | audit/replay JSONL | 返回统一 `EventEnvelope`，旧 audit 字段缺失时用 derived/default 补齐。 |
| Adapter/Backend 最近动作 | `GET /api/actions/recent?n=20` | audit action events | 返回 `ActionResultView`，用于最近动作列表和 action result 展示。 |
| Policy Gate | `GET /api/policy/decisions?n=20` | audit `policy_decision_event` | 返回 `PolicyDecisionView`，保留 decision code、reason、profile、scope、audit tags。 |
| Skills 能力库 | `GET /api/skills` | Capability Registry | 返回 `SkillManifest`，默认隐藏 dangerous action。 |

`GET /api/capabilities` 仍保留为原始 capability inventory / 兼容接口；新
`GET /api/skills` 是更适合控制台卡片展示的 projection，包含 display name、
input/output schema、usage 默认值和 safety metadata。

## 9. 字段来源和安全语义

- `/api/events`、`/api/actions/recent`、`/api/policy/decisions` 的真实来源是
  runtime audit/replay 文件；缺失的 ID、node、duration、risk 等字段可由后端生成
  fallback 或返回 `null`。
- `/api/skills` 的真实来源是 Action / Capability Registry；`usage.total_calls`
  等调用统计在 v0.1 中是 default/derived，后续可接入真实 metrics。
- ViewModel 只用于前端展示，不等于执行授权。
- 所有真实 action 仍必须通过 Runtime / Policy Gate。
- HTTP API 不接受任意 shell command。
- `smoke-takeoff` 和 `land` 仍是 SITL-only。
- dangerous action 默认隐藏；即使 `include_dangerous=true` 展示 forbidden
  metadata，也不代表可执行。

## 10. Later console APIs

以下接口仍属于后续聚合阶段，不在本轮实现完整实时数据：

- `GET /api/runtime/pipeline`
- `WS /api/telemetry/stream`

## 11. Read-only realtime state API v0.1

The console may poll these local Runtime endpoints without opening MAVLink,
Gazebo Transport, or DDS connections in the browser:

| Route | Source | Offline behavior |
| --- | --- | --- |
| `GET /api/telemetry/latest` | per-node telemetry cache owned by the Runtime vehicle registry | registered nodes remain present and are marked stale/unavailable |
| `GET /api/snapshot` | thread-safe runtime state composition | stable object with null/empty unsupported fields |
| `GET /api/vehicle-snapshot` | cached telemetry projected to the Cesium vehicle contract | `full_state: true`; registered stale vehicles remain until explicitly unregistered |
| `GET /api/agent/status` | directly stored Template Planner/lifecycle state | `latest_plan: null`, no fabricated metrics |
| `GET /api/simulation/status` | independent Gazebo evidence only | `status: unknown`, `evidence: []` |

PX4 heartbeat proves PX4/MAVLink reachability, not Gazebo health. Until Runtime
owns a Gazebo clock/world/model probe, simulation status remains unknown. The
Registry defaults to the manifest endpoints `14540/14541/14542`. Each node has
one shared MAVLink session/RX owner; command ACK and telemetry are dispatched
inside Runtime instead of using competing receivers.

## 12. Multi-Vehicle Runtime v0.1.1 Hardening

HTTP rejects unsupported backend identity and invalid numeric boundaries before
PX4 execution. Response and audit identity comes from the resolved vehicle, not
browser labels. Full snapshots retain stale nodes and use authoritative scenario
poses for never-observed nodes; only unregister removes a node. Snapshot tests
load the frontend-owned JSON Schema directly when that main-branch artifact is
available and never modify or duplicate it.
