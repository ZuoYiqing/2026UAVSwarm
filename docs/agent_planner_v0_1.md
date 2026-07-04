# Intent Router + Template Agent Planner v0.1

## 1. 本阶段目标

本阶段新增一个 **plan-only / dry-run** 的 agent planning 层，用来把受控任务意图转换为结构化、可解释、可校验的 Mission Plan IR。

目标链路：

```text
mission_type / mission_intent
-> Intent Router
-> Template Agent Planner
-> Mission Plan IR
-> Capability Registry validation
-> Policy precheck
-> plan_result
-> audit/replay
```

本阶段不执行 action，不连接 PX4，不调用 adapter，不发送 MAVLink，也不接 LLM。

## 2. 为什么现在需要 Intent Router + Template Planner

现有系统已经具备：

- Capability Registry：描述 action 元数据、风险、adapter 支持和 dangerous 边界。
- Policy Gate / Profile / Fallback：给出 allow / deny / require_confirm / defer 等控制面裁决。
- Mission Runtime：负责 action 执行状态、pending_takeover、phase_exit 和 audit/replay。
- PX4 SITL backend：验证了 backend_connected、minimal takeoff smoke 和 runtime smoke-takeoff。

缺口在于：上层 operator / CLI / 外部系统给出“任务类型”后，还缺一个受控、可解释、可测试的 plan-only 层，把任务类型展开成 action steps，并在执行前做 capability 与 policy 预检查。

## 3. 为什么 v0.1 不直接引入大模型

v0.1 不做自由自然语言理解，原因是：

- 当前最需要的是稳定、可审计的模板计划，而不是开放式意图猜测。
- LLM 不应直接决定或执行 action，更不能绕过 Capability Registry、Policy Gate、Operator Confirm 或 Runtime。
- 受支持的 mission_type 数量很少，确定性模板比自由规划更容易测试和复盘。
- 对未知 mission_type 必须返回 unsupported / blocked，不能猜测。

不加大模型时，“意图识别”由 operator / CLI / 上层系统显式指定 `mission_type`。系统只做有限路由与模板展开。

## 4. 边界说明

### 4.1 Planner 与 Runtime

Planner 只生成 Mission Plan IR 和 dry-run plan_result。Runtime 才负责真实 action 执行、running_actions、pending_takeovers、phase_exit、adapter 调用与 action_result。

### 4.2 Planner 与 Policy Gate

Planner 可以调用 Policy Gate 做 precheck，但 precheck 不等于最终执行授权。真正执行时 Runtime 必须再次调用 Policy Gate，并使用当时的实时上下文。

### 4.3 Planner 与 PX4 backend

Planner 不发送 MAVLink，不启动 GCS heartbeat，不 ARM，不 TAKEOFF，不 LAND，也不创建 PX4 adapter session。PX4 backend 只在 Runtime 执行阶段使用。

## 5. Mission Plan IR

### MissionIntent

| 字段 | 含义 |
| --- | --- |
| `intent_id` | 本次意图 ID |
| `mission_type` | 显式任务类型，不是自由文本 |
| `source` | operator / CLI / 上层系统来源 |
| `objective` | 人类可读目标说明 |
| `constraints` | 计划约束，v0.1 只保留结构 |
| `requested_profile` | 用于 policy precheck 的 profile |
| `dry_run` | v0.1 固定为 plan-only 语义 |

### MissionPlan

| 字段 | 含义 |
| --- | --- |
| `plan_id` | 计划 ID |
| `intent_id` | 对应 MissionIntent |
| `mission_type` | 任务类型 |
| `steps` | MissionPlanStep 列表 |
| `status` | ready / blocked |
| `explanation` | 计划解释 |
| `created_at` | 创建时间 |

### MissionPlanStep

| 字段 | 含义 |
| --- | --- |
| `step_id` | 步骤 ID |
| `action_type` | 对应 Capability Registry action |
| `params` | 模板参数 |
| `expected_adapter` | registry 中的首选 adapter；没有则为空 |
| `required_capability` | capability metadata 快照 |
| `risk_level` | registry 风险级别 |
| `fallback_allowed` | 是否 fallback allowed |
| `policy_precheck` | Policy Gate dry-run precheck 结果 |
| `status` | ready / needs_operator_confirm / dry_run_only / blocked / unsupported |

### PlanResult

| 字段 | 含义 |
| --- | --- |
| `result` | ready / blocked |
| `failure_reason` | blocked 原因 |
| `plan` | MissionPlan 或 null |
| `validation_summary` | capability validation 汇总 |
| `policy_summary` | policy precheck 汇总 |

## 6. 支持的 mission_type

| mission_type | 模板步骤 | 说明 |
| --- | --- | --- |
| `simple_takeoff_land` | `takeoff` -> `land` | 最小飞行闭环计划；仍只是 dry-run plan |
| `inspection_snapshot` | `takeoff` -> `report_status` -> `camera_capture` -> `land` | 最小巡检拍照模板 |
| `status_only` | `health_query` -> `sensor_read` -> `report_status` | 不涉及飞行动作的状态模板 |
| `safe_stop` | `land_safe` | 安全停止模板；当前可能是 dry_run_only |
| `fallback_hold` | `hold_position` | fallback hold 模板 |

未知 mission_type 返回 `blocked` / `unsupported_mission_type`，不做猜测。

## 7. Capability validation

每个 step 必须查询 Capability Registry：

- action_type 是否存在；未知 action 进入 unsupported / blocked。
- dangerous=True 的 action 在 plan 阶段直接拒绝。
- supported_adapters 为空时可进入 plan，但标注 `dry_run_only`。
- registry 数据本阶段不修改。
- dangerous action 不允许进入任何默认模板。

## 8. Policy precheck

每个非 dangerous / 非 unknown step 做 Policy Gate precheck，记录：

- `decision_code`
- `primary_reason_code`
- `secondary_reason_codes`
- `effective_profile_id`
- `effective_scope`
- `policy_trace_id`
- `audit_tags`

规则：

- `deny` step 导致 plan_result=`blocked`。
- `require_confirm` step 标注 `needs_operator_confirm`。
- `allow` step 标注 `ready`，如果没有 adapter 支持则标注 `dry_run_only`。
- precheck 不等于最终执行授权。

## 9. CLI 示例

```bash
python -m uav_runtime.console.cli plan-mission \
  --mission-type inspection_snapshot \
  --source ground_station \
  --profile standard \
  --dry-run \
  --pretty
```

输出 JSON 至少包含：

- `result`
- `plan.plan_id`
- `plan.mission_type`
- `plan.steps`
- `validation_summary`
- `policy_summary`

## 10. Audit / Replay

`plan-mission` 写入 `agent_plan_created` audit event，字段包括：

- `mission_type`
- `plan_id`
- `source`
- `profile`
- `dry_run`
- `step_count`
- `blocked_steps`
- `require_confirm_steps`
- `result`

该事件用于 replay 看到计划生成顺序，但不代表 action 已执行。

## 11. 安全边界

本阶段明确不做：

- 不接 LLM。
- 不做自由自然语言理解。
- 不执行 PX4 takeoff。
- 不调用 adapter。
- 不做多机。
- 不做路径规划。
- 不做视觉识别。
- 不做 GUI。
- 不做真实无人机。
- 不做 dangerous payload。
- 不让 LLM 或 Planner 直接发 MAVLink。
- 不改 protocol contract。

## 12. 后续 LLM Intent Parser 接入方式

后续可以增加 LLM Intent Parser，但只能作为 proposal 层：

```text
free text
-> LLM proposes mission_type / params
-> operator confirm or deterministic validation
-> Intent Router
-> Template Planner
-> Capability validation
-> Policy precheck
-> Runtime / Policy Gate final authorization
```

LLM 不能直接生成可执行 adapter command，不能绕过 Capability Registry，不能绕过 Policy Gate，不能绕过 Runtime，也不能绕过 operator confirmation。
