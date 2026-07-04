# Action / Capability Registry v0.1

## 1) 本步目标

新增一个轻量的 Action / Capability Registry v0.1，用于统一描述当前 flight / payload / system / coordination 类 action 的基础元数据，为 policy/profile、fallback taxonomy、adapter mapping 与后续硬件能力清点提供共同参考。

本阶段不修改 protocol contract，不接真实硬件，不接 PX4/SITL，不实现真实动作，不替换 Policy Gate，不替换 adapter dispatch。

---

## 2) 设计判断

当前 action 语义已经分散在多个位置：

- `src/uav_runtime/policy/fallback_actions.py`：lost-link fallback allowlist 与 unsafe payload-like action；
- `src/uav_runtime/adapters/payload_mapping.py`：payload/device skeleton 支持动作；
- `src/uav_runtime/adapters/mavlink_mapping.py`：MAVLink skeleton 支持动作；
- `src/uav_runtime/policy/profile.py`：conservative / standard / aggressive / lost_link profile；
- `src/uav_runtime/policy/gate.py`：link_lost、degraded、unsafe payload 等 policy 裁决。

Registry 要解决的问题：

- 给 action 提供统一元数据入口；
- 降低 fallback taxonomy、payload mapping、mavlink mapping 之间 drift 的风险；
- 为后续硬件清点结果映射到 capability 提供参考；
- 让 unsafe action 可以被显式记录为 `dangerous=True`、`policy_default=deny`、`supported_adapters=[]`，而不是通过缺失映射隐式表达。

Registry 不解决的问题：

- 不做策略裁决替代；
- 不做复杂规则引擎；
- 不做 adapter dispatch；
- 不执行动作；
- 不声明真实硬件已经支持；
- 不改变 `ActionRequest` schema。

---

## 3) 最小字段说明

`ActionCapability` 字段：

| 字段 | 含义 |
| --- | --- |
| `action_type` | canonical action type |
| `domain` | `flight` / `payload` / `system` / `coordination` |
| `skill_group` | 与 runtime/policy 使用的 skill group 对齐 |
| `risk_level` | 静态最小风险提示，不替代 runtime `risk_hint` |
| `supported_adapters` | 当前 skeleton 映射或可占位执行的 adapter |
| `fallback_allowed` | 是否属于 fallback allowlist |
| `allowed_link_states` | 元数据层允许的 link state |
| `requires_confirmation_by_default` | 默认是否建议确认 |
| `dangerous` | 是否为危险/明确不允许动作 |
| `policy_default` | 默认策略倾向，当前仅作元数据 |
| `notes` | 说明与边界 |

---

## 4) 最小 action registry 表

### 4.1 flight/control

| action_type | fallback_allowed | supported_adapters | notes |
| --- | --- | --- | --- |
| `takeoff` | false | `mavlink` | skeleton only，不发送真实 takeoff |
| `goto` | false | `mavlink` | 不是 lost-link fallback |
| `hover` | false | `fake`, `mavlink` | 常规低风险动作 |
| `land` | false | `mavlink` | skeleton only |
| `return_home` | true | `mavlink` | lost-link fallback 元数据允许 |
| `hold_position` | true | `fake` | lost-link fallback 元数据允许 |
| `land_safe` | true | none | policy capability placeholder |
| `reduce_speed` | true | none | policy capability placeholder |
| `maintain_heading` | true | none | policy capability placeholder |

### 4.2 payload/device

| action_type | fallback_allowed | supported_adapters | notes |
| --- | --- | --- | --- |
| `camera_capture` | true | `payload` | 可用于低风险态势记录 |
| `gimbal_set_angle` | false | `payload` | 非 lost-link fallback |
| `speaker_play_message` | false | `payload` | degraded 可 require_confirm，lost 默认 deny |
| `light_set_state` | true | `payload` | 低风险设备动作 |
| `sensor_read` | true | `payload` | system/health 类能力，通过 payload skeleton 暂接 |
| `health_query` | true | `payload` | system/health 类能力，通过 payload skeleton 暂接 |

### 4.3 system

| action_type | fallback_allowed | supported_adapters | notes |
| --- | --- | --- | --- |
| `report_status` | true | none | policy capability placeholder |
| `health_query` | true | `payload` | 见 payload/device 表 |
| `sensor_read` | true | `payload` | 见 payload/device 表 |

### 4.4 unsafe / explicitly denied

| action_type | dangerous | fallback_allowed | supported_adapters | policy_default |
| --- | --- | --- | --- | --- |
| `payload_release` | true | false | none | deny |
| `drop` | true | false | none | deny |
| `deploy` | true | false | none | deny |
| `strike` | true | false | none | deny |
| `attack` | true | false | none | deny |

Unsafe action 可以进入 registry，但必须保持：

- `dangerous=True`；
- `fallback_allowed=False`；
- `supported_adapters=[]`；
- `policy_default=deny`；
- 不进入 `payload_mapping` 或 `mavlink_mapping` supported actions。

---

## 5) 与 policy/profile/fallback/adapter 的关系

当前选择风险更低的方案：**只新增 registry 与一致性测试，不强制改 Policy Gate 使用 registry**。

关系如下：

- Policy Gate 继续使用当前 profile/fallback 规则进行裁决；
- fallback taxonomy 继续作为 Policy Gate 的直接输入；
- registry 作为元数据参考与一致性测试来源；
- payload/mavlink mapping 暂不重构，只通过测试保证支持动作存在于 registry；
- 后续硬件清点结果可以映射到 registry 的 `supported_adapters` / capability metadata，但不反向修改 protocol contract。

---

## 6) 一致性测试

`tests/unit/test_action_registry.py` 覆盖：

- fallback allowlist 中的动作必须存在于 registry；
- payload mapping 支持动作必须存在于 registry；
- MAVLink mapping 支持动作必须存在于 registry；
- unsafe action 必须 `dangerous=True`、`fallback_allowed=False`、`supported_adapters=[]`、`policy_default=deny`；
- unsafe action 不得进入 payload/mavlink supported mapping；
- lost-link fallback 动作必须 `fallback_allowed=True`、包含 `lost` link state、风险不超过阈值。

---

## 7) 非目标

当前明确不做：

- 不接真实 PX4；
- 不接真实 payload；
- 不实现真实动作；
- 不做复杂规则引擎；
- 不替换 Policy Gate；
- 不替换 adapter dispatch；
- 不改 protocol contract；
- 不改 adapter/backend contract；
- 不做 GUI；
- 不新增危险能力。

---

## 8) Capability manifest visibility

本阶段在 CLI 中提供只读 manifest 输出能力：

```bash
python -m uav_runtime.console.cli list-capabilities --pretty
```

可选过滤参数：

| 参数 | 用途 |
| --- | --- |
| `--domain flight` / `payload` / `system` / `coordination` | 只展示指定 domain 的 action |
| `--adapter mavlink` / `payload` / `fake` | 只展示当前 metadata 中由指定 adapter 支持的 action |
| `--fallback-only` | 只展示 `fallback_allowed=true` 的 action |
| `--include-dangerous` | 显式包含 dangerous action；默认隐藏 dangerous action |

Manifest 每条 action 输出字段与 `ActionCapability` 对齐：

- `action_type`
- `domain`
- `skill_group`
- `risk_level`
- `supported_adapters`
- `fallback_allowed`
- `allowed_link_states`
- `requires_confirmation_by_default`
- `dangerous`
- `policy_default`
- `notes`

该输出只用于能力可见性、硬件清点和后续 adapter 对齐，不执行 action，不连接真实硬件，不改变 Policy Gate 主逻辑，也不改变 protocol contract。

### 8.1 硬件清点用途

- `supported_adapters=["mavlink"]` 的动作，对应飞控 / PX4 / ArduPilot 路线能力清点；
- `supported_adapters=["payload"]` 的动作，对应相机、云台、喊话器、灯光、传感器等非破坏性设备清点；
- `fallback_allowed=true` 的动作需要重点确认真实平台是否支持并能在失联/退化状态下安全执行；
- `dangerous=true` 的动作当前只作为禁止项记录，不作为采购、开发或演示目标；
- adapter 过滤只能说明当前 skeleton metadata 中存在映射，不代表真实硬件已接入。
