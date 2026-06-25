# Project Onboarding and Team Handoff Guide

## 1) 本文目标

这份文档用于把本项目教给完全不了解代码的新成员，并把后续工作拆成可分工、可验收、可交接的模块。

阅读顺序建议：先理解系统边界，再跑通 CLI，再看协议/策略/运行时/adapter，最后再按个人分工深入对应模块。不要一开始就尝试接真实 PX4、真实相机或真实载荷。

---

## 2) 一句话理解项目

本项目是一个无人系统控制面 / runtime skeleton：

```text
ActionRequest
-> Policy Gate
-> RuntimeOrchestrator
-> AdapterGateway
-> fake / mavlink / payload / px4_sitl backend skeleton
-> action_result
-> audit / replay
```

核心价值不是“马上控制真实飞机”，而是先把以下能力做稳定：

- 请求结构稳定；
- 策略裁决可解释；
- adapter/backend seam 清晰；
- readiness 诊断明确；
- audit/replay 可复盘；
- action/capability 边界可查看；
- dangerous action 明确禁止。

---

## 3) 新人第一天：只跑命令，不改代码

### 3.1 建立环境

```bash
python -m pip install -e .
```

如需要 SITL optional dependency，再使用：

```bash
python -m pip install -e .[sitl]
```

默认学习阶段不要求 PX4、pymavlink、真实网络或真实硬件。

### 3.2 跑全量测试

```bash
python -m pytest -q
```

如果这个命令失败，先不要改业务逻辑，先记录：

- Python 版本；
- 当前 git commit；
- 失败测试名；
- 完整错误输出；
- 是否缺依赖。

### 3.3 查看 capability manifest

```bash
python -m uav_runtime.console.cli list-capabilities --pretty
```

查看 forbidden/dangerous 边界：

```bash
python -m uav_runtime.console.cli list-capabilities --include-dangerous --pretty
```

学习重点：

- `supported_adapters` 只是 skeleton/metadata，不代表真实硬件已接入；
- `fallback_allowed=true` 需要硬件线后续重点确认；
- `dangerous=true` 只作为禁止项记录，不是采购或开发目标。

### 3.4 跑一个最小 action

```bash
python -m uav_runtime.console.cli submit-action hover --pretty
```

再跑 payload skeleton：

```bash
python -m uav_runtime.console.cli submit-action health_query --adapter payload --pretty
```

学习重点：输出里同时看：

- `result`；
- `policy_decision_event`；
- `adapter`；
- `code`；
- `execution_trace`。

---

## 4) 新人第二天：按文件读代码

建议按以下顺序读，不要跳着从 PX4 或 payload 开始。

### 4.1 Protocol / schema

入口文件：

- `src/uav_runtime/protocol/schema.py`
- `src/uav_runtime/protocol/enums.py`

理解点：

- `ActionRequest` 是 runtime 输入；
- `action_type` / `requested_scope` / `priority_hint` 是 canonical 字段；
- legacy 字段仍保留兼容，但不是长期主入口；
- 当前不修改 protocol contract。

### 4.2 Policy Gate

入口文件：

- `src/uav_runtime/policy/gate.py`
- `src/uav_runtime/policy/profile.py`
- `src/uav_runtime/policy/fallback_actions.py`
- `src/uav_runtime/policy/action_registry.py`
- `docs/skill_group_taxonomy.md`

理解点：

- Policy Gate 只做控制面裁决；
- 不发送 MAVLink；
- 不连接 payload；
- DENY / DEFER / REQUIRE_CONFIRM / PREEMPT 必须有 reason code；
- lost_link 下只允许 self_local + self_only + fallback allowlist；
- unsafe payload-like action 先在 policy 层拒绝。
- `skill_group` 是能力通道 / 策略分组，不是可执行 skill。

### 4.3 Runtime

入口文件：

- `src/uav_runtime/runtime/orchestrator.py`
- `src/uav_runtime/runtime/mission_context.py`
- `src/uav_runtime/runtime/audit_log.py`
- `src/uav_runtime/runtime/replay.py`

理解点：

- Runtime 负责串联 Policy Gate、AdapterGateway、audit/replay；
- pending_takeover 是 runtime control-plane 状态；
- phase_exit 后会重评估 pending takeover；
- 当前不做真实飞控抢占、不做复杂调度器。

### 4.4 Adapter / Backend

入口文件：

- `src/uav_runtime/adapters/gateway.py`
- `src/uav_runtime/adapters/fake_adapter.py`
- `src/uav_runtime/adapters/mavlink_adapter.py`
- `src/uav_runtime/adapters/payload_adapter.py`
- `src/uav_runtime/adapters/px4_sitl_backend.py`

理解点：

- Gateway 把已获准的 request 转成 adapter command；
- fake adapter 是稳定测试基线；
- mavlink adapter 当前仍是 skeleton；
- payload adapter 只做非破坏性设备 placeholder；
- px4_sitl_backend 当前只做 readiness / heartbeat probe，不发送 arm/set_mode/takeoff。

---

## 5) 新人第三天：按测试理解行为

建议按以下顺序跑和读测试：

```bash
python -m pytest tests/unit/test_action_registry.py -q
python -m pytest tests/unit/test_policy_gate_v2.py -q
python -m pytest tests/unit/test_policy_profile_v2.py -q
python -m pytest tests/unit/test_payload_adapter.py -q
python -m pytest tests/unit/test_px4_sitl_backend.py -q
python -m pytest tests/integration/test_minimal_runtime_flow.py -q
python -m pytest tests/integration/test_policy_profile_runtime_flow.py -q
python -m pytest tests/integration/test_runtime_takeover_flow.py -q
```

读测试时不要只看 assert，要理解每个测试保护什么边界：

- registry 一致性；
- policy reason code 稳定；
- lost_link fallback；
- dangerous action 拒绝；
- payload placeholder result；
- px4_sitl readiness code；
- runtime audit/replay；
- pending_takeover 状态流。

---

## 6) 建议团队分工

### 6.1 负责人 A：Protocol / Contract / Schema

负责范围：

- `src/uav_runtime/protocol/*`
- contract shape tests；
- ActionRequest / ActionResult 字段稳定性；
- 与文档中的 contract 说明保持一致。

交付物：

- 不破坏已冻结 protocol contract；
- 所有字段变更必须有迁移说明；
- 补充 contract tests；
- 审核其他人是否误改 schema。

不负责：

- 不接硬件；
- 不写 adapter vendor SDK；
- 不把硬件字段塞进 protocol。

### 6.2 负责人 B：Policy Gate / Profile / Reason Codes

负责范围：

- `src/uav_runtime/policy/gate.py`
- `src/uav_runtime/policy/profile.py`
- `src/uav_runtime/policy/fallback_actions.py`
- `src/uav_runtime/policy/action_registry.py`
- policy unit tests。

交付物：

- allow / deny / require_confirm / defer / preempt reason 稳定；
- lost_link / degraded / recovering 行为稳定；
- unsafe action 永远禁止；
- 新规则必须先写测试；
- reason code 不出现同义重复。

不负责：

- 不实现真实 MAVLink 命令；
- 不在 adapter 中绕过 policy。

### 6.3 负责人 C：Runtime / Mission Flow / Audit Replay

负责范围：

- `src/uav_runtime/runtime/orchestrator.py`
- `src/uav_runtime/runtime/mission_context.py`
- `src/uav_runtime/runtime/audit_log.py`
- `src/uav_runtime/runtime/replay.py`
- runtime integration tests。

交付物：

- policy_decision_event 字段稳定；
- action_result 字段稳定；
- pending_takeover 状态流稳定；
- audit/replay 可复盘；
- CLI submit-action 输出可解释。

不负责：

- 不直接控制硬件；
- 不把复杂调度器一次性做完。

### 6.4 负责人 D：Adapter / Backend / PX4 SITL Readiness

负责范围：

- `src/uav_runtime/adapters/gateway.py`
- `src/uav_runtime/adapters/mavlink_adapter.py`
- `src/uav_runtime/adapters/mavlink_mapping.py`
- `src/uav_runtime/adapters/px4_sitl_backend.py`
- PX4 readiness docs/tests。

交付物：

- fake / mavlink / px4_sitl 路径不互相破坏；
- readiness code 语义稳定；
- backend_connected 只表示 heartbeat/probe 成功；
- 不发送 arm/set_mode/command_long/takeoff，除非进入明确 smoke 阶段并单独评审。

不负责：

- 不定义 policy 权限；
- 不修改 protocol contract。

### 6.5 负责人 E：Payload / Device / Hardware Inventory

负责范围：

- `src/uav_runtime/adapters/payload_adapter.py`
- `src/uav_runtime/adapters/payload_mapping.py`
- `docs/hardware_capability_mapping_template.md`
- `docs/payload_device_adapter_plan.md`
- payload tests。

交付物：

- 非破坏性 payload skeleton 稳定；
- camera/gimbal/speaker/light/sensor/health_monitor 接口清点；
- 硬件模块映射到 capability registry；
- forbidden/dangerous action 不进入采购目标。

不负责：

- 不做危险载荷；
- 不接真实设备，除非已有 bench-test 任务和隔离测试计划。

### 6.6 负责人 F：CLI / Docs / Demo / Training

负责范围：

- `src/uav_runtime/console/cli.py`
- `docs/*`
- README / demo runbook / onboarding；
- 演示脚本和培训材料。

交付物：

- 每个新功能有最小 CLI 或测试入口；
- 文档能被新人按步骤复现；
- demo 不依赖真实硬件；
- 输出 JSON 可读、可截图、可审计。

不负责：

- 不改 policy 语义；
- 不绕过 runtime 直接调用 adapter。

---

## 7) 推荐学习节奏

### 第 1 周：共同基础

- 所有人跑通 `python -m pytest -q`；
- 所有人跑通 `list-capabilities`；
- 所有人读 `ActionRequest`、`Policy Gate`、`RuntimeOrchestrator`；
- 每个人认领一个模块并讲 10 分钟。

### 第 2 周：按模块深入

- A 负责 contract 讲解；
- B 负责 policy reason 演示；
- C 负责 audit/replay 演示；
- D 负责 PX4 SITL readiness 演示；
- E 负责 hardware capability mapping；
- F 负责 CLI/docs/demo 串联。

### 第 3 周：小任务闭环

每个人完成一个小 PR：

- 只改自己模块；
- 必须有测试或文档验证；
- 不改 protocol contract；
- 不接真实硬件；
- 不新增危险能力；
- PR 描述必须写清楚测试命令。

---

## 8) 新人常见误区

| 误区 | 正确理解 |
| --- | --- |
| `backend_connected` 表示能飞 | 只表示最小连接/heartbeat probe 成功 |
| payload adapter 返回 ok 表示真实相机拍照 | 当前只是 placeholder result |
| list-capabilities 是执行入口 | 它只是只读 manifest |
| dangerous action 在 registry 中出现表示要开发 | 它们是禁止项，用来明确边界 |
| Policy Gate 应该知道硬件 SDK | 硬件细节属于 adapter/backend seam 或 hardware mapping |
| DEFER 会自动真实抢占 | 当前只是 runtime pending_takeover 状态流 |
| 改 CLI 就可以绕过 policy | submit-action 必须走 RuntimeOrchestrator 和 Policy Gate |

---

## 9) PR 与代码修改规则

1. 先跑相关单测，再跑全量测试；
2. 新增 reason code 必须有测试；
3. 修改 ActionRequest / ActionResult 前必须先评审；
4. adapter 不能新增策略拒绝逻辑；
5. policy 不能写硬件厂商 SDK 细节；
6. docs 中说“已支持”时必须区分 skeleton / readiness / real hardware；
7. dangerous action 不得进入 supported adapter mapping；
8. 所有 runtime 行为都应能通过 audit/replay 解释。

---

## 10) 最小验收命令

每个成员提交前至少运行与自己模块相关的命令。跨模块变更必须跑全量。

```bash
python -m pytest tests/unit/test_action_registry.py -q
python -m pytest tests/unit/test_policy_gate_v2.py -q
python -m pytest tests/unit/test_policy_profile_v2.py -q
python -m pytest tests/unit/test_payload_adapter.py -q
python -m pytest tests/unit/test_px4_sitl_backend.py -q
python -m pytest tests/integration/test_minimal_runtime_flow.py -q
python -m pytest tests/integration/test_policy_profile_runtime_flow.py -q
python -m pytest tests/integration/test_runtime_takeover_flow.py -q
python -m pytest tests/test_cli.py -q
python -m pytest -q
```
