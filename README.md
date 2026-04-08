# UAV Runtime (MVP Skeleton)

## 1) 项目简介
`uav-runtime` 是一个面向无人机/无人系统任务执行的 **运行时骨架（runtime skeleton）**。它聚焦于“控制面决策 + 执行面适配 + 审计回放”的最小闭环，而不是完整飞控系统。

它当前**是**：
- 一个以 `ActionRequest -> policy decision -> adapter execute -> audit/replay` 为主链路的 Python MVP。
- 一个用于冻结协议字段命名、决策接口形状和最小测试契约的工程基础。

它当前**不是**：
- 不是普通聊天 Agent（目标不是对话体验）。
- 不是直接输出飞控底层协议帧的控制器（目前只有 fake adapter skeleton）。
- 不是桌面自动化工具（没有 GUI/RPA 目标）。

---

## 2) 当前目标
当前 MVP 的目标是：
1. 固化最小协议对象与决策对象（`Envelope`、`ActionRequest`、`PolicyDecisionEnvelope`、`ActionResult`）。
2. 固化单一 policy 裁决入口（`unified_policy_gate`）并让 orchestrator 严格消费其结果。
3. 提供可运行的执行路径（通过 `AdapterGateway + FakeAdapter` 完成最小执行）。
4. 提供基础审计与回放能力（JSONL append + replay）。

当前完成度（按代码与测试现状）：
- skeleton 主链路已跑通。
- 核心 contract 命名已在测试中对齐（包括 `REASON_CODE_CONFIRMATION_REQUIRED`、`REASON_CODE_RISK_LEVEL_EXCEEDED`、`REASON_CODE_LINK_LOST_SCOPE_RESTRICTED` 等 reason code，以及 decision shape / protocol schema）。
- CLI 已提供最小入口命令集用于验证流程。

---

## 3) 核心设计原则
1. **LLM 不直接输出飞控协议帧**  
   上层只产生结构化请求（如 `ActionRequest`），具体执行命令由 adapter 层映射。

2. **控制面与执行面分离**  
   policy 做“能否执行”的裁决；adapter 做“如何执行”的下沉映射。

3. **`unified_policy_gate` 是唯一裁决入口**  
   运行时在执行前统一进入该 gate，输出标准化 `PolicyDecisionEnvelope`。

4. **canonical protocol_json 的作用**  
   `ActionRequest` 内 canonical 字段（如 `action_type`、`requested_scope`、`priority_hint`）是对外契约主入口；legacy alias 仅用于迁移兼容。

5. **adapter gateway 的作用**  
   `AdapterGateway` 负责：请求转执行意图、幂等检查、命令构造、adapter 调用、结果归一化。

6. **audit / replay 的作用**  
   所有关键决策事件可写入本地 JSONL 审计日志；`replay_last` 用于读取最近事件，支持问题复盘与后续可观测性扩展。

---

## 4) 系统分层
- **protocol (`src/uav_runtime/protocol`)**  
  枚举、schema dataclass、编解码与基础校验。

- **runtime (`src/uav_runtime/runtime`)**  
  orchestrator、事件总线、任务队列、审计写入、回放读取。

- **policy (`src/uav_runtime/policy`)**  
  policy context/profile/decision 结构与 `unified_policy_gate` 统一裁决逻辑。

- **skills (`src/uav_runtime/skills`)**  
  内建技能注册与执行骨架（如 `takeoff`、`land`、`goto` 等占位技能）。

- **adapters (`src/uav_runtime/adapters`)**  
  适配器网关与 fake adapter，并包含 `mavlink` stub（仅 contract 占位，尚未接真实 SITL/PX4）；承接执行层抽象。

- **console (`src/uav_runtime/console`)**  
  最小 CLI 入口（提交动作、查看状态/审计、回放）。

- **tests (`tests`)**  
  单元与集成测试，覆盖协议字段、policy shape、gateway/cli 对齐与最小运行时流程。

---

## 5) 当前核心消息与对象
- **Envelope**  
  通用消息封套，包含 `message_type / trace_id / mission_id / payload / timestamp` 等。

- **ActionRequest**  
  动作请求对象；canonical 字段为主契约，legacy 字段保留迁移兼容。

- **PolicyDecisionEnvelope**  
  policy 层权威决策输出，包含 `decision_code / primary_reason_code / effective_scope / handover_plan` 等。

- **ActionResult**  
  执行结果对象（状态、代码、消息、时间戳与兼容字段）。

- **DelegationGrant**  
  委派授权对象，提供有效期与撤销状态判断。

- **PolicyProfile**  
  策略配置对象（风险阈值、确认规则、并发限制及扩展行为配置）。

- **PolicyContext**  
  policy 决策上下文（source/scope/link_state + mission/runtime 状态信息）。

---

## 6) 当前已实现内容（基于仓库现状）
- 已完成可运行的 **MVP skeleton**：
  - `RuntimeOrchestrator` 串联 policy -> adapter -> audit。
  - `AdapterGateway` 支持注册 adapter、执行调用与结果归一化。
  - `FakeAdapter` 提供最小可执行下游。
  - `MavlinkAdapter` 提供未接入状态 stub（默认 `exec_unavailable`）。

- contract 与 tests 已对齐（当前仓库内测试集）：
  - protocol schema 与 policy decision 形状测试。
  - policy gate 的 allow / require_confirm / deny / preempt 合同形状测试。
  - gateway 与 CLI 的当前 API 对齐测试。
  - 最小 runtime 集成流（allow 与 require_confirm 路径）。

- 当前 `pytest` 通过范围：
  - `tests/unit/*`
  - `tests/integration/*`
  - `tests/test_cli.py`
  - `tests/test_gateway.py`

---

## 7) 当前未做 / 后续计划
1. **从 fake adapter 向真实 adapter 演进**  
   增加真实执行后端、异常分类、重试策略和超时控制。

2. **PX4 SITL / MAVLink 接入**  
   在 adapter 层增加真实协议映射与仿真联调，不在 policy 层耦合底层帧细节。

3. **更完整 CLI / audit / replay 展示**  
   增强状态查询、过滤、结构化展示与回放分析能力。

4. **更完整仿真与控制台**  
   增加更贴近任务态的仿真场景、可视化控制台和多机协作观测面。

---

## 8) 如何运行
### 环境
- Python 3.10+

### 安装依赖
```bash
pip install -e .[dev]
```

### 运行测试
```bash
pytest -q
```

### CLI 最小用法
```bash
# 提交动作
python -m uav_runtime.console.cli submit-action takeoff

# 查看状态（骨架返回）
python -m uav_runtime.console.cli show-status

# 查看审计（骨架返回）
python -m uav_runtime.console.cli show-audit

# 回放最近审计
python -m uav_runtime.console.cli replay-last
```


### Demo 最小闭环（v0.1）
推荐按 `docs/demo_runbook.md` 的 3 条路径执行：ALLOW / DENY / REQUIRE_CONFIRM，然后用 `replay-last` 回放审计。

当前支持命令：
- `submit-mission`
- `submit-action <action>`
- `show-status`
- `show-audit`
- `replay-last`

---


### 推荐阅读顺序
建议按以下顺序阅读：`README.md -> docs/codebase_guide.md -> docs/project_summary.md -> tests/`。

## 9) 项目状态
- **阶段**：MVP skeleton / contract-freeze early stage。
- **适合**：
  - 作为控制面-执行面分层架构的开发基线。
  - 作为协议字段与策略裁决契约的对齐基准。
  - 作为后续真实飞控适配（SITL/MAVLink）前的验证底座。
- **不适合**：
  - 直接用于生产飞行任务。
  - 作为完整飞控替代品。
  - 作为复杂 UI 控制台或通用 Agent 产品。

> 结论：本仓库当前定位是“可测试、可演进的运行时骨架”，不是“功能完备的无人机控制系统”。
