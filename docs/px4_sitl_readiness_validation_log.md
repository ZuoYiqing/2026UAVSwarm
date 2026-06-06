# PX4 SITL Readiness Validation Log

## 0. 文档用途与边界

本文档用于固化 **PX4 SITL readiness** 手工验证结果与准入条件。

### 当前阶段边界（冻结）
- 本文档只记录 readiness；
- 不记录真实 takeoff；
- 不执行 `arm`；
- 不执行 `set_mode`；
- 不发送 `command_long`；
- 不作为飞行安全验证；
- 不修改 protocol/policy contract。

---

## 1. 验证环境信息（本轮）

- 验证日期：2026-05-26
- 操作系统：Linux（CI/sandbox 环境）
- Python 环境：仓库默认测试环境（`python -m pytest` 可运行）
- 当前 Git commit：待实际执行人填写
- `pymavlink` 是否安装：按场景区分（A 为未安装语义，C 为已安装但探测失败语义）
- PX4 SITL 是否启动：A/B/C 场景按“未启动或不可达”处理
- `transport_endpoint`：`udp://127.0.0.1:14540`（B 场景为空）

> 说明：本轮聚焦已验证语义与手工命令模板，不做真实飞控动作验证。

---

## 2. 当前已验证场景记录

### A) dependency_missing（已验证）

- 执行命令：
  ```bash
  python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --pretty
  ```
- 预期：
  - `code=dependency_missing`
  - `readiness=not_ready`
- 说明：未安装 `pymavlink` 时的结构化降级。
- 实际记录：由执行人粘贴 JSON 输出与截图链接。
- 结论：通过/不通过（待填写）

---

### B) backend_not_configured（已验证）

- 执行命令：
  ```bash
  python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --pretty
  ```
- 预期：
  - `code=backend_not_configured`
  - `reason=transport_endpoint_missing`
  - `readiness=not_ready`
- 实际记录：由执行人粘贴 JSON 输出与截图链接。
- 结论：通过/不通过（待填写）

---

### C) backend_probe_failed（已验证）

- 执行命令：
  ```bash
  python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --connect-timeout-ms 1500 --pretty
  ```
- 预期：
  - `code=backend_probe_failed`
  - `readiness=not_ready`
- 说明：`pymavlink` 已安装，但 PX4 SITL 未启动或 endpoint 不可达。
- 实际记录：由执行人粘贴 JSON 输出与截图链接。
- 结论：通过/不通过（待填写）

---

## 3. Readiness 语义冻结规则

- `dependency_missing -> not_ready`
- `backend_not_configured -> not_ready`
- `backend_probe_failed -> not_ready`
- `sitl_not_configured -> not_ready`
- `smoke_not_connected -> not_ready`
- `backend_connected -> ready`

> 规则解释：只有 `connect_probe.code == backend_connected` 时，readiness 才允许是 `ready`。

---

## 4. backend_connected 准入前置条件

进入 `backend_connected` 验证前，需要满足：

1. `pymavlink` installed；
2. `transport_endpoint` configured；
3. PX4 SITL 已启动；
4. endpoint 与 `px4_sitl_backend` 配置一致；
5. `connect_timeout_ms` 设定合理；
6. `connect_probe` 能收到 heartbeat 或等价最小探测成功信号。

---

## 5. 后续 backend_connected 验证命令模板

```bash
python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --connect-timeout-ms 3000 --pretty
```

预期：
- `code=backend_connected`
- `readiness=ready`

---


## 5.1 backend_connected 验收标准（手工）

当执行以下命令时：

```bash
python -m uav_runtime.console.cli check-backend --backend px4_sitl --backend-mode sitl --backend-enabled --transport-endpoint udp://127.0.0.1:14540 --connect-timeout-ms 3000 --pretty
```

应同时满足：
- `code=backend_connected`
- `readiness=ready`
- `dependency.present=true`
- `transport_endpoint_configured=true`

并在验证记录中附上：
- PX4 SITL 启动命令；
- endpoint 记录；
- `check-backend` 原始 JSON 输出。

> 注意：`backend_connected` 仅表示 heartbeat/probe 成功，不代表已经执行任何飞控动作。

---
## 6. 附件与追踪

- 日志文件路径：
- 控制台输出文件：
- 截图/录屏链接：
- 关联 issue/任务单：
- 责任人：
- 复核人：
