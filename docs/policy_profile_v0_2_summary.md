# Policy Profile v0.2 + Fallback Action Taxonomy Summary

## 1) 本阶段目标

Policy Profile v0.2 的目标是在不修改 protocol contract、不接真实执行面的前提下，明确不同 profile 在链路退化/失联场景下的动作边界，并用最小 fallback action 白名单让 Policy Gate 能稳定输出 `allow` / `deny` / `REQUIRE_CONFIRM` / `DEFER`。

本阶段只做数据化 profile 与 fallback taxonomy，不做复杂规则引擎，不发送 MAVLink 命令，不接 PX4/SITL，不控制真实载荷。

---

## 2) 设计判断

当前 Policy Gate v0.2 已支持 command source priority、delegation、link-state shrink、preemption、risk/confirmation、reason/audit 语义。当前缺口是：`link_lost` 下 self-local fallback 的动作集合还不够明确，容易让 `goto`、peer/subcluster 控制、未知 action 或危险 payload-like action 混入失联自治边界。

Fallback taxonomy 属于 policy/profile 层，而不是 adapter/backend 层，原因是：

- fallback 是否允许是授权与安全策略问题，不是设备执行问题；
- adapter/backend 只应消费已授权的 command，并返回执行结果；
- link state、profile、risk、scope 的组合裁决必须在 Policy Gate 侧统一解释；
- 仿真器或真实硬件不应改变 fallback 白名单语义。

本阶段不依赖真实 PX4/SITL，因为所有规则都只基于 `profile + action_type + link_state + scope + risk` 做控制面裁决。

先做最小白名单，而不是复杂规则引擎，是为了先冻结失联自治边界，避免在真实飞控/载荷接入前把危险或未知动作纳入 fallback。

---

## 3) 最小 Policy Profile 表

| Profile | 定位 | link healthy | degraded | lost |
| --- | --- | --- | --- | --- |
| `conservative` | 偏保守 | 允许低风险动作 | 高风险动作 deny | 强收缩，仅 fallback，风险上限低 |
| `standard` | 默认 profile | 允许低风险常规动作 | 高风险 require_confirm | 仅 self-only fallback |
| `aggressive` | 结构占位 | 不扩大危险能力 | 仍 require_confirm / risk limited | 仍仅 fallback，受安全规则限制 |
| `lost_link` | 失联 profile | 不作为常规健康链路 profile | 可作为收缩策略参考 | 仅 self-only fallback，禁止 peer/subcluster 和 unsafe payload |

实现上 `build_policy_profile(name)` 返回以上最小 profile，profile 数据仍保持 `PolicyProfile` 结构，不修改 `ActionRequest` schema。

---

## 4) Fallback Action Taxonomy

### 4.1 flight/control fallback

| Action | lost_link profile |
| --- | --- |
| `hold_position` | allow when `self_local + self_only + low risk` |
| `return_home` | allow when `self_local + self_only + low risk` |
| `land_safe` | allow when `self_local + self_only + low risk` |
| `reduce_speed` | allow when `self_local + self_only + low risk` |
| `maintain_heading` | allow when `self_local + self_only + low risk` |

### 4.2 system/health fallback

| Action | lost_link profile |
| --- | --- |
| `health_query` | allow |
| `sensor_read` | allow |
| `report_status` | allow |

### 4.3 payload/device fallback

| Action | degraded | lost |
| --- | --- | --- |
| `light_set_state` | allow / profile risk rules | allow when low risk |
| `camera_capture` | allow / profile risk rules | allow when low risk |
| `speaker_play_message` | require_confirm candidate | not in lost-link fallback allowlist by default |

### 4.4 explicitly not fallback

The following actions are not fallback actions and are denied under lost link:

- `goto`
- `peer_control`
- `subcluster_control`
- unknown `action_type`
- `payload_release`
- `release_payload`
- `drop` / `drop_payload`
- `deploy` / `deploy_payload`
- `strike`
- `attack`

Unsafe payload-like actions are denied by policy even before adapter execution.

---

## 5) 最小行为规则

| 场景 | Decision | Reason |
| --- | --- | --- |
| `link_lost + fallback action + self_local + self_only + low risk` | `allow` | `primary_reason_code = null`, secondary includes link-lost scope restriction |
| `link_lost + non-fallback action` | `deny` | `REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED` |
| `link_lost + peer/subcluster scope` | `deny` | `REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED` |
| `degraded + high risk + standard` | `REQUIRE_CONFIRM` | `REASON_CODE_DEGRADED_CONFIRM_REQUIRED` |
| `degraded + high risk + conservative` | `deny` | `REASON_CODE_PROFILE_RISK_EXCEEDS_MAX` |
| unknown action under `lost_link` | `deny` | `REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED` |
| `payload_release` / `drop` / `strike` / `attack` / `deploy` | `deny` | `REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED` |

---

## 6) Reason code 收口

本阶段复用既有 reason code：

- `REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED`
- `REASON_CODE_DEGRADED_CONFIRM_REQUIRED`
- `REASON_CODE_LINK_LOST_SCOPE_RESTRICTED`

本阶段新增最小 reason code：

- `REASON_CODE_PROFILE_RISK_EXCEEDS_MAX`
- `REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED`

约束：

- `deny` / `defer` / `REQUIRE_CONFIRM` 必须有 `primary_reason_code`；
- `allow` 可为 `null`；
- fallback allow 路径可通过 `secondary_reason_codes` 保留 link-lost scope shrink 证据。

---

## 7) audit/replay 一致性

新增路径仍走既有 `policy_decision_event`，至少保留：

- `decision_code`
- `primary_reason_code`
- `secondary_reason_codes`
- `effective_profile_id`
- `effective_scope`
- `audit_tags`
- `policy_trace_id`

因此 audit/replay 可以解释：

- 为什么 lost-link fallback 被 allow；
- 为什么 lost-link non-fallback 被 deny；
- 为什么 degraded high-risk 被 require_confirm 或 deny；
- 为什么 unsafe payload-like action 在 policy 层提前拒绝。

---

## 8) 当前测试覆盖

`tests/unit/test_policy_profile_v2.py` 覆盖：

- `lost_link + hold_position + self_local -> allow`；
- `lost_link + return_home + self_local -> allow`；
- `lost_link + goto -> deny`；
- `lost_link + peer_control scope -> deny`；
- `standard + degraded + high risk -> REQUIRE_CONFIRM`；
- `conservative + degraded + high risk -> deny`；
- unknown action under lost link -> deny；
- `payload_release` / `drop` / `strike` / `attack` / `deploy` -> deny；
- fallback taxonomy contains only the intended minimal safe actions.

Existing Policy Gate v0.2, Mission Runtime v0.2, Payload Adapter, CLI, and PX4 readiness tests continue to run without requiring PX4/SITL or hardware.

`tests/integration/test_policy_profile_runtime_flow.py` 覆盖 runtime / audit / replay 关键路径：

- `lost_link + self_local + hold_position` 在 runtime 中 allow，`policy_decision_event` 可见 `effective_profile_id=lost_link`、`effective_scope=self_only`、`primary_reason_code=null`；
- `lost_link + self_local + goto` 在 runtime 中 deny，`primary_reason_code=REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED`，且不产生 `action_result`；
- `payload_release` 在 policy 层提前 deny，`primary_reason_code=REASON_CODE_UNSAFE_PAYLOAD_ACTION_DENIED`，不进入 PayloadAdapter 执行；
- `standard + degraded + high risk` 在 runtime 中 `REQUIRE_CONFIRM`；
- `conservative + degraded + high risk` 在 runtime 中 deny；
- replay 可读取这些 `policy_decision_event`，用于复盘 profile/fallback 裁决原因。

这些 integration 覆盖仍然是 control-plane policy 验证：fallback action 被 policy allow 不代表真实 `return_home` / `land_safe` 已实现，也不代表真实飞控动作已经执行。

---

## 9) 当前非目标

- 不实现真实 `return_home` / `land_safe`；
- 不发送 MAVLink 命令；
- 不控制真实载荷；
- 不做武器化或攻击性能力；
- 不做复杂多机决策；
- 不改 protocol contract；
- 不接 PX4/SITL；
- 不把 adapter/backend 细节写进 policy taxonomy。
