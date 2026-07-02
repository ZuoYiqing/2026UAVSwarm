# Policy Gate v0.2 Summary (Contract / Reason / Audit-Replay Consistency)

## 1) 范围与边界

本阶段是 **Policy Gate 控制面裁决增强**，不是执行面扩展：
- 不修改 protocol contract；
- 不修改 adapter/backend contract；
- 不接 PX4/SITL 真连接；
- 不新增 GUI；
- 不实现真实飞控动作（arm/set_mode/takeoff）。

---

## 2) v0.2 已支持规则（当前实现）

1. **Command source priority / preemption**
   - `ground_station` / `higher_command` > `cluster_head` > `delegated_peer` > `self_local`；
   - 高优先级可抢占低优先级；
   - non-preemptible phase -> `DEFER`；
   - reverse hierarchy -> `DENY`。

2. **Delegation rule**
   - `delegated_peer` 在非 `self_only` scope 下必须有 delegation；
   - delegation 过期/撤销/目标不匹配 -> `DENY`。

3. **Link-state shrink**
   - `lost`：scope 收缩为 `self_only`；
   - `lost` 且非 `self_local` 来源 -> `DENY`；
   - `degraded` 高风险 -> `REQUIRE_CONFIRM`；
   - `recovering`（flag/phase）-> `DEFER`。

4. **Risk / confirm**
   - 风险超过阈值 -> `DENY`；
   - 命中确认路径 -> `REQUIRE_CONFIRM`；
   - `ALLOW` 路径可无 `primary_reason_code`。

---

## 3) reason code 收口（v0.2 使用集）

### 3.1 已使用 reason code
- `REASON_CODE_CONFIRMATION_REQUIRED`
- `REASON_CODE_RISK_LEVEL_EXCEEDED`
- `REASON_CODE_LINK_LOST_SCOPE_RESTRICTED`
- `REASON_CODE_DELEGATION_REQUIRED`
- `REASON_CODE_DELEGATION_INVALID`
- `REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED`
- `REASON_CODE_PREEMPT_NON_PREEMPTIBLE`
- `REASON_CODE_PREEMPT_REVERSE_HIERARCHY_DENIED`
- `REASON_CODE_PREEMPT_GRANTED`
- `REASON_CODE_DEGRADED_CONFIRM_REQUIRED`
- `REASON_CODE_RECOVERING_DEFER`

### 3.2 主因约束
- `DENY` / `DEFER` / `REQUIRE_CONFIRM` / `PREEMPT` 必须有 `primary_reason_code`；
- `ALLOW` 可为 `null`。

> 注：运行时在非 ALLOW 路径已有主因缺失保护（contract violation）。

---

## 4) policy_decision_event / audit / replay 一致性

当前 runtime 产出的 `policy_decision_event` 至少包含：
- `decision_code`
- `primary_reason_code`
- `secondary_reason_codes`
- `effective_scope`
- `effective_profile_id`
- `policy_trace_id`
- `handover_plan`
- `audit_tags`

这使得 v0.2 裁决路径可在 audit/replay 中解释“为什么 allow/deny/defer/require_confirm/preempt”。

---

## 5) 测试覆盖状态

### 5.1 Unit（已覆盖）
- source priority / preempt / reverse hierarchy；
- delegation missing / invalid；
- link_lost 非 fallback deny；
- link_lost self fallback allow；
- degraded require_confirm；
- non-preemptible defer；
- high-risk deny；
- require_confirm reason 稳定。

### 5.2 Integration（本轮补关键路径）
- delegated_peer 无 delegation：runtime 链路拒绝且审计可见 reason；
- link_lost 非 fallback 来源：runtime 链路拒绝且审计可见 reason；
- require_confirm 路径：runtime 输出 reason 稳定（已存在）。

---

## 6) 非目标（当前不做）

- 完整抢占执行流程编排（执行器级）；
- 多机协同优化算法；
- 真实飞控动作控制；
- PX4/SITL 环境联调扩展。
