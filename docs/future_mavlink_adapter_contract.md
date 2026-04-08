# Future MAVLink / SITL Adapter Design Contract（v0.1 baseline 后续设计）

> 状态：设计说明（Design-Only）
>
> 日期：2026-04-03
>
> 范围：用于指导下一阶段最小 MAVLink/SITL adapter 接入，不包含真实协议实现代码。

> 进展：仓库已新增 `mavlink` adapter stub（仅 contract 占位，默认 `exec_unavailable`，未接真实 MAVLink/PX4/SITL）。

---

## 1. 背景与目标

当前基线已经具备：
- 控制面（policy / orchestrator）与执行面（adapter）分层；
- gateway 负责将 `ActionRequest -> execution intent -> adapter command`；
- fake adapter 已覆盖 `success / fail / timeout / delay` 语义；
- adapter result 在 gateway/orchestrator 侧被标准化后返回控制面。

本设计目标：
- 证明未来接入 MAVLink/SITL 时，不需要修改控制面 contract；
- 将 MAVLink 细节隔离在 adapter 内部，不污染控制面协议字段；
- 定义下一阶段“最小可实现”边界，降低一次性集成风险。

非目标：
- 本文不引入真实 PX4 连接；
- 不涉及 ROS2、多机编队、复杂任务编排。

---

## 2. 当前 fake adapter contract 回顾（作为未来兼容基线）

### 2.1 Adapter 输入（来自 gateway command）

当前 adapter 执行入口为：
- `adapter.execute(command: dict[str, Any]) -> dict[str, Any]`

其中 `command` 由 gateway 统一构造，核心形态：
- `command.command`：动作名（目前等同 action_type）
- `command.arguments`：参数字典
- `command.meta`：原始 intent（包括 request_id、skill_group、risk_hint 等）
- 可选 `command._simulate`：fake 语义控制（fail/timeout/delay）

### 2.2 Adapter 输出（raw result）

fake adapter 已形成最低返回语义：
- `accepted: bool`
- `code: str`
- `message: str`
- `detail: str`
- `adapter: str`
- `evidence_ref: str | None`
- `execution_trace: dict | None`

其中：
- timeout -> `accepted=False`, `code=exec_timeout`
- fail -> `accepted=False`, `code=exec_failed`
- success -> `accepted=True`, `code=exec_ok`

这组字段已被 gateway/orchestrator 正常消费并映射为控制面结果。

---

## 3. Future MAVLink adapter 的定位

future `mavlink` adapter 应被定义为：

1. **执行面插件（adapter plugin）**
   - 与 `fake` adapter 同层级注册；
   - 输入仍然是 gateway command，而不是直接暴露控制面 request。

2. **协议细节封装层（protocol boundary）**
   - 负责 command 到 MAVLink/PX4 动作的内部翻译；
   - 负责会话、超时、重试、应答解析、SITL 连接状态维护；
   - 负责把协议细节压缩成 raw result 统一字段。

3. **非策略决策层（not a policy engine）**
   - 不做授权拒绝、不做风险拒绝、不做确认流判定；
   - policy 的 deny/require_confirm/defer 继续留在控制面。

---

## 4. fake 与 future MAVLink adapter 共享的最小 contract

以下 contract 必须保持一致（最小兼容集）：

### 4.1 输入 contract（adapter command 层）

保留以下字段语义：
- `command.command`：adapter 要执行的抽象动作名
- `command.arguments`：动作参数（控制面允许下发的规范参数）
- `command.meta.request_id`：用于 trace / evidence 关联
- `command.meta.action_type` / `skill_group`：用于内部映射和 trace

> 说明：`meta` 可扩展，但不得要求控制面修改已冻结字段名。

### 4.2 输出 contract（raw result 层）

future adapter 至少返回并保持语义一致：
- `accepted`
- `detail`
- `code`
- `message`
- `evidence_ref`
- `execution_trace`
- （建议保留）`adapter`

这可保证 gateway/orchestrator 不改 contract 也能兼容。

---

## 5. 字段边界：哪些属于 adapter command，哪些不应泄漏

## 5.1 应属于 adapter command 层（可见于控制面到执行面的边界）

- 抽象动作信息：`action_type` / `command`
- 抽象参数：`altitude_m`、`target`、`hold_s`、`speed_mps`（示例）
- 上下文字段：`request_id`、`skill_group`、`priority_hint`、`risk_hint`
- 可审计关联：`idempotency_key`（通过 meta 透传）

这些字段是“控制面可解释、与具体飞控协议弱耦合”的内容。

## 5.2 属于 MAVLink/飞控细节（不应泄漏回控制面 contract）

以下内容应留在 adapter 内部（或仅出现在 `execution_trace` 的调试信息中）：
- MAVLink message id、command id、ack 枚举原值
- PX4/ArduPilot mode 编码细节（如 custom mode number）
- 心跳丢包计数、链路重连策略、串口/UDP endpoint 参数
- 飞控特定失败码、低层状态机中间态
- 任务分段/航点内部编译细节

控制面只关心：动作是否被接受、失败类别、可审计证据引用、可读解释。

---

## 6. 第一批最小动作映射子集（建议）

建议第一批仅覆盖：
- `takeoff`
- `goto`
- `hover`
- `land`
- `return_home`

### 为什么先做这 5 个

1. **飞行闭环最小完整性高**：起飞 -> 机动 -> 悬停 -> 返航/降落，覆盖最常见主路径。
2. **接口稳定性验证价值高**：可快速证明 command/result contract 足够承载典型动作。
3. **对 payload/协同依赖低**：不依赖相机云台、投送器、多机协调协议。
4. **SITL 可复现性强**：在仿真中更容易建立可重复 smoke 测试。
5. **失败语义清晰**：超时、拒绝、不可达等错误较易统一成 `exec_*` 族 code。

### 为什么暂不做复杂动作

暂不优先：payload、coordination、多机任务编排，因为它们通常涉及：
- 额外状态同步与时序约束；
- 更复杂的参数模型与安全策略联动；
- 更高的环境依赖（仿真资源、异构设备、队形控制）。

在控制面 contract 未发生变更前，先用 flight_core 最小集证明边界正确，是更稳妥路径。

---

## 7. future MAVLink adapter 返回语义（SITL 阶段建议取值）

以下为与 fake 对齐的最小返回建议：

### 7.1 `accepted: bool`
- `True`：动作在 adapter 内已通过基础执行判定（例如收到可接受 ack 或进入执行态）。
- `False`：动作在执行层失败（超时/执行失败/不可执行）。

### 7.2 `code: str`
建议沿用最小统一族：
- `exec_ok`
- `exec_failed`
- `exec_timeout`
- （可增补）`exec_unavailable`（链路不可用）

SITL 阶段优先保持粗粒度，避免把 MAVLink 专有错误码上抛为控制面 contract。

### 7.3 `message: str`
- 人类可读短句，给日志/CLI 展示用；
- 不作为机器强依赖字段。

### 7.4 `detail: str`
- 与 `code` 对齐的简洁摘要（如 `ok/failed/timeout/unavailable`）。

### 7.5 `evidence_ref: str | None`
SITL 阶段建议使用可定位引用，例如：
- `sitl://session/<session_id>/req/<request_id>`
- `sitl://log/<timestamp>/<request_id>`

要求：可被后续审计/回放组件关联，不要求当前就实现完整存储系统。

### 7.6 `execution_trace: dict | None`
建议保存“必要但去协议化”的执行摘要：
- `mode`: `mavlink_sitl`
- `action`: 抽象动作名
- `latency_ms`
- `attempt`
- `endpoint_tag`（如 `udp_local`）
- `ack_class`（如 `accepted/temporary_reject/timeout` 的归一类）

注意：允许包含调试细节，但控制面不应依赖其中任何飞控特定字段。

---

## 8. 当前阶段明确“不该做”的事

1. 不直接写完整 PX4 深度集成（参数同步、模式全集、全量任务协议）。
2. 不修改控制面 contract（request/result 字段与语义保持 v0.1 基线）。
3. 不在 adapter 层引入策略拒绝（deny 仍归 policy gate）。
4. 不做真实硬件接入（仅面向 SITL/仿真）。
5. 不做复杂任务编排映射（payload / coordination / multi-agent 暂缓）。

---

## 9. 下一步最小实现建议（按顺序）

### A. 先写 `mavlink` adapter stub

**目标**
- 在不接真实 MAVLink 的情况下，完成适配器注册与接口对齐验证。

**建议验证**
- 单测：gateway 可按 `adapter_name="mavlink"` 分发；
- stub 返回字段完整（含 `accepted/code/message/detail/evidence_ref/execution_trace`）。

### B. 再写 command -> mavlink-action mapping skeleton

**目标**
- 为首批 5 个动作建立显式映射表与参数校验骨架；
- 未支持动作返回统一 `exec_failed`/`exec_unavailable`（按约定）。

**建议验证**
- 单测：每个动作可进入对应 mapping 分支；
- 单测：参数缺失/非法时返回一致 code 与 message。

### C. 再做 SITL smoke test

**目标**
- 证明端到端路径在 SITL 下可跑通（控制面 contract 不变）。

**建议验证**
- 最小场景：takeoff -> hover -> land；
- 结果检查：返回 code 语义正确，`evidence_ref` 可关联，`execution_trace` 含关键摘要；
- 回归检查：现有 fake adapter 测试仍通过。

---

## 10. 可考虑的低风险准备项（本次不改代码）

可在下一次小步提交中考虑：

1. **Adapter registry 预留命名**
   - 在文档/注释中约定 `fake`、`mavlink` 两个标准 adapter 名称。

2. **command schema 注释增强**
   - 补充 `command.arguments` 推荐字段词汇表（takeoff/goto/hover/land/rth）。

3. **action_type -> adapter action 映射表占位**
   - 在 gateway 或 adapter 内提供静态映射骨架（不接真实协议）。

4. **result code 约定注释**
   - 明确 `exec_ok / exec_failed / exec_timeout / exec_unavailable` 语义边界。

这些准备项风险低、回滚容易、对 baseline contract 影响最小。

---

## 11. 结论

在 v0.1 基线下，未来接入 MAVLink/SITL adapter 的关键不是扩展控制面 contract，而是：
- 严格守住 policy 与 adapter 的边界；
- 将 MAVLink 细节封装在 adapter 内部；
- 先用首批 flight_core 最小动作子集证明链路可行；
- 用一致 raw result 字段保证可审计与可替换性。

按本文的 A->B->C 顺序推进，可在低风险下完成下一阶段最小落地验证。
