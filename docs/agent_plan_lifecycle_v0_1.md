# Agent Plan Lifecycle + Operator Approval + Plan Execution Controller v0.1

## 1. 本阶段目标

Agent Planner v0.1 已能把显式 `mission_type` 转换成 Mission Plan IR，但它只负责生成计划。Plan Lifecycle v0.1 补上 planner 与 Runtime 之间的控制层，使计划具备：

- 可验证的 lifecycle status。
- human-in-the-loop operator approval / rejection。
- dry-run / fake execution skeleton。
- step state update。
- audit/replay 可复盘事件链。

本阶段仍然不接 LLM，不做自由自然语言理解，不直接控制 PX4，不做多机，不做复杂路径规划，不做危险载荷。

## 2. 为什么需要 Plan Lifecycle

没有 lifecycle 时，`plan-mission` 只能输出一次性的 plan JSON，无法表达：

- 计划是否已经 validated。
- 哪些 step 等待人工确认。
- operator 是否 approve / reject。
- 计划是否已经开始 dry-run / fake execution。
- step 是否 running / succeeded / failed。
- 计划是否 completed / cancelled / expired。

Plan Lifecycle 让计划从“静态模板输出”变成“可审批、可推进、可审计”的控制面对象。

## 3. 边界说明

### 3.1 Plan Lifecycle 与 Mission Runtime

Plan Lifecycle 是 agent-level control-plane 状态，不是 Runtime execution 状态。它管理 MissionPlan 的审批与 dry-run/fake step progression。Mission Runtime 仍负责真实 action execution、running_actions、pending_takeovers、phase_exit、adapter 调用和 action_result。

### 3.2 Plan Execution Controller 与 RuntimeOrchestrator

PlanExecutionController v0.1 只做 dry-run/fake skeleton，不调用 `RuntimeOrchestrator.handle_action_request()`，不连接 PX4，不调用真实 adapter。后续接入 Runtime 时，每个 approved step 需要转换为 ActionRequest，并在执行前再次经过 Runtime / Policy Gate。

### 3.3 Operator Approval 与 Policy Gate

Operator Approval 是 human-in-the-loop 确认，表示操作员认可该计划可以进入下一步控制流程。它不能替代 Policy Gate：

- approval 不能把 dangerous / blocked capability 变成可执行。
- approval 不能绕过 planner precheck。
- approval 不能绕过 execution-time Policy Gate。
- 真实执行前仍必须使用实时上下文重新做 Policy Gate 检查。

### 3.4 为什么 v0.1 不直接执行真实 PX4

PX4 runtime smoke-takeoff 属于部署验证线；agent lifecycle 本阶段只补控制面生命周期。直接从 approved plan 执行 PX4 会引入飞控 session、MAVLink command、真实状态观测和安全边界耦合，不利于先把审批和审计状态收口。

## 4. Plan status

| 状态 | 触发事件 | 含义 |
| --- | --- | --- |
| `draft` | plan 初始构建前 | 预留状态，表示草稿计划 |
| `validated` | `agent_plan_validated` | plan 无 blocked / confirmation blocker，已通过 lifecycle load |
| `awaiting_confirmation` | `agent_plan_awaiting_confirmation` | 至少一个 step 需要 operator confirm |
| `approved` | `agent_plan_approved` | operator approve 后进入可 dry-run/fake execution 状态 |
| `executing` | `agent_plan_execution_started` | controller 开始 dry-run/fake 执行 |
| `completed` | `agent_plan_completed` | 所有 step 在 dry-run/fake 中 succeeded |
| `blocked` | validation / approval / execution 拒绝 | 存在 blocked/unsupported step 或 policy/capability blocker |
| `failed` | `agent_plan_step_failed` | dry-run/fake 过程中 step failed |
| `cancelled` | `agent_plan_cancelled` 或 reject | operator reject/cancel |
| `expired` | TTL/时间窗过期 | v0.1 预留状态 |

这些状态是 agent-level plan 状态，不是飞控状态，不代表飞机起飞、降落或任务完成。

## 5. Step status

| 状态 | 触发事件 | 含义 |
| --- | --- | --- |
| `pending` | 预留 / 后续排队 | step 尚未 ready |
| `ready` | planner allow / approval 后 | 可进入 dry-run/fake controller |
| `needs_operator_confirm` | Policy precheck require_confirm | 需要人工确认 |
| `running` | `agent_plan_step_started` | controller 正在推进该 step |
| `succeeded` | `agent_plan_step_succeeded` | dry-run/fake step 成功模拟 |
| `failed` | `agent_plan_step_failed` | dry-run/fake step 失败 |
| `skipped` | 后续条件跳过 | v0.1 预留 |
| `blocked` | capability/policy blocker | 不可执行，需要 replan 或处理 blocker |

## 6. Operator Approval

`PlanApproval` 最小字段：

| 字段 | 含义 |
| --- | --- |
| `approval_id` | 审批记录 ID |
| `plan_id` | 被审批的 plan |
| `operator_id` | 操作员 ID |
| `decision` | `approve` / `reject` |
| `approved_steps` | 被批准的 step 列表；为空表示全部可批准 step |
| `rejected_steps` | 被拒绝的 step 列表 |
| `reason` | 审批说明 |
| `created_at` | 审批时间 |

行为规则：

- plan 含 `needs_operator_confirm` step 时，lifecycle load 后进入 `awaiting_confirmation`。
- approve 后，plan status 变为 `approved`。
- reject 后，plan status 变为 `cancelled`。
- 如果 plan 含 blocked step，approval 不会绕过 blocker，plan 保持/进入 `blocked`。

## 7. PlanExecutionController v0.1

最小 API：

```python
controller.load_plan(plan)
controller.approve_plan(plan, approval)
controller.start_execution(plan, mode="dry_run")
controller.advance_next_step(plan, mode="dry_run")
controller.mark_step_succeeded(plan, step)
controller.mark_step_failed(plan, step)
controller.cancel_plan(plan)
```

支持 execution mode：

| mode | 行为 |
| --- | --- |
| `dry_run` | 只更新 lifecycle/step 状态，不执行 action |
| `fake` | 与 dry_run 类似，表示可用于 fake adapter 接入前的模拟 |
| `disabled` | 默认非执行模式；不启动 execution |

非 `dry_run/fake` mode 返回 `unsupported_execution_mode`。本阶段不支持真实 PX4 execution。

## 8. Final policy check required

每个 MissionPlanStep 保留 `final_policy_check_required=True` 标记。含义是：planner 阶段的 Policy Gate precheck 只是计划可行性检查；真正执行时必须由 Runtime 使用实时上下文再次调用 Policy Gate。

这条标记防止后续维护者误以为 operator approval 或 planner precheck 可以直接授权 adapter / MAVLink command。

## 9. Audit / Replay events

当前 lifecycle 事件：

| event | 触发条件 |
| --- | --- |
| `agent_plan_validated` | load_plan 后 plan validated 或 blocked |
| `agent_plan_awaiting_confirmation` | load_plan 后发现 confirm step |
| `agent_plan_approved` | operator approve |
| `agent_plan_rejected` | operator reject 或 approval 无法通过 blocker |
| `agent_plan_execution_started` | dry_run/fake execution started |
| `agent_plan_step_started` | step running |
| `agent_plan_step_succeeded` | step succeeded |
| `agent_plan_step_failed` | step failed |
| `agent_plan_cancelled` | cancel_plan |
| `agent_plan_completed` | 全部 step succeeded |

每个 event 至少包含：

- `timestamp`
- `plan_id`
- `mission_type`
- `step_id` / `action_type` if applicable
- `operator_id` if applicable
- `execution_mode`
- `status`
- `reason`

## 10. 后续接入 Runtime action execution

后续路线：

1. `PlanExecutionController` 读取 approved plan。
2. 对 next ready step 生成 ActionRequest。
3. 调用 RuntimeOrchestrator，而不是直接调用 adapter。
4. Runtime 再次调用 Policy Gate 做 execution-time final check。
5. Runtime 返回 action_result。
6. Controller 根据 action_result 更新 step status。
7. audit/replay 记录 planner、approval、runtime action_result 的完整链路。

## 11. 非目标

- 不接 LLM。
- 不做自由自然语言理解。
- 不直接执行 PX4 takeoff。
- 不直接调用真实 MAVLink。
- 不做多机。
- 不做路径规划。
- 不做视觉识别。
- 不做 GUI。
- 不做真实无人机。
- 不做危险 payload。
- 不让 approval 绕过 Policy Gate。
- 不改 protocol contract。
