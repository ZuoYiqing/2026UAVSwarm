# Skill Group Taxonomy and Runtime Semantics

## 1) 为什么要修正 skill_group 的含义

`skill_group` 之前容易被误解为“另一个 action 字段”或“Anthropic/Agent 那种可执行 skill”。当前修正后的定义是：

> `skill_group` 是 runtime / policy 使用的 **operational capability lane（运行时能力通道）**，不是具体动作，也不是可执行 skill 实现。

它必须比 `domain` 更贴近运行时控制，比 `action_type` 更粗粒度：

- `action_type`：具体要做什么，例如 `hover`、`health_query`、`camera_capture`；
- `domain`：高层领域，例如 `flight`、`payload`、`system`、`coordination`；
- `skill_group`：运行时/策略分组，例如 `flight_core`、`payload`、`coordination`、`generic`，用于 profile 级 allow/deny、审计和后续调度分流；
- `Skill` / `SkillExecutor`：另一个预留的可执行 skill abstraction，目前不是主 runtime 执行链路。

因此，`skill_group` 不是重复 `action_type`，也不只是粗略领域名；它是 policy/profile 能批量控制一类能力的最小运行时标签。

---

## 2) 当前最小 skill_group 集合

| skill_group | 当前含义 | 典型 action_type | 主要 domain | 运行时/策略意义 |
| --- | --- | --- | --- | --- |
| `flight_core` | 飞控核心能力通道 | `hover`, `takeoff`, `land`, `return_home`, `hold_position` | `flight` | 可由 profile 单独允许/拒绝，后续可绑定飞控 adapter/backend 路径 |
| `payload` | 非破坏性载荷/设备能力通道 | `camera_capture`, `light_set_state`, `sensor_read`, `health_query` | `payload` / `system` | 可由 profile 单独允许/拒绝，后续可绑定 payload adapter 和硬件清点 |
| `coordination` | 任务/协同控制通道 | `submit_mission` | `coordination` | 用于 mission orchestration，不等同于飞控或载荷动作 |
| `generic` | 通用/未细分能力通道 | `report_status` | `system` | 用于低风险通用状态类动作，避免误归入 flight/payload |

---

## 3) 当前已经落地的功能扩充

本轮开始，`skill_group` 不再只是 registry/CLI metadata。Policy Gate 会读取 `RuntimeActionContext.skill_group`，并结合 `PolicyProfile.allowed_skill_groups` / `denied_skill_groups` 做 profile 级裁决：

- 如果 `skill_group` 在 `denied_skill_groups` 中：`DENY`；
- 如果 `allowed_skill_groups` 非空且不包含该 `skill_group`：`DENY`；
- 拒绝 reason 使用 `REASON_CODE_SKILL_GROUP_DENIED`；
- `ALLOW`、link-state、preemption、risk 等后续规则仍按原有逻辑继续执行。

这让 `skill_group` 具备独立价值：它可以关闭一整类 capability lane，而不是重复每一个 `action_type` 规则。

---

## 4) 与 SkillExecutor 的关系

仓库里存在 `src/uav_runtime/skills/*` skeleton，但当前主链路仍是：

```text
ActionRequest
-> RuntimeOrchestrator
-> Policy Gate
-> AdapterGateway
-> Adapter
```

不是：

```text
ActionRequest
-> SkillExecutor
-> Skill.execute
```

因此当前命名虽然保留 `skill_group`，但团队内部应统一理解为：

> `skill_group` = 能力通道 / 策略分组；
> `Skill` = 预留的可执行技能抽象；
> 二者不是同一个概念。

---

## 5) 后续扩展原则

1. 不要把 `skill_group` 当作具体动作名；具体动作仍用 `action_type`。
2. 不要把 `skill_group` 当作硬件 adapter；执行路径仍由 adapter/backend seam 负责。
3. 新增 action 时必须在 Action / Capability Registry 中填写 `skill_group`。
4. 新增 profile 时必须明确是否允许该 `skill_group`。
5. 如果未来启用 `SkillExecutor`，应新增 `skill_name` 或类似字段，不要把 `skill_group` 复用成可执行 skill 名。
6. 如果某个 group 只是 domain 的重复，应重新审视是否需要拆分为更有策略意义的 capability lane。
