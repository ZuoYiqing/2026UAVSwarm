# PX4 SITL Real Backend Minimal Integration Plan

> 状态：Planning Only（本轮不写真实 PX4/MAVLink 接入代码）

## 本步目标
- 输出第一轮真实 PX4 SITL backend 接入的最小计划。
- 保持已冻结的 protocol/policy contract 不变。
- 明确“先打通最小真实链路，再小步扩展”的实施顺序。

## 设计判断
1. **为什么现在可以进入真实 backend 接入规划阶段**
   - control plane 已冻结且有单测/集成测试保护；
   - adapter selection 已落地（fake/mavlink 可切换）；
   - backend seam / probe seam / transport config wiring 已具备；
   - SITL smoke wiring 路径已经可运行（即使目前仍是 placeholder 语义）。

2. **当前各层准备程度**
   - control plane（protocol/policy/runtime）：已具稳定 contract 与 decision/event/result 主链路；
   - adapter 层：已能完成 mapping、unsupported 前置、结果归一化、trace 打标；
   - backend seam：已具备 `status()/describe()/connect_probe()/execute_mapped_action()` 最小接口与 sitl stub。

3. **为什么第一轮真实接入必须保持最小范围**
   - 真实 PX4/MAVLink 接入引入环境变量（SITL 启停、端口、时序）和系统不确定性；
   - 若首次接入范围过大，会同时叠加架构问题与后端问题，难定位；
   - 当前目标是验证 seam 可替换性，而不是一次性实现完整飞控功能。

4. **为什么不能一上来做完整 PX4 集成**
   - 完整集成需要更多动作语义、状态机、错误恢复、连接管理；
   - 当前代码明确约束“不做复杂连接/心跳/重试状态机”；
   - 直接全量实现会破坏 v0.1 baseline 的可控演进节奏。

## 建议修改文件列表（本轮）
- `docs/px4_sitl_real_backend_minimal_plan.md`（新增）

## 预期后续验证方式
- 本轮：`pytest -q` 维持基线通过（仅文档变更）。
- 下一轮最小真实接入后：
  1. `adapter=mavlink + backend_mode=sitl` 可进入真实 backend 文件实现路径；
  2. 单动作（建议 takeoff）可完成“请求进入真实 backend 并返回统一结构结果”；
  3. action_result / audit / replay 结构保持不变。

---

## 1) 第一轮真实接入的最小目标
建议采用以下最小范围：

- **backend 名称**：`px4_sitl_backend`（作为新的 backend 实现，不替换 adapter 主体接口）。
- **动作范围**：仅 `takeoff`（单动作，最小可观察，便于判断真实路径是否生效）。
- **transport 入口**：仅一个最简单 endpoint 入口（例如单 UDP endpoint 配置位）。
- **成功定义**：只验证最小 E2E 通路（CLI -> runtime -> adapter -> real backend -> normalized result -> audit/replay）。

### 为什么选择 takeoff
- 语义最清晰，触发链路短，最容易判定是否真正进入 backend；
- 相比 goto/land/return_home，对参数与状态依赖更少；
- 便于作为“第一个真实动作”建立回归基线。

## 2) 第一轮成功标准

### A. 真实接入成功（Success）
满足以下全部条件可判定成功：
1. `adapter=mavlink + backend_mode=sitl + backend_enabled=true` 时，调用进入 `px4_sitl_backend` 实现路径；
2. `takeoff` 请求在 backend 层被识别并返回统一 raw result；
3. adapter/gateway/orchestrator 归一化输出保持现有字段结构；
4. audit/replay 仍可读取并关联 request_id 与 policy_decision_event/action_result。

### B. 架构没问题但后端未就绪（Acceptable not-ready）
以下属于可接受状态（非架构失败）：
- `sitl_not_configured`（配置未启用）；
- `backend_probe_failed`（transport 参数不满足）；
- `smoke_not_connected`（backend 存在但未连通）。

### C. 说明 seam 设计有问题（Must-fix）
以下说明分层或 seam 设计存在问题：
- 需要修改 protocol/policy contract 才能接真实 backend；
- adapter 选择逻辑回流到 policy gate；
- real backend 细节直接污染控制面消息字段；
- action_result / audit / replay 结构被真实接入破坏。

### D. 必须保持不变的结构
- `action_result` 的核心字段结构（request_id/status/code/message/evidence_ref/timestamps/accepted/detail/adapter）；
- audit/replay 的事件读写方式与最小消费模型。

## 3) 最小实现顺序（建议）

### A. 真实 backend 文件占位
- 新增 `px4_sitl_backend.py`（仅实现与 `MavlinkBackend` 接口一致的最小骨架）。
- 目的：先建立替换点与依赖边界，不改 adapter contract。

### B. transport/config 最小接入
- 仅消费现有 config：`transport_endpoint/connect_timeout_ms/timeout_ms/retry_count`。
- 目的：不新增控制面字段，验证 wiring 与 probe 在真实 backend 文件中可用。

### C. 单动作 smoke test（takeoff）
- 仅做 takeoff 路径（成功或可解释失败都可接受，但必须结构一致）。
- 目的：验证“真实 backend 路径存在且可观测”。

### D. 成功后扩第二动作
- 建议第二动作 `hover`（次优先 `land`）。
- 目的：在已有回归基线上小步扩展，不一次拉高复杂度。

### 为什么这样排
- 每一步都能独立验证且容易回滚；
- 可将“配置问题/连接问题/动作映射问题”分开定位；
- 最大程度保护现有  v0.1 baseline 与测试稳定性。

## 4) 当前不该做的事
- 不做完整 PX4 集成；
- 不做多动作全覆盖；
- 不做多机；
- 不做 GUI；
- 不改 protocol/policy contract；
- 不把 PX4/MAVLink 细节提升到控制面消息。

## 5) 可选低风险准备项（不强制，本轮不实现真实接入）
1. `src/uav_runtime/adapters/px4_sitl_backend.py` 占位文件（接口一致，返回明确 placeholder）。
2. transport endpoint 规范文档（最小 URI 约定与示例）。
3. smoke success checklist（命令、预期 code、审计字段检查点）。
4. backend state code 约定表（`sitl_not_configured`/`backend_probe_failed`/`smoke_not_connected`/`backend_connected`）。

---

## 结论
当前仓库已经具备进入“第一个真实 PX4 SITL backend 最小接入”规划阶段的条件。下一步应坚持单 backend + 单动作 + 单 transport 入口策略，先验证 seam 可替换与结构稳定，再逐步扩展动作与连接能力。
