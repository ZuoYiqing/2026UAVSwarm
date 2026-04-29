# PX4 SITL Dependency and Environment Readiness Plan (v0.1 -> v0.2-prep)

## 1) 本步目标
在不引入完整飞控控制逻辑的前提下，固化**第一轮真实 PX4 SITL backend**的依赖路线与环境就绪检查标准，确保后续实现可控、可回退、可观测。

---

## 2) 设计判断：pymavlink vs MAVSDK

### 结论（第一轮建议）
优先选择 **pymavlink** 作为第一轮真实 backend 依赖路线。

### 为什么优先 pymavlink
- 与当前代码中的 `mavlink` adapter/backend 语义最贴近，接入 seam 更直接；
- 依赖更轻、可控度高，适合先完成“最小连接 + 最小命令发送”验证；
- 更容易把底层细节封装在 backend 内部，不污染 protocol/policy contract。

### pymavlink 优点
- 低层可控、透明，便于精确控制第一轮 smoke 行为；
- 与 MAVLink 概念一致，便于和当前 `mavlink_*` 结构对应；
- 对“先打通单动作 takeoff 路径”的最小目标更聚焦。

### pymavlink 风险/代价
- 需要自行处理更多底层细节（连接状态、超时策略、命令确认）；
- API 抽象层较低，后续工程化封装工作更多。

### MAVSDK 优点
- 更高层 API，业务语义更友好；
- 部分常见控制流程更快上手。

### MAVSDK 风险/代价（在本阶段）
- 与当前以 MAVLink/backend seam 为核心的结构相比，抽象层次不一致；
- 可能引入额外运行时和兼容性变量，不利于第一轮最小路径验证；
- 一开始就双路线（pymavlink + MAVSDK）会显著增加测试矩阵与排障复杂度。

### 为什么第一轮不应同时支持两套依赖
- 违背“单 backend + 单动作 + 单 transport”最小化原则；
- 会引入接口行为分叉，增加 contract 稳定性风险；
- 让 smoke 失败时难以快速定位是 backend 实现问题还是依赖栈差异问题。

---

## 3) 第一轮最小依赖路线（建议固定）

- **路线**：`pymavlink`
- **安装方式**：作为可选依赖（optional dependency）提供，例如 extras：`.[sitl]`
- **默认行为**：不安装 `pymavlink` 时，系统继续走当前 placeholder/stub 路径，不影响 v0.1 baseline

### optional dependency 策略
- `pymavlink` 不进入 core 必装依赖；
- CI 默认单元测试不要求真实 SITL；
- 仅在专用 smoke 环境启用 `sitl` 依赖。

### 未安装时的降级策略
- readiness/probe 返回明确 code（如 `dependency_missing`）；
- execute 返回 `accepted=false` + 结构化错误信息；
- 不抛出未处理异常到控制面。

### 对现有 pytest 的影响
- 默认不应影响现有测试（保持当前通过基线）；
- 新增的真实 backend smoke 用例应标记为可选（仅在 SITL 环境下启用）。

---

## 4) 最小环境 readiness check 设计

第一轮建议按以下顺序检查：
1. **依赖检查**：`pymavlink` 是否可导入；
2. **配置检查**：`transport_endpoint` 是否存在且格式合法；
3. **连接检查**：在给定超时内能否完成 SITL 连接探测；
4. **命令前检查**：仅当 probe `ok=true` 时允许进入发送。

### 超时与错误码建议
- 连接探测超时：`backend_probe_timeout`
- 连接失败：`backend_probe_failed`
- 缺少依赖：`dependency_missing`
- 缺少配置：`backend_not_configured`
- 未进入真实实现：`not_implemented`

### 无真实后端时返回约定
- `accepted=false`
- `status` 保持可审计（如 `not_connected` / `not_configured`）
- `message/detail` 明确说明是 readiness 阶段失败，不是 policy 拒绝。

---

## 5) 第一轮 smoke test 目标（严格最小）

固定目标：
- `backend=px4_sitl_backend`
- `action=takeoff`
- `adapter=mavlink`
- `backend_mode=sitl`

只验证：
1. 连接探测可执行并返回结构化结果；
2. 单动作命令发送路径可到达 backend；
3. normalized result + audit/replay 链路不断裂。

不验证：
- 多动作序列
- 多机协同
- 复杂飞行状态机
- 长时间稳定性

---

## 6) 当前明确不做的事

- 不做完整飞控任务控制；
- 不做 GUI 扩展；
- 不做 ROS2 集成；
- 不做多机支持；
- 不做复杂重试/心跳管理；
- 不把 MAVLink/PX4 细节上升到 protocol/policy contract。

---

## 7) 低风险代码准备项（可先做）

1. optional dependency 检测函数（例如 `check_pymavlink_available()`）；
2. backend readiness 标准错误码常量（集中定义，避免散落字符串）；
3. `px4_sitl_backend.py` 的 import guard（延迟导入 + 明确降级码）；
4. 新增 `docs/px4_sitl_setup.md`（本地 SITL 环境准备清单）；
5. 可选 smoke test 标记（例如 `@pytest.mark.sitl`）及运行说明。

> 注：以上准备项均应保持“非侵入式”，不改 protocol/policy 主线 contract。

---

## 8) 预期验证方式

- 单元层：
  - 依赖缺失时的降级码和返回结构稳定；
  - readiness check 的超时/失败分支可预测。
- 集成层（可选环境）：
  - 在 SITL 环境下执行最小 takeoff smoke 路径；
  - 审计/回放记录结构不变。
- 回归层：
  - 现有 `pytest` 基线保持通过。
