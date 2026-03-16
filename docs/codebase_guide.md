# 代码导览（Codebase Guide）

## 1. 仓库目录树（当前实际）
```text
.
├── README.md
├── pyproject.toml
├── docs/
│   ├── project_summary.md
│   └── codebase_guide.md
├── src/
│   └── uav_runtime/
│       ├── __init__.py
│       ├── protocol/
│       │   ├── __init__.py
│       │   ├── enums.py
│       │   ├── schema.py
│       │   ├── codec.py
│       │   └── validation.py
│       ├── policy/
│       │   ├── __init__.py
│       │   ├── gate.py
│       │   ├── decision.py
│       │   ├── context.py
│       │   ├── profile.py
│       │   ├── delegation.py
│       │   ├── registry_refs.py
│       │   ├── preemption.py
│       │   ├── link_state.py
│       │   └── autonomy_state.py
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── gateway.py
│       │   ├── fake_adapter.py
│       │   └── mappers/
│       │       ├── __init__.py
│       │       └── canonical_mapper.py
│       ├── runtime/
│       │   ├── __init__.py
│       │   ├── __main__.py
│       │   ├── orchestrator.py
│       │   ├── event_bus.py
│       │   ├── task_queue.py
│       │   ├── mission_context.py
│       │   ├── audit_log.py
│       │   └── replay.py
│       ├── console/
│       │   ├── __init__.py
│       │   └── cli.py
│       └── skills/
│           ├── __init__.py
│           ├── base.py
│           ├── registry.py
│           ├── executor.py
│           └── builtin/
│               ├── __init__.py
│               ├── takeoff.py
│               ├── land.py
│               ├── hover.py
│               ├── goto.py
│               ├── return_home.py
│               ├── start_stream.py
│               ├── stop_stream.py
│               ├── capture_snapshot.py
│               └── broadcast_message.py
└── tests/
    ├── test_cli.py
    ├── test_gateway.py
    ├── integration/
    │   └── test_minimal_runtime_flow.py
    └── unit/
        ├── test_protocol_schema.py
        ├── test_policy_contract_shapes.py
        └── test_reason_registry_refs.py
```

---

## 2. 关键目录职责说明
- `src/uav_runtime/protocol`：定义跨层通信对象与枚举，是 contract 边界。
- `src/uav_runtime/policy`：定义决策上下文/配置/输出对象与统一裁决逻辑。
- `src/uav_runtime/runtime`：运行时编排与基础设施（事件、审计、回放）。
- `src/uav_runtime/adapters`：执行面抽象与网关，隔离下游执行实现。
- `src/uav_runtime/skills`：技能定义与执行占位。
- `src/uav_runtime/console`：CLI 入口。
- `tests`：行为与契约验证。
- `docs`：当前项目理解与导览文档。

---

## 3. 关键文件作用说明
## protocol
- `protocol/enums.py`：消息类型、决策码、来源、scope、链路状态等枚举。
- `protocol/schema.py`：`Envelope` / `ActionRequest` / `PolicyDecision` / `ActionResult` 核心数据结构。
- `protocol/validation.py`：对 envelope 的轻量校验。
- `protocol/codec.py`：消息编解码占位。

## policy
- `policy/gate.py`：`unified_policy_gate` 核心裁决函数（当前骨架版）。
- `policy/decision.py`：`PolicyDecisionEnvelope` 与 `HandoverPlan`，含 preempt 合同校验。
- `policy/context.py`：`PolicyContext` 与 `RuntimeActionContext`。
- `policy/profile.py`：`PolicyProfile` 配置结构。
- `policy/delegation.py`：`DelegationGrant` 与有效性判断。
- `policy/registry_refs.py`：decision/reason/error 注册表引用常量。

## adapters
- `adapters/gateway.py`：adapter 注册、intent 转换、幂等检查、dispatch、结果归一化。
- `adapters/fake_adapter.py`：最小可执行适配器，用于 skeleton 流程验证。
- `adapters/base.py`：adapter 协议接口（类型层约定）。

## runtime
- `runtime/orchestrator.py`：核心链路编排；policy 决策事件发布/审计；allow 时调用 gateway。
- `runtime/audit_log.py`：JSONL 追加写入。
- `runtime/replay.py`：读取最近 N 条审计记录。
- `runtime/event_bus.py`：简化事件总线。
- `runtime/task_queue.py` / `runtime/mission_context.py`：队列与上下文骨架。
- `runtime/__main__.py`：`python -m uav_runtime.runtime` 启动入口。

## console / skills
- `console/cli.py`：当前 CLI 命令解析与路由。
- `skills/*`：技能接口、注册、执行器和 builtin 占位技能。

## tests
- `tests/unit/test_protocol_schema.py`：协议对象与 preempt 合同。
- `tests/unit/test_policy_contract_shapes.py`：gate 分支形状。
- `tests/unit/test_reason_registry_refs.py`：registry ref 常量一致性。
- `tests/integration/test_minimal_runtime_flow.py`：runtime 最小闭环路径。
- `tests/test_cli.py`：CLI 当前命令可用性。
- `tests/test_gateway.py`：gateway 当前公开 API 行为。

---

## 4. 最关键执行链路
## 4.1 action_request -> policy_decision_event -> adapter -> action_result
1. 调用 `RuntimeOrchestrator.handle_action_request(req)`。
2. orchestrator 补齐 request 最小字段（`request_id`、`mission_id`、`idempotency_key` 等）。
3. 构造 `PolicyContext` 与 `RuntimeActionContext`，调用 `unified_policy_gate`。
4. 生成并发布 `policy_decision_event`，并写入 `AuditLog`。
5. 若决策为 deny/defer/require_confirm/preempt：直接返回 blocked-like 结果。
6. 若决策为 allow：通过 `AdapterGateway.execute("fake", req)` 调用 adapter。
7. gateway 做 intent/command 转换后调用 `FakeAdapter.execute`。
8. gateway 归一化后返回 action result；orchestrator 返回给调用方。

## 4.2 audit / replay 链路
1. orchestrator 将 policy 决策事件写入 `audit/runtime.audit.jsonl`（或自定义路径）。
2. CLI `replay-last` 调用 `runtime.replay.replay_last(path, n)`。
3. replay 读取文件最后 N 行并反序列化返回列表。

---

## 5. 当前 tests 在验证什么
- **契约字段级验证**：protocol schema、reason code、decision shape 命名与字段存在性。
- **分支行为级验证**：policy gate 在 allow / require_confirm / link_lost deny / preempt 合同下的输出。
- **系统最小链路验证**：runtime 集成测试覆盖 allow 与 require_confirm 两条路径及审计落盘。
- **接口对齐验证**：CLI 仅验证当前支持命令，gateway 仅验证当前 `execute(...)` API。

---

## 6. 新成员建议阅读顺序
建议按“先 contract，后流程，再细节”阅读：

1. `README.md`：先理解项目边界与目标。
2. `protocol/enums.py` + `protocol/schema.py`：理解对象与字段。
3. `policy/decision.py` + `policy/context.py` + `policy/profile.py`：理解 policy 输入输出。
4. `policy/gate.py`：理解当前裁决规则。
5. `runtime/orchestrator.py`：理解全链路拼装方式。
6. `adapters/gateway.py` + `adapters/fake_adapter.py`：理解执行面入口。
7. `runtime/audit_log.py` + `runtime/replay.py` + `console/cli.py`：理解可操作入口和审计回放。
8. `tests/`：用测试反向校验“当前真实行为”。

---

## 7. contract 驱动的核心文件
- `src/uav_runtime/protocol/schema.py`
- `src/uav_runtime/protocol/enums.py`
- `src/uav_runtime/policy/decision.py`
- `src/uav_runtime/policy/gate.py`
- `src/uav_runtime/runtime/orchestrator.py`
- `tests/unit/test_protocol_schema.py`
- `tests/unit/test_policy_contract_shapes.py`
- `tests/integration/test_minimal_runtime_flow.py`

这些文件共同定义并约束了当前 MVP 的消息、决策和执行链路契约。

---

## 8. 仍属 stub / skeleton、后续需补全的文件
1. `policy/gate.py`：大部分步骤仍是 TODO（鉴权、delegation、priority、preempt 判定、target 校验、runtime 约束）。
2. `adapters/gateway.py`：参数裁剪、限速、真实命令映射与异常模型仍简化。
3. `adapters/mappers/canonical_mapper.py`：仅占位映射。
4. `runtime/task_queue.py` / `runtime/mission_context.py`：当前仅骨架。
5. `skills/executor.py` / builtin skills：以占位实现为主，缺少真实执行语义。
6. `console/cli.py`：当前以最小可用命令路由为主，输出语义与错误处理较简化。

结论：当前仓库可作为“可测试的契约化骨架”，但距离真实无人系统控制平台还有明显工程补全工作。
