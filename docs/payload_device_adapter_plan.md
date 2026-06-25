# Payload / Device Adapter Skeleton Plan

## 1) 本步目标

在不修改 protocol / policy contract 的前提下，新增 Payload / Device Adapter skeleton，给后续接入非破坏性载荷与设备接口预留统一执行面入口。

本阶段只做 skeleton / stub，不接真实硬件，不接 PX4/SITL，不实现危险载荷控制。

---

## 2) 设计判断

### 为什么现在需要 payload/device adapter

当前系统已有 flight/mavlink 方向的执行面起点，但无人机/无人车平台还会包含相机、云台、喊话器、照明、传感器与设备健康监控等非飞控设备。将这些能力放入独立 payload/device adapter，有助于：

- 避免把设备控制逻辑塞入 flight/mavlink adapter；
- 让飞控动作与载荷/设备动作在执行面职责上解耦；
- 为后续真实硬件接入保留统一 raw result contract；
- 让 policy gate 继续作为动作授权入口，而不是让 adapter 内部承担策略裁决。

### payload/device adapter 与 flight/mavlink adapter 的区别

| 维度 | flight/mavlink adapter | payload/device adapter |
| --- | --- | --- |
| 主要对象 | 飞控 / PX4 / SITL / MAVLink 飞行动作 | 非破坏性载荷与设备 |
| 典型动作 | takeoff / goto / hover / land / return_home | camera_capture / gimbal_set_angle / sensor_read |
| 接入重点 | 飞行控制链路与 backend readiness | 设备命令映射、占位校验、设备状态结果 |
| 当前阶段 | readiness / stub | skeleton / placeholder |

### 属于 payload/device adapter 的能力

- 非破坏性设备动作映射；
- 参数占位校验；
- 设备类型与 placeholder action 元数据；
- 与 fake/mavlink adapter 一致的 raw result contract；
- 后续真实设备接入 seam。

### 不应进入 payload/device adapter 的能力

- policy gate 的授权、风险、确认和拒绝逻辑；
- protocol / policy contract 修改；
- 飞控控制动作；
- PX4/SITL 连接逻辑；
- 危险载荷、投放、打击、武器化或攻击性动作。

### 为什么本阶段不修改 protocol/policy contract

当前 `ActionRequest` 已能通过 `action_type`、`skill_group`、`params` 与 adapter gateway 传递 payload/device 动作。Payload adapter 只消费 gateway 构造后的 command 对象，并返回既有 raw result 字段，因此无需改动 protocol/policy contract。

### 为什么危险载荷/投放/打击类动作不在范围内

本阶段目标是接口预留与非破坏性设备闭环，不是危险能力建设。投放、释放、打击、武器化、攻击性载荷等动作不进入 mapping，也不返回 supported placeholder，避免把危险能力固化进执行面 skeleton。

---

## 3) 最小 action / device 表

| device category | action_type | 当前行为 | 参数占位 |
| --- | --- | --- | --- |
| camera | `camera_capture` | placeholder result | optional: `camera_id`, `mode`, `resolution` |
| gimbal | `gimbal_set_angle` | placeholder result | required: `pitch_deg`, `yaw_deg`; optional: `roll_deg`, `gimbal_id` |
| speaker | `speaker_play_message` | placeholder result | required: `message`; optional: `speaker_id`, `volume` |
| light | `light_set_state` | placeholder result | required: `state`; optional: `light_id`, `intensity` |
| sensor | `sensor_read` | placeholder result | optional: `sensor_id`, `sensor_type` |
| health_monitor | `health_query` | placeholder result | optional: `device_id`, `include_metrics` |

---

## 4) 最小代码结构

- `src/uav_runtime/adapters/payload_mapping.py`
  - 定义非破坏性设备 action metadata；
  - 不导入真实硬件 SDK。
- `src/uav_runtime/adapters/payload_adapter.py`
  - 消费 gateway command；
  - 返回 contract-compatible raw result；
  - unsupported action 返回 `exec_unsupported`。
- `tests/unit/test_payload_adapter.py`
  - 覆盖实例化、支持动作、unsupported、参数占位校验、gateway dispatch、mapping 范围。

---

## 5) raw result contract

Payload adapter 与 fake/mavlink adapter 共享最小 raw result contract：

- `accepted`
- `code`
- `message`
- `detail`
- `adapter`
- `evidence_ref`
- `execution_trace`

---

## 6) 与 Policy Gate 的关系

- payload/device 动作仍必须经过 policy gate；
- 高风险 payload action 后续可通过 risk/confirm rule 触发 `require_confirm` 或 `deny`；
- 本轮只做低风险、非破坏性动作 skeleton；
- adapter 内不做策略拒绝，只做 action mapping 与参数占位校验。

---

## 7) 当前非目标

- 不接真实相机；
- 不接真实云台；
- 不接真实喊话器；
- 不接真实照明/传感器/载荷硬件；
- 不实现投放、释放、打击、武器化或攻击性动作；
- 不做 GUI；
- 不修改 protocol/policy contract；
- 不接 PX4/SITL。

---

## 8) 预期验证方式

```bash
python -m pytest tests/unit/test_payload_adapter.py -q
python -m pytest -q
```

---

## 9) Runtime wiring 与 audit/replay 集成

Payload adapter 进入 runtime wiring 后，仍保持默认执行路径不变：未显式选择 adapter 时继续使用 `fake`，只有显式选择 `payload` 时才进入 payload/device stub。

### 选择方式

- Runtime：`RuntimeOrchestrator(adapter_name="payload")`
- CLI：`submit-action health_query --adapter payload`

### 当前最小 CLI 动作

为避免引入复杂参数系统，当前 CLI 优先使用无必填参数动作：

- `health_query`
- `sensor_read`
- `camera_capture`

需要参数的动作（例如 `gimbal_set_angle`、`speaker_play_message`、`light_set_state`）暂时仍由 runtime/API 层传入 params，后续如确有需要再设计极简 `--params-json`。

### audit/replay 期望

payload 路径与 fake/mavlink 路径保持一致，成功或 unsupported 都应产生：

- `policy_decision_event`
- `action_result`
- 可由 `replay-last` / replay 工具读取的 audit record

其中 `action_result.adapter == "payload"`，支持动作返回 `payload_placeholder_ok`，unsupported 动作返回 `exec_unsupported`。
