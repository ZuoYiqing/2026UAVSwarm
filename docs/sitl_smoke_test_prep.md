# PX4 SITL Smoke Test Preparation（设计说明）

> 状态：Design-Only（本轮不写真实 PX4/MAVLink 集成代码）
>
> 日期：2026-04-16
>
> 约束：保持 protocol/policy contract 冻结，不引入 GUI/ROS2/多机复杂编排。

---

## 1) 为什么现在可以进入 SITL smoke test 准备阶段

当前已经具备进入 SITL smoke test 准备的必要前提：

1. **控制面 contract 已冻结且有测试保障**
   - policy/protocol 语义边界明确，避免 smoke test 期间反复改上层 contract。

2. **执行面有双路径基线**
   - `fake` adapter：稳定回归基线；
   - `mavlink` adapter：stub + mapping skeleton，已具备最小 contract 兼容输出。

3. **adapter selection 已最小落地**
   - 默认 fake；
   - 可显式选择 mavlink；
   - orchestrator 只消费 adapter_name，gateway 只做注册+分发。

结论：体系结构已足够支持“先做 smoke test 准备，再逐步连接真实 backend”。

---

## 2) 当前各组件所处位置

### fake adapter
- 角色：主回归执行后端。
- 当前价值：用于验证控制面 contract 与运行时主链路稳定性。

### mavlink adapter stub + mapping skeleton
- 角色：未来 SITL 后端的占位入口。
- 当前价值：
  - 提供 command->future-action 结构；
  - 维持 raw result 字段稳定；
  - 允许“有 backend / 无 backend”语义分流设计。

### adapter selection
- 角色：部署/运行时 wiring 选择点。
- 当前价值：使 smoke test 可以在不改 policy/protocol 的前提下，定向走 `mavlink` 路径。

---

## 3) SITL smoke test 的目标与非目标

## 3.1 目标（第一轮）

1. 证明控制面 contract 不变时，可走通 `orchestrator -> gateway -> mavlink adapter` 路径。
2. 证明 `mavlink` 路径可区分：
   - backend 未配置/不可用；
   - backend 已启用（即使仍为最小占位）。
3. 保持 action_result / audit / replay 结构一致，不因 backend 模式改变而破坏上层消费。

## 3.2 非目标（第一轮）

1. 不追求真实飞控动作完整正确性（那是后续 integration 阶段目标）。
2. 不做复杂任务编排、payload、多机协同。
3. 不做性能压测、鲁棒性压测、链路容灾验证。

---

## 4) 第一轮 smoke test 最小动作子集

仅考虑：
- `takeoff`
- `goto`
- `hover`
- `land`
- `return_home`

### 4.1 建议第一轮优先顺序
1. `takeoff`
2. `hover`
3. `land`
4. `goto`
5. `return_home`（可先 placeholder）

理由：
- 先验证最短闭环（起飞-悬停-降落）；
- 再扩展到位移与返航语义；
- 在 backend 仍占位时，`return_home` 可先保持 placeholder，避免过早引入任务状态机复杂度。

### 4.2 参数最小化建议
- takeoff: `altitude_m`（可选默认值）
- goto: `x/y/z` 或 `lat/lon/alt_m` 二选一最小集合
- hover: `duration_s`
- land: 无必填参数
- return_home: 无必填参数（placeholder）

### 4.3 明确延后项
- payload 控制、相机/云台动作
- 多机协同/编队
- 复杂航线批量下发
- 任务级容错与恢复策略

---

## 5) 未来 backend config（仅设计，不改代码）

为进入 SITL smoke test，未来建议引入最小配置位（占位）：

1. `adapter_name`（如 `fake` / `mavlink`）
2. `backend_mode`（如 `stub` / `sitl`）
3. `backend_enabled`（bool）
4. `transport_endpoint`（连接串占位，如 udp endpoint）
5. `timeout_ms`（调用超时占位）
6. `retry_count`（重试次数占位）

### 5.1 归属边界

**deployment/config 层：**
- adapter_name
- backend_mode
- backend_enabled
- transport_endpoint
- timeout/retry 默认值

**adapter internals：**
- endpoint 解析与连接状态
- timeout/retry 具体执行机制
- backend 异常映射到统一 result code

**不属于 protocol contract：**
- 以上所有 backend 细节均不应上升到控制面消息字段。

---

## 6) 第一轮 smoke test 成功标准

## 6.1 可接受成功标准

1. 控制面 contract 不变。
2. 通过 `mavlink` 路径能明确区分“backend 已配置/未配置”语义（即使先用占位模式）。
3. 至少一个动作（建议 `takeoff` 或 `hover`）可完成最小端到端通路。
4. action_result / audit / replay 结构保持一致，既有消费者无需协议改动。

## 6.2 可接受失败（当前阶段）

- SITL backend 未配置导致 `unavailable/not_configured` 类失败；
- placeholder 动作返回 `unsupported`；
- 单动作执行失败但返回结构完整且可审计。

## 6.3 不可接受失败（说明架构问题）

- 需要改 protocol/policy contract 才能接 smoke test；
- adapter 选择逻辑侵入 policy gate；
- action_result/audit 结构被 backend 细节破坏；
- gateway 承担复杂策略选择导致边界混乱。

---

## 7) 下一步最小代码准备项（建议，不在本轮实现）

1. 在 `mavlink` adapter 增加 `backend_mode` 占位（默认 `stub`）。
2. 增加轻量 backend config dataclass（只含 mode/enabled/endpoint/timeout/retry）。
3. 增加一个稳定响应语义：`sitl_not_configured`（或 `exec_unavailable` 子类消息）。
4. 增加 smoke test 命令样例（文档/脚本级，不接真实 MAVLink 库）。
5. 增加 1~2 条最小测试：
   - `backend_mode=stub` 时稳定返回；
   - `backend_mode=sitl + backend_enabled=false` 时稳定 not-configured 语义。

---

## 8) 当前不该做的事

1. 不直接写完整 PX4 集成。
2. 不修改 protocol/policy contract。
3. 不提前接 ROS2。
4. 不扩展 GUI。
5. 不做复杂多机 smoke test。
6. 不把 SITL 配置细节上升到控制面消息。

---

## 9) 建议推进顺序

1. 先完成 backend config 占位 + 语义分流（stub/sitl-not-configured）。
2. 再补最小 smoke test 命令和测试样例。
3. 最后再评估真实 SITL 连接接入（单动作、可回滚、小步）。

该顺序可最大化复用当前冻结 contract，且将“架构风险”与“协议接入风险”解耦。
