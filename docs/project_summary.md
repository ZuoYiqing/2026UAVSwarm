# 项目当前总结（Project Summary）

## 1. 项目目标
当前项目目标是构建一个无人系统任务执行 Runtime 的 MVP 骨架，验证以下主链路在工程上可落地：

1. 上游输入 `ActionRequest`。
2. 经 `unified_policy_gate` 输出结构化 `PolicyDecisionEnvelope`。
3. 在允许路径下经 `AdapterGateway` 下发到 adapter 执行。
4. 输出统一化的 `ActionResult` 形态，并记录审计事件，支持回放。

该目标是“控制面 + 执行面 + 审计面”的最小闭环，不是生产级飞控系统。

---

## 2. 当前阶段定位
当前阶段属于 **MVP skeleton / contract 冻结早期**：

- 已有可运行代码与测试覆盖，能够证明关键对象与关键路径形状稳定。
- 大量模块仍是 skeleton（含 TODO），侧重接口边界和契约一致性。
- 执行面仍以 `FakeAdapter` 为主，未接入真实飞控后端。

---

## 3. 已完成的关键工作
1. **协议对象骨架已建立**：`Envelope`、`ActionRequest`、`PolicyDecision`、`ActionResult` 等 dataclass 已实现并有基础校验与兼容字段策略。
2. **策略裁决主入口已统一**：`unified_policy_gate` 作为唯一 policy 裁决入口，产出 `PolicyDecisionEnvelope`。
3. **运行时主链路已打通**：`RuntimeOrchestrator` 已实现 request -> policy -> gateway -> result 的流程分发。
4. **适配器网关已具备最小职责**：包含注册、幂等检查、command 构造、dispatch、结果归一化。
5. **审计/回放基础能力已存在**：JSONL append + replay last-n。
6. **CLI 最小命令集已可运行**：支持 `submit-mission` / `submit-action` / `show-status` / `show-audit` / `replay-last`。
7. **测试已对齐当前契约命名**：包括 reason code 冻结命名、policy shape、runtime 最小流程、gateway/cli 当前 API。

---

## 4. 当前技术主线
当前技术主线可以概括为：

- **contract-first skeleton**：优先冻结协议字段和裁决输出形状。
- **policy-first control plane**：所有执行请求先进入统一 gate 判定。
- **adapter abstraction**：执行面通过 gateway 隔离，不让上层直接绑定底层协议。
- **auditable runtime**：每次 policy 决策形成可追踪事件，支持最小回放。

这条主线有利于后续将 fake 执行替换为 SITL/真实协议执行，同时减少对上层 contract 的扰动。

---

## 5. 当前系统分层
### protocol 层
- 定义枚举、消息封装、请求/结果/决策对象、编解码与基本校验。

### policy 层
- 定义上下文（`PolicyContext`）、配置（`PolicyProfile`）、决策对象（`PolicyDecisionEnvelope`）与统一决策入口（`unified_policy_gate`）。

### runtime 层
- 由 orchestrator 串联 policy、adapter 与审计；并提供 event bus、task queue、audit log、replay 等 runtime 组件。

### adapters 层
- `AdapterGateway` 封装执行入口与归一化；`FakeAdapter` 提供最小可执行实现；mappers 目录保留映射扩展位。

### skills 层
- 技能基类、注册器、执行器与内置技能占位实现（takeoff/land/goto 等）。

### console 层
- 提供面向运行时的最小 CLI 命令入口。

### tests 层
- 覆盖协议对象、policy shape、runtime 最小集成路径、CLI/gateway 当前 API 一致性。

---

## 6. 当前关键 contract / protocol / policy / tests 状态
## contract / protocol
**当前已实现**
- `ActionRequest` 支持 canonical 字段并保留 legacy alias 兼容，`__post_init__` 进行主字段回填。
- `PolicyDecisionEnvelope` 支持 `decision_code + primary_reason_code + handover_plan` 形态，且 PREEMPT 合同有显式校验。
- reason code 命名已切换并在测试中固定为 `REASON_CODE_*`。

**当前未实现或仍简化**
- protocol validation 仍是轻量级（并非严格 schema registry 驱动）。
- 兼容字段仍存在，尚未进入“完全去 alias”阶段。

## policy
**当前已实现**
- `unified_policy_gate` 已具备最低可用分支：ALLOW / DENY / REQUIRE_CONFIRM，并处理 link lost 场景下 scope 收缩。

**当前未实现或仍简化**
- 鉴权、时效、delegation 完整检查、source priority、preemption 判定、target 验证、runtime 约束等多数环节仍是 TODO。

## tests
**当前已实现**
- 单测：协议结构、policy 形状、reason/registry refs、gateway、cli。
- 集成：runtime 最小 allow / require_confirm 双路径。
- 当前全量 pytest 已通过（17 tests）。

---

## 7. 当前 MVP 的能力边界
**能做的**
- 接收动作请求并形成结构化 policy 决策。
- 在允许路径下走 gateway -> fake adapter，返回统一结果结构。
- 写入 policy 决策审计事件并回放最近记录。
- 通过 CLI 快速触发最小流程。

**不能做的（当前未覆盖）**
- 真实飞控执行（PX4/MAVLink）与硬件闭环。
- 完整的权限体系、冲突仲裁、preemption 编排。
- 完整可观测控制台、长生命周期任务调度与多机协同控制。

---

## 8. 当前遗留问题与技术债
1. **TODO 密度高**：policy/gateway 多处仅保留占位注释。
2. **执行面真实性不足**：仅 fake adapter，无法验证真实协议映射风险。
3. **contract 双轨并存**：canonical 与 legacy alias 并行，长期需收敛。
4. **审计深度有限**：当前主要记录 policy_decision_event，尚缺更细粒度执行事件与错误分类。
5. **CLI 偏骨架**：命令可用但输出/参数/错误路径尚简化。
6. **文档到实现映射仍需持续维护**：后续每次 contract 变更需同步测试与文档。

---

## 9. 下一阶段建议路线（按优先级）
### P0（应优先）
1. **补齐 policy TODO 的最小可用版本**：先做 identity/ttl/idempotency/delegation/risk 分支可执行实现。
2. **扩展 adapter 错误模型与超时策略**：让 `ActionResult` 的失败可分类、可追踪。
3. **强化审计闭环**：补充 action_result 级事件记录与 replay 查询维度。

### P1（次优先）
1. **引入真实 adapter PoC**（先 SITL，再真实链路）：保持 gateway 接口不变，替换 fake 后端。
2. **收敛 contract 兼容字段策略**：明确 legacy alias 退场路径。
3. **扩展集成测试**：覆盖 deny/defer/preempt 与幂等冲突路径。

### P2（后续）
1. CLI 与控制台增强（结构化展示、过滤、统计）。
2. 多机/任务编排层能力扩展。
3. 与外部注册表/配置中心集成。

---

## 10. 当前哪些内容已适合写论文/专利草案
> 这里指“可作为草案素材”，不是“已形成可申请文本”。

1. **架构方法层面**
   - “控制面（policy gate）与执行面（adapter gateway）分离”的运行时架构。
   - “contract-first + skeleton-first”的无人系统软件迭代策略。

2. **流程与接口层面**
   - `ActionRequest -> PolicyDecisionEnvelope -> AdapterCommand -> ActionResult` 的规范化消息流。
   - 可审计事件驱动的最小闭环（policy decision event + replay）。

3. **工程治理层面**
   - 通过 tests 固化命名与接口形状（reason code、decision branch、cli/gateway API）的方法。

**尚不适合单独成稿的部分**
- 真实飞控接入性能与安全结论（当前缺数据）。
- 大规模协同调度效果（当前无对应实现与实验）。
