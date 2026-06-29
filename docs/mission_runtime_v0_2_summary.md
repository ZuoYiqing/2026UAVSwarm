# Mission Runtime v0.2 Summary

## 1) 本阶段目标

Mission Runtime v0.2 的目标是把 Policy Gate v0.2 的 `DEFER` / `PREEMPT` 控制面语义，最小落地为 runtime 可审计、可 replay 的状态流。

当前阶段只做：

- `running_actions` 状态输入；
- `pending_takeovers` 状态记录；
- `non_preemptible -> DEFER -> pending_takeover`；
- `phase_exit -> recheck -> admitted / activated`；
- `ttl expired -> expired / dropped`；
- audit/replay 事件顺序验证。

当前阶段不做真实飞控抢占，不做真实任务 abort/suspend/resume，不做复杂多机调度，不接 PX4/SITL，不接真实硬件，不修改 protocol / policy / adapter contract。

---

## 2) 当前状态检查

### 2.1 RunningAction 当前字段

`RunningAction` 是 runtime 内部最小运行中动作模型，当前字段为：

| 字段 | 含义 |
| --- | --- |
| `request_id` | 当前运行动作的请求 ID |
| `action_type` | 当前运行动作类型 |
| `source` | 当前动作来源，默认 `self_local` |
| `priority` | 当前动作优先级，默认 `50` |
| `non_preemptible` | 是否处于不可直接抢占阶段 |

### 2.2 PendingTakeover 当前字段

`PendingTakeover` 是 runtime 内部最小待接管模型，当前字段为：

| 字段 | 含义 |
| --- | --- |
| `takeover_id` | runtime 生成的 takeover 标识 |
| `request_id` | 原始接管请求 ID |
| `mission_id` | mission 标识 |
| `action_type` | 待接管动作类型 |
| `source` | 接管请求来源 |
| `priority` | 接管请求优先级 |
| `created_at` | pending 创建时间戳 |
| `ttl_s` | pending 有效期 |
| `status` | 当前 takeover 状态 |
| `reason_code` | 创建 pending 的 policy reason |
| `request` | runtime 内部保留的原始 `ActionRequest`，用于 phase_exit recheck |

### 2.3 当前 pending_takeover 状态

当前状态集合为：

- `pending`
- `admitted`
- `activated`
- `expired`
- `dropped`

这些状态只表示 runtime control-plane 接管流状态，不代表真实执行面已经 abort/suspend/resume 或完成飞控抢占。

---

## 3) pending_takeover 状态机

| 状态迁移 | 触发事件 / 条件 | 当前 runtime 行为 | Audit 事件 |
| --- | --- | --- | --- |
| `pending -> admitted` | `phase_exit` 后 recheck 通过 | 选中最高优先级、最早创建的 pending takeover 并标记 admitted | `pending_takeover_admitted` |
| `admitted -> activated` | admitted 后立即进入最小激活态 | 标记 activated；不执行真实任务 abort/resume | `pending_takeover_activated` |
| `pending -> expired` | pending 超过 `ttl_s` | 标记 expired | `pending_takeover_expired` |
| `expired -> dropped` | expired 后 runtime 清理 | 标记 dropped | `pending_takeover_dropped` |
| `pending -> dropped` | recheck 失败或 pending 缺失原始 request | 标记 dropped | `pending_takeover_dropped` |

说明：

- `pending -> admitted -> activated` 当前是最小控制面状态流；
- `activated` 不等于真实飞控抢占完成；
- `dropped` 表示该 takeover 不再参与后续 phase_exit 选择；
- 当前不做复杂队列调度，只按 `priority desc + created_at asc` 选择候选。

---

## 4) phase_exit 重评估流程

当前 `phase_exit` 最小流程为：

1. runtime 写入 `phase_exit` audit event；
2. runtime 调用 expired pending 清理；
3. runtime 从 `pending_takeovers` 中筛选 `status == "pending"` 且 mission 匹配的候选；
4. 按 `priority desc + created_at asc` 选择一条；
5. 使用 pending takeover 内部保留的 `ActionRequest` 重新构造 `RuntimeActionContext`；
6. 以 `phase_override="nominal"` 重新调用 policy gate；
7. recheck 结果为 `ALLOW` 或 `PREEMPT` 时，进入 `admitted -> activated`；
8. recheck 失败或缺失 request 时，进入 `dropped`。

该流程仍是 runtime control-plane recheck，不发送 adapter/backend 命令，也不接真实 PX4/SITL。

---

## 5) audit / replay 事件表

| Event type | 触发条件 | 最小字段 |
| --- | --- | --- |
| `policy_decision_event` | 每次 `handle_action_request` 调用 policy gate 后 | `request_id`, `mission_id`, `decision_code`, `primary_reason_code`, `secondary_reason_codes`, `effective_scope`, `effective_profile_id`, `policy_trace_id`, `audit_tags`, `timestamp` |
| `pending_takeover_created` | `DEFER` 被 runtime 记录为 pending takeover | `takeover_id`, `request_id`, `mission_id`, `action_type`, `source`, `priority`, `created_at`, `ttl_s`, `status`, `reason_code`, `timestamp` |
| `phase_exit` | runtime 收到 phase exit | `mission_id`, `timestamp` |
| `pending_takeover_admitted` | phase_exit recheck 通过并进入 admitted | takeover 最小字段 + `decision_code`, `timestamp` |
| `pending_takeover_activated` | admitted 后进入 activated | takeover 最小字段 + `decision_code`, `timestamp` |
| `pending_takeover_expired` | pending 超过 ttl | takeover 最小字段 + `timestamp` |
| `pending_takeover_dropped` | expired 清理、recheck 失败或 request 缺失 | takeover 最小字段 + 可选 `reason`, `decision_code`, `primary_reason_code`, `timestamp` |

Replay 当前通过 JSONL audit record 复盘事件顺序，能看到：

- `policy_decision_event -> pending_takeover_created`；
- `phase_exit -> pending_takeover_admitted -> pending_takeover_activated`；
- `pending_takeover_expired -> pending_takeover_dropped`。

---

## 6) 当前测试覆盖

`tests/integration/test_runtime_takeover_flow.py` 当前覆盖：

- `non_preemptible` running action 导致高优先级请求 `DEFER`；
- `DEFER` 后创建 `pending_takeover`；
- `pending_takeover_created` audit event 字段稳定；
- `phase_exit` 后 pending takeover 进入 `admitted -> activated`；
- audit event 顺序稳定；
- replay 可见 `pending_takeover_admitted` / `pending_takeover_activated`；
- ttl 过期后进入 `expired -> dropped`；
- `pending_takeover_expired` / `pending_takeover_dropped` audit event 顺序稳定。

当前不需要把所有 policy unit case 复制成 integration test；本轮只保留 runtime takeover 关键状态流覆盖。

---

## 7) 当前非目标

当前明确不做：

- 不做真实飞控抢占；
- 不做真实任务 `abort` / `suspend` / `resume`；
- 不做复杂调度器；
- 不做多机优化；
- 不接 PX4/SITL；
- 不接真实硬件；
- 不扩展 adapter/backend；
- 不新增 GUI；
- 不修改 protocol contract；
- 不修改 policy contract。
