# v0.1 Demo 验收清单（demo-ready baseline）

## 1) 当前 demo 目标
将当前已跑通的最小闭环固定为可验收、可复现、可展示输入：

`submit-action -> runtime -> policy_decision_event -> fake adapter(按分支可执行) -> action_result -> audit -> replay`

范围仅限当前 v0.1 baseline：
- 不改核心 contract
- 不改 policy 语义
- 不新增消息类型
- 不接 PX4 / MAVLink / ROS2

---

## 2) 必须通过的 3 条演示路径

### Path A: ALLOW（正常通过）
**输入命令**
```bash
python -m uav_runtime.console.cli submit-action hover --mission-id demo-a --risk-hint 1 --pretty
```

**必须看到的关键输出字段**
- `result.accepted = true`
- `result.status = "accepted"`
- `policy_decision_event.decision_code = "allow"`
- `policy_decision_event.effective_scope = "self_only"`
- `policy_decision_event.policy_trace_id` 非空

---

### Path B: DENY（高风险拒绝）
**输入命令**
```bash
python -m uav_runtime.console.cli submit-action goto --mission-id demo-b --risk-hint 5 --demo-link-state lost --pretty
```

**必须看到的关键输出字段**
- `result.accepted = false`
- `result.status = "blocked"`
- `result.code = "REASON_CODE_RISK_LEVEL_EXCEEDED"`
- `policy_decision_event.decision_code = "deny"`
- `policy_decision_event.primary_reason_code = "REASON_CODE_RISK_LEVEL_EXCEEDED"`
- `policy_decision_event.effective_scope = "self_only"`

---

### Path C: REQUIRE_CONFIRM（等待确认）
**输入命令**
```bash
python -m uav_runtime.console.cli submit-action goto --mission-id demo-c --require-confirm --pretty
```

**必须看到的关键输出字段**
- `result.accepted = false`
- `result.status = "waiting_confirmation"`
- `result.code = "REASON_CODE_CONFIRMATION_REQUIRED"`
- `policy_decision_event.decision_code = "REQUIRE_CONFIRM"`
- `policy_decision_event.primary_reason_code = "REASON_CODE_CONFIRMATION_REQUIRED"`
- `policy_decision_event.policy_trace_id` 非空

---

## 3) Replay 验收
**输入命令**
```bash
python -m uav_runtime.console.cli replay-last --pretty
```

**必须看到的关键字段（最近记录中）**
- `type = "policy_decision_event"` 的事件
- 至少包含：`request_id`, `decision_code`, `effective_scope`, `policy_trace_id`
- 若存在 allow 路径，还应出现 `type = "action_result"` 且与对应 `request_id` 可对齐

---

## 4) 失败标准（任一触发即不通过）
1. 命令执行后终端无输出或输出非 JSON。
2. 路径 A/B/C 的关键字段缺失。
3. reason code 漂移（不再是当前正式命名）。
4. decision_code 与路径预期不一致。
5. DENY 路径出现执行成功结果（应不执行 adapter）。
6. replay 里找不到对应 request_id 的决策事件，或 action_result 与 request_id 对不上。

---

## 5) 当前实现状态说明（命名混用）
当前实现存在 decision_code 大小写风格并存：
- 枚举路径：`allow/deny/preempt`（小写）
- 非枚举分支：`REQUIRE_CONFIRM/DEFER`（大写）

这属于当前实现状态，不在本轮重构范围。

**后续收敛建议（文档建议，非本轮改动）**
- 在后续单独 patch 中统一 decision_code 命名风格，并同步 tests 与文档。
