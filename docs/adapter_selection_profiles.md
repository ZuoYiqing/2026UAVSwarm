# Adapter Selection + Profile-Aware Wiring（设计说明）

> 状态：Design-Only（本阶段先设计，不做大规模实现）
>
> 日期：2026-04-10
>
> 约束：不修改已冻结 protocol/policy contract；不接真实 PX4/SITL/MAVLink。

---

## 1) 为什么当前需要 adapter selection

在 v0.1 baseline 下，控制面与执行面已经解耦：
- policy/orchestrator 负责“是否执行”；
- adapter/gateway 负责“如何执行”。

随着 `fake` 与 `mavlink`（stub）并存，系统需要一个清晰、可测试、可配置的“执行面 adapter 选择点”，用于：
1. 在同一控制面 contract 下切换不同执行后端；
2. 支持不同部署形态（Ground / Edge）的默认行为；
3. 为后续 SITL smoke test 提供稳定入口（无需先改 policy/protocol）。

---

## 2) fake / mavlink 两类 adapter 定位

### fake adapter（当前主执行路径）
- 定位：基线验证与回归测试主路径。
- 价值：具备 success/fail/timeout/delay/evidence/trace 语义，稳定、快速、无外部依赖。
- 当前适用：默认开发、CI、回归与合同形状验证。

### mavlink adapter（当前为 stub + mapping skeleton）
- 定位：未来 SITL/MAVLink 执行面的占位接口。
- 价值：固定 command->future-action mapping skeleton，验证 adapter contract 可扩展性。
- 当前限制：不连真实 PX4/SITL，不承诺真实执行成功。

---

## 3) Ground / Edge Profile 的默认选择建议

## 3.1 Ground Profile（当前阶段）
- 默认：`fake`
- 可选：`mavlink`（仅用于 stub/mapping 验证）

原因：
- Ground 环境开发和演示优先稳定可复现；
- 当前 `mavlink` 仍是占位，不应作为默认执行面；
- 默认 fake 可保持现有 pytest 与 demo 行为一致。

## 3.2 Ground Profile（未来接 SITL 时）
- 切换策略：通过部署配置（env/cli/config）将默认 adapter 从 `fake` 切到 `mavlink`；
- 控制面 contract 不变，仅 wiring/config 改变。

## 3.3 Edge Profile（未来）
- 原则：不直接复用 Ground 的全部依赖（尤其是本地调试、仿真依赖链）。
- 共享核心：protocol/policy/runtime/gateway contract。
- 差异主要在 wiring/config：
  - 可用 adapter 集合
  - 默认 adapter
  - 部署参数来源（本地文件/环境变量/设备固化配置）

---

## 4) 各层职责边界：谁负责 adapter 选择

### deployment/config 层（负责“选哪个”）
负责确定“已选定 adapter_name”，来源可以是：
- 默认配置（例如 ground 默认 fake）；
- CLI 参数覆盖（例如 `--adapter mavlink`）；
- 环境变量或配置文件。

### runtime/orchestrator 层（消费已选结果）
- 只消费“已选定 adapter_name”；
- 不引入复杂多因子策略评分；
- 保持 policy decision -> adapter execute 主链路语义不变。

### gateway 层（注册与分发）
- 负责 adapter 注册表与按名字分发执行；
- 不承担 profile 推断、策略决策或部署选择逻辑。

### policy 层（不负责 adapter 选择）
- 继续只做 allow/deny/require_confirm 等裁决；
- 不引入 adapter 选择逻辑，避免边界混乱。

---

## 5) 最小选择机制（克制方案）

建议采用三步最小机制：

1. **默认 adapter 名称配置**
   - 设定系统默认 `default_adapter_name="fake"`。

2. **可选覆盖入口**
   - CLI 或配置文件允许传入 adapter 名称（如 `--adapter mavlink`）。

3. **orchestrator 消费最终 adapter_name**
   - orchestrator 执行时仅使用已解析的 adapter_name 调 gateway；
   - 若 adapter 未注册，沿用现有 `adapter_not_found` 语义。

该机制不新增策略层，不改变 protocol/policy contract。

---

## 6) 哪些逻辑属于 config，哪些不该进入控制面 contract

### 属于 deployment/config 的
- 默认 adapter 名称；
- profile 到 adapter 的默认映射（Ground=Fake, Edge=TBD）；
- CLI/env/config 的覆盖优先级。

### 不该进入控制面 contract 的
- adapter 的选择评分规则；
- profile 细节和部署拓扑；
- MAVLink/PX4/SITL 连接参数（这些属于 adapter 内部配置）。

控制面 contract 继续保持“动作语义 + policy 决策 + 结果归一化”，不掺杂部署选择细节。

---

## 7) 低风险最小准备项（建议，不在本步大量实现）

可在下一步小步提交落地：

1. `adapter` 名称常量/默认配置占位（例如 `DEFAULT_ADAPTER_NAME = "fake"`）。
2. `RuntimeOrchestrator` 支持构造参数 `adapter_name`（默认 fake）。
3. CLI 增加可选 `--adapter` 参数并透传到 orchestrator。
4. 补一条 adapter selection 测试路径：
   - 传 `mavlink` 时走 mavlink stub；
   - 不传时保持 fake 默认路径。

注意：以上均为 wiring/config 改动，不触碰 policy/protocol contract。

---

## 8) 为什么下一步应先落地 selection，再做 SITL smoke test

原因：
1. **先稳定入口**：没有可控 adapter 选择机制，后续 SITL smoke test 无法可重复切换执行面。
2. **降低风险**：先改 wiring，再接外部依赖，便于把“框架问题”和“协议问题”分离定位。
3. **保持 contract 稳定**：先验证同一控制面 contract 下 fake/mavlink 可切换，再推进真实协议接入。
4. **可回滚性好**：selection 落地失败可快速回退，不影响底层协议集成计划。

因此推荐顺序：
- 第一步：adapter selection 最小代码落地（配置 + 透传 + 测试）；
- 第二步：SITL smoke test 准备（仍可先 stub 驱动）；
- 第三步：再考虑真实 MAVLink/PX4 集成。

---

## 9) 结论

当前最优策略是“先把 adapter selection 与 profile-aware wiring 设计清楚、接口最小落地，再推进 SITL”。

这样可以在不破坏已冻结 contract 的前提下，稳定演进执行面能力，并为 Ground/Edge 后续分化保留清晰边界。
