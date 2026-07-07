# Hardware Capability Mapping Template

## 1) 本步目标

建立“硬件资源 -> Action / Capability Registry action”的最小映射模板，用于把公司现有平台、拟采购平台、飞控、伴随计算板、通信链路和非破坏性载荷接口映射到当前 capability registry。

本模板只用于硬件清点、采购判断、接口缺口分析和后续 adapter 接入规划；不接真实硬件，不实现真实控制，不修改 protocol / policy contract，不新增危险能力。

---

## 2) 设计判断

### 2.1 为什么现在需要硬件能力映射

当前系统已经具备：

- Action / Capability Registry v0.1：统一记录 flight / payload / system / unsafe action 元数据；
- Capability Manifest / `list-capabilities` CLI：可导出当前 action 能力边界；
- payload / mavlink / px4_sitl skeleton：提供后续 adapter/backend seam；
- Policy Gate / Profile / Runtime v0.2：提供控制面裁决、fallback、audit/replay 语义。

硬件线正在清点无人机平台、飞控、伴随计算板、通信链路和载荷接口。如果没有统一映射模板，硬件清点结果容易直接进入临时代码、口头结论或分散表格，导致 capability registry、adapter mapping、采购需求和 policy 边界发生 drift。

### 2.2 capability registry 与硬件清点的关系

Capability registry 描述“系统知道哪些 action、这些 action 属于哪个 domain、当前 skeleton 支持哪些 adapter、是否 fallback、是否 dangerous”。硬件清点描述“公司现有或拟采购硬件是否具备实现这些 action 的物理接口、SDK、驱动、供电、重量和文档条件”。

二者关系是：

```text
hardware inventory
-> capability mapping template
-> candidate adapter/backend route
-> later implementation plan
-> tests / audit / readiness validation
```

硬件清点不直接改变 protocol schema，不直接扩大 Policy Gate 权限，也不直接把 unsupported action 写进 adapter。它先通过本文档映射到 registry action，再形成后续最小接入任务。

### 2.3 为什么硬件清点不应直接修改 policy/adapter

- Policy Gate 负责控制面裁决，不应混入某个硬件厂商的接口细节；
- adapter/backend 负责执行面接入，不应因为硬件清点结果而绕过 policy/profile；
- protocol contract 已冻结，硬件差异应在 adapter/backend seam 或 capability mapping 中消化；
- 未完成 bench test / SITL / readiness 的硬件不应直接标记为生产可用。

### 2.4 dangerous action 处理原则

`payload_release` / `drop` / `deploy` / `strike` / `attack` 等 dangerous action 只能作为禁止项记录，用于审计、边界说明和防止误采购；不得作为采购目标、开发目标、演示目标或 adapter supported mapping。

### 2.5 为什么本步不依赖 PX4/SITL 或真实设备

本步只建立文档模板与填写规范，不执行飞控动作，不连接 PX4 SITL，不连接真实 payload，不需要真实 MAVLink endpoint，也不需要设备 SDK。真实接入必须在后续按 capability mapping 结果单独拆分 readiness / bench test / smoke test。

---

## 3) 使用方式

1. 导出当前 capability manifest：

   ```bash
   python -m uav_runtime.console.cli list-capabilities --pretty
   ```

2. 如需审计禁止项，显式包含 dangerous action：

   ```bash
   python -m uav_runtime.console.cli list-capabilities --include-dangerous --pretty
   ```

3. 按平台填写“平台基础信息表”。
4. 按硬件模块填写“硬件模块清点表”。
5. 逐项把 manifest 中的 action 填入“Capability 映射表”。
6. 将 dangerous action 填入“禁止/高风险能力表”，并保持 `forbidden` / `not procurement target`。
7. 对 `supported_adapters=["mavlink"]` 的 action，优先对齐飞控 / PX4 / ArduPilot 路线。
8. 对 `supported_adapters=["payload"]` 的 action，优先对齐相机、云台、喊话器、灯光、传感器等非破坏性设备。
9. 对 `fallback_allowed=true` 的 action，重点确认真实平台是否支持失联/退化状态下安全执行。
10. 对 `dangerous=true` 的 action，只做禁止项审计，不作为开发或采购目标。

---

## 4) 平台基础信息表

| platform_id | platform_type | flight_controller | autopilot_stack | companion_computer | communication_link | payload_ports | power_budget | weight_margin | interface_docs_available | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `platform-001` | `uav` / `ugv` / `usv` / `fixed_node` | TBD | `PX4` / `ArduPilot` / `vendor` / `unknown` | TBD | TBD | TBD | TBD | TBD | `yes` / `no` / `partial` | 填写平台来源、现状、限制 |

字段说明：

- `platform_id`：内部平台编号；
- `platform_type`：平台类型，仅使用 `uav` / `ugv` / `usv` / `fixed_node`；
- `flight_controller`：飞控型号或供应商；
- `autopilot_stack`：PX4 / ArduPilot / vendor / unknown；
- `companion_computer`：伴随计算板型号，如 Jetson、Raspberry Pi、工控机等；
- `communication_link`：遥测、数传、4G/5G、Wi-Fi、专网等；
- `payload_ports`：USB、UART、CAN、Ethernet、GPIO、SDK 等；
- `power_budget`：可供载荷/伴随计算使用的电源预算；
- `weight_margin`：剩余载重余量；
- `interface_docs_available`：接口文档是否可用；
- `notes`：限制、风险、依赖供应商事项。

---

## 5) 硬件模块清点表

| module_id | module_type | vendor_model | interface_type | driver_or_sdk_available | test_status | blocking_issue | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `module-001` | `flight_controller` / `companion_computer` / `camera` / `gimbal` / `speaker` / `light` / `sensor` / `telemetry` / `power` | TBD | `MAVLink` / `UART` / `CAN` / `USB` / `Ethernet` / `GPIO` / `SDK` / `unknown` | `yes` / `no` / `partial` | `unknown` / `available` / `bench_tested` / `blocked` | TBD | 填写驱动、供电、线缆、协议风险 |

字段说明：

- `module_id`：硬件模块编号；
- `module_type`：模块类型；
- `vendor_model`：厂商和型号；
- `interface_type`：主要控制/数据接口；
- `driver_or_sdk_available`：驱动、SDK、协议说明是否可用；
- `test_status`：当前验证状态；
- `blocking_issue`：阻塞项，如无线缆、协议闭源、供电不足、重量超限；
- `notes`：附加说明。

---

## 6) Capability 映射表

| action_type | domain | required_hardware | required_interface | candidate_adapter | current_status | fallback_allowed | dangerous | verification_method | missing_items | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `takeoff` | `flight` | flight controller + airframe | MAVLink / autopilot API | `mavlink` / `px4_sitl` | `supported_stub` / `needs_hardware` / `needs_driver` / `blocked` / `forbidden` | false | false | SITL readiness -> backend_connected -> takeoff smoke | PX4 SITL / endpoint / safety checklist | 当前不实现真实 takeoff |
| `return_home` | `flight` | flight controller + configured home | MAVLink / autopilot API | `mavlink` | `needs_hardware` | true | false | bench/SITL fallback validation | autopilot mode support evidence | fallback 需重点确认 |
| `camera_capture` | `payload` | camera | USB / Ethernet / SDK | `payload` | `supported_stub` / `needs_driver` | true | false | bench test with sample image artifact | camera SDK / mount / power | 非破坏性载荷 |
| `gimbal_set_angle` | `payload` | gimbal | UART / CAN / SDK | `payload` | `needs_driver` | false | false | bench test angle command with no flight | gimbal protocol docs | 不在 lost-link fallback 默认白名单 |
| `speaker_play_message` | `payload` | speaker | UART / USB / GPIO / SDK | `payload` | `needs_hardware` | false | false | bench test with preset message only | speaker SDK / audio file format | degraded 可 require_confirm |
| `light_set_state` | `payload` | light | GPIO / CAN / SDK | `payload` | `needs_driver` | true | false | bench test on/off with current limit | relay/driver docs | fallback 可考虑 |
| `sensor_read` | `system` | sensor | UART / CAN / USB / Ethernet / SDK | `payload` | `supported_stub` / `needs_driver` | true | false | bench read sample telemetry | sensor protocol docs | health/status 类 |
| `health_query` | `system` | companion + module health APIs | local API / SDK | `payload` | `supported_stub` | true | false | runtime payload path + bench health read | hardware health source | 当前 skeleton 可见 |

状态枚举：

- `supported_stub`：当前 adapter skeleton 已有占位结果，但不代表真实硬件可用；
- `needs_hardware`：缺少硬件或平台；
- `needs_driver`：有硬件但缺驱动、SDK、协议实现或线缆；
- `blocked`：接口闭源、供电/重量/通信不满足或供应商资料不足；
- `forbidden`：禁止项，不进入采购或开发目标。

---

## 7) 禁止/高风险能力表

| action_type | reason | dangerous | policy_default | procurement_allowed | notes |
| --- | --- | --- | --- | --- | --- |
| `payload_release` | dangerous payload/release-like action is outside project scope | true | deny | no | forbidden / not procurement target |
| `drop` | drop/release-like action is outside project scope | true | deny | no | forbidden / not procurement target |
| `deploy` | deployment/release-like action is outside project scope | true | deny | no | forbidden / not procurement target |
| `strike` | strike/attack-like action is outside project scope | true | deny | no | forbidden / not procurement target |
| `attack` | attack-like action is outside project scope | true | deny | no | forbidden / not procurement target |

要求：

- 上述 action 必须保持 `current_status=forbidden`；
- `procurement_allowed` 必须为 `no`；
- 不允许把危险动作变成开发目标；
- 不允许进入 payload/mavlink supported mapping；
- 如硬件供应商宣传相关能力，也只记录为排除项和风险项。

---

## 8) 后续采购建议规则

最小采购/接入优先级规则：

1. 优先采购开放接口设备；
2. 优先 MAVLink / PX4 / ArduPilot 可接入平台；
3. 优先可接伴随计算板的平台；
4. 优先具备 SDK、串口、网口、CAN 或明确协议文档的载荷；
5. 优先可进行 bench test 且不依赖封闭 App 的设备；
6. 不优先采购封闭整机作为第一批验证对象；
7. 不采购无法提供接口资料的载荷作为第一批验证对象；
8. 不采购 dangerous action 相关设备作为项目目标；
9. 对 fallback action 相关硬件，优先要求供应商提供失联/退化状态安全行为说明；
10. 所有采购前先填写 Capability 映射表中的 `verification_method` 与 `missing_items`。

---

## 9) 非目标

当前明确不做：

- 不接真实硬件；
- 不实现真实 payload 控制；
- 不实现真实飞控动作；
- 不修改 capability registry 数据；
- 不修改 policy gate；
- 不新增危险能力；
- 不做 GUI；
- 不修改 protocol / policy contract；
- 不把硬件清点结果直接写入 adapter/backend；
- 不把 forbidden action 转换为采购目标或开发目标。
