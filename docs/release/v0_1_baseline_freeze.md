# v0.1 Baseline Freeze

## 1. 目的与适用范围
本文档定义当前仓库的 **v0.1 baseline 冻结面**，用于后续两天内的 demo 闭环交付与回归基线管理。

适用范围：
- `src/uav_runtime/**`
- `tests/**`
- `README.md` 与 `docs/**`

原则：本冻结文档以“当前真实代码 + 当前测试行为”为准。

---

## 2. 冻结项（Freeze Items）
以下内容在 v0.1 阶段视为冻结，不做随意语义改写；如需改动，需先提交变更提案并同步 tests。

### 2.1 Envelope 字段（冻结）
`protocol.schema.Envelope` 当前字段集合与语义冻结：
- `message_type`, `protocol_version`, `schema_id`, `message_id`, `trace_id`
- `correlation_id`, `causation_id`, `mission_id`
- `source`, `target`, `timestamp`, `ttl`, `payload`
- `audit_ref`, `replay_ref`

### 2.2 MVP 消息子集（冻结）
`protocol.enums.MessageType` 当前 MVP 消息子集冻结为：
- `ACTION_REQUEST`
- `POLICY_DECISION_EVENT`
- `ACTION_RESULT`

### 2.3 policy_decision_event 形状（冻结）
`RuntimeOrchestrator` 产出的 `policy_decision_event` 关键字段与语义冻结：
- `type`, `request_id`, `mission_id`
- `decision_code`, `primary_reason_code`, `secondary_reason_codes`
- `effective_scope`, `effective_profile_id`, `effective_risk_level`
- `enforced_constraints`, `handover_plan`, `policy_trace_id`, `audit_tags`, `timestamp`

### 2.4 requested_scope / effective_scope 语义（冻结）
- `requested_scope`：请求侧意图（来自 `ActionRequest`）
- `effective_scope`：policy 裁决后的最终生效 scope（可收缩，不保证等于 requested）

### 2.5 risk_hint / effective_risk_level 区分（冻结）
- `risk_hint`：请求输入风险提示（request-side hint）
- `effective_risk_level`：policy 决策中实际采用/计算后的风险等级（decision-side effective value）

### 2.6 reason / error / decision registry 命名（冻结）
- registry 引用前缀保持：
  - `registry://decision/`
  - `registry://reason/`
  - `registry://error/`
- 当前 reason code 命名以现有实现与测试为准：
  - `REASON_CODE_CONFIRMATION_REQUIRED`
  - `REASON_CODE_RISK_LEVEL_EXCEEDED`
  - `REASON_CODE_LINK_LOST_SCOPE_RESTRICTED`
  - `REASON_CODE_PREEMPT_REQUIRED`（PREEMPT 场景测试）
- 当前 decision 分支保持：
  - 枚举：`allow / deny / preempt`
  - gate 非枚举分支：`REQUIRE_CONFIRM / DEFER`

### 2.7 PREEMPT 约束（冻结）
`PolicyDecisionEnvelope.validate_preempt_contract` 约束冻结：
- 当 `decision_code == PREEMPT` 时，`handover_plan.mode` 不能为 `none`。

---

## 3. v0.1 必测项（Required Tests）
发布 v0.1 前，以下测试集合必须通过：

1. 协议/合同层
   - `tests/unit/test_protocol_schema.py`
   - `tests/unit/test_policy_contract_shapes.py`
   - `tests/unit/test_reason_registry_refs.py`

2. 接口对齐层
   - `tests/test_cli.py`
   - `tests/test_gateway.py`

3. 最小链路集成层
   - `tests/integration/test_minimal_runtime_flow.py`

建议命令：
```bash
pytest -q
```

---

## 4. 当前最小闭环（Demo Baseline）
v0.1 最小闭环定义为：

1. 通过 CLI 触发 `submit-action`。
2. Runtime 构建 policy context 并进入 `unified_policy_gate`。
3. 产出并记录 `policy_decision_event`（audit JSONL）。
4. allow 路径进入 `AdapterGateway.execute(...)`。
5. 通过 `FakeAdapter.execute(...)` 完成最小执行。
6. 返回标准化 action result。
7. 可通过 `replay-last` 读取最近审计记录。

该闭环是 v0.1 演示与回归的唯一基线闭环。

---

## 5. 当前非目标（Out of Scope）
v0.1 baseline 明确非目标：

- ROS2 接入
- GUI 控制台
- 多机协同控制逻辑扩展
- 真实飞控链路接入（PX4/MAVLink/厂商 SDK）
- 国产板卡/平台迁移
- 大规模新架构重构

---

## 6. 变更纪律（Change Discipline）
- 非必要不改 frozen contract；如确需修改，先提交“冲突说明 + 变更提案 + 测试修订计划”。
- 优先变更范围：文档、测试、CLI 入口、fake adapter、audit/replay 可演示性。
- 所有变更以 `pytest -q` 全通过作为合入前置条件。

---

## 7. 版本说明
- 文档版本：`v0.1-baseline-freeze`
- 状态：`active`
- 用途：release baseline / demo 回归基线 / 后续扩展评审输入
