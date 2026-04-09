# 标准演示场景说明（v0.1 demo-ready）

## A) 正常通过场景（ALLOW）
**输入命令**
```bash
python -m uav_runtime.console.cli submit-action hover --mission-id demo-a --risk-hint 1 --pretty
```

**预期 decision_code**
- `allow`

**预期 primary_reason_code**
- `null` / 不要求

**预期状态**
- `accepted`

**预期是否执行 adapter**
- 是（应产生 `action_result`）

**预期 replay 结果**
- 可看到同一 `request_id` 下的 `policy_decision_event` + `action_result`

---

## B) 高风险拒绝场景（DENY）
**输入命令**
```bash
python -m uav_runtime.console.cli submit-action goto --mission-id demo-b --risk-hint 5 --demo-link-state lost --pretty
```

**预期 decision_code**
- `deny`

**预期 primary_reason_code**
- `REASON_CODE_RISK_LEVEL_EXCEEDED`

**预期状态**
- `blocked`

**预期是否执行 adapter**
- 否（deny 路径不应产生对应 `action_result`）

**预期 replay 结果**
- 有 `policy_decision_event`，`effective_scope = self_only`
- `secondary_reason_codes` 包含 `REASON_CODE_LINK_LOST_SCOPE_RESTRICTED`

---

## C) REQUIRE_CONFIRM 场景
**输入命令**
```bash
python -m uav_runtime.console.cli submit-action goto --mission-id demo-c --require-confirm --pretty
```

**预期 decision_code**
- `REQUIRE_CONFIRM`

**预期 primary_reason_code**
- `REASON_CODE_CONFIRMATION_REQUIRED`

**预期状态**
- `waiting_confirmation`

**预期是否执行 adapter**
- 否（等待确认阶段不执行 adapter）

**预期 replay 结果**
- 有 `policy_decision_event`，包含 `policy_trace_id`
- `effective_scope = self_only`

---

## 补充说明：当前 decision_code 命名状态
当前演示输出中存在大小写并存（`allow/deny` 与 `REQUIRE_CONFIRM`）。
这是当前实现状态，后续如需统一，建议在独立 patch 里与 tests 一起收敛。
