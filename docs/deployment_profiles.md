# Ground / Edge 部署分层设计（v0.1 之后）

## 0. 文档目的
本文件用于把当前单一 demo runtime 过渡到“双部署 profile 设计”阶段：
- Ground Profile（地面站满血版）
- Edge Profile（机载板轻量版）

约束：
- 不改已冻结核心 contract
- 不引入 GUI / PX4 / MAVLink / ROS2 真实实现
- 先完成结构与演进主线清晰化

---

## 1. Ground Profile / Edge Profile 定义

## 1.1 Ground Profile（地面站）
定位：控制面主节点 + 运维观察主节点。\
职责重点：
- 完整策略评估与审计追踪
- 完整 replay / 诊断能力
- 更丰富的 adapter 仿真与测试工具链
- 面向人机调试、任务编排和问题复盘

特点：
- 日志更全
- 依赖可更重
- 功能面更完整

## 1.2 Edge Profile（机载伴随计算板）
定位：执行面近端节点 + 受限环境下的策略执行子集。\
职责重点：
- 按冻结 contract 消费控制面输入
- 进行低延迟、轻量、确定性执行
- 维持必要安全约束与最小审计

特点：
- 资源受限（算力/存储/网络）
- 功能收敛、日志抽样
- 强调稳定性与可预测性

---

## 2. 两者共享与差异

## 2.1 必须共享（Shared Core）
1. 协议对象与字段语义（Envelope / ActionRequest / PolicyDecisionEnvelope / ActionResult）
2. reason/error/decision 命名与 registry 规则
3. policy 核心语义边界（ALLOW / DENY / REQUIRE_CONFIRM / PREEMPT 合同约束）
4. adapter 调用的 command 级接口约定

## 2.2 可以不同（Profile-specific）
1. 日志粒度与保留策略（Ground 全量，Edge 精简）
2. adapter 数量与实现深度（Ground 偏测试/仿真，Edge 偏执行）
3. runtime 周边能力（Ground 可含更多分析工具，Edge 保持最小集）
4. 可选依赖规模与启动方式

---

## 3. 当前仓库模块映射（基于现状）

### 3.1 `protocol`
- 归类：**shared core**
- 原因：是两端必须一致的 contract 边界。

### 3.2 `policy`
- 归类：**shared core**（Edge 可子集执行）
- 原因：语义必须一致；Edge 后续可降级执行某些分支，但不应改变语义定义。

### 3.3 `runtime`
- 归类：**shared but reduced on edge**
- Ground：完整 orchestrator + 审计/回放 + 调试友好
- Edge：保留最小执行闭环，日志/回放可简化

### 3.4 `adapters`
- 归类：**shared but reduced on edge**
- Ground：更偏 fake/sim/test adapter 强化
- Edge：保留与实际执行链路最相关的最小 adapter 子集

### 3.5 `skills`
- 归类：**shared but reduced on edge**
- Ground：保留全技能注册与验证工具
- Edge：仅保留任务需要的最小技能集

### 3.6 `console`
- 归类：**ground only**（当前阶段）
- 原因：CLI 主要面向地面调试与演示；Edge 通常不以人工 CLI 作为主入口。

### 3.7 `audit/replay`
- 归类：**shared but reduced on edge**
- Ground：完整审计 + replay 分析
- Edge：保留必要审计（安全/追责/关键事件），回放能力可简化

---

## 4. 哪些模块应在哪端存在

## 4.1 Ground only（当前建议）
- Console 全量命令入口
- 完整 replay 分析工具
- 演示/测试辅助输出与诊断增强

## 4.2 Edge 必须下沉（后续）
- 最小 runtime 执行闭环
- policy 关键约束执行能力
- adapter command 执行入口
- 最小审计记录（关键决策与执行结果）

## 4.3 双端都存在但深度不同
- runtime / policy / adapters / skills / audit
- Ground 偏“全量可观测、可调试”
- Edge 偏“最小可用、确定性、资源受控”

---

## 5. 后续演进顺序建议（A~E）

## 推荐顺序
1. **A. fake adapter 强化**
2. **B. adapter contract 收口**
3. **C. SITL / MAVLink 接口准备（仅接口准备，不接真实）**
4. **D. Ground Profile 继续增强**
5. **E. Edge Profile 抽取**

## 排序理由
- A 先行：以最低风险提高演示与回归可靠性，快速发现执行链路问题。
- B 次之：先把接口边界稳定，避免后续 SITL 准备阶段反复改口。
- C 再做：先准备接口与目录边界，不马上落真实协议实现。
- D 随后：Ground 是当前主开发与验证阵地，优先增强工具链收益最高。
- E 最后：在 Ground 主线稳定后抽取 Edge，避免重复返工。

---

## 6. 当前不该优先做的事
1. 不该优先做 GUI（当前核心是运行时链路与可复现性，不是前端交互）。
2. 不该优先做多机协同全量功能（当前单链路闭环仍在强化阶段）。
3. 不该优先做模型压缩/国产算力迁移（应在功能边界稳定后再评估）。
4. 不该为了展示重写主逻辑（会破坏 baseline 可追溯性与后续可维护性）。

---

## 7. 下一阶段 1~2 周任务清单（最小实现主线）

## Week 1（Ground 主开发）
1. 固化 demo 三路径 + replay 自动化脚本（命令级 smoke，不改 contract）
2. fake adapter 场景增强（成功/拒绝/异常模拟一致化）
3. adapter 层错误码与输出字段一致性检查（仅收口，不扩语义）
4. Ground 审计输出模板稳定化（便于专家复盘）

## Week 2（为 Edge 留接口）
1. 引入 deployment profile 配置草案（ground/edge 开关，不改 contract）
2. 拆分运行时启动配置（同一核心，不同 profile 参数）
3. 为 SITL 预留 adapter 注册入口与占位文档（不接真实实现）
4. 增加 profile 维度测试矩阵占位（先 smoke 层）

---

## 8. 低风险、值得顺手做的准备项（仅建议，不在本轮改代码）
1. `profile` 启动参数（`--profile ground|edge`）与配置文件占位。
2. `deployment config` 最小结构（日志级别、审计级别、replay 保留窗口）。
3. adapter registry 小改造：支持按 profile 过滤可注册 adapter。
4. audit level 分级：`full / essential`，Ground 与 Edge 可切换。
5. demo 输出模式开关：`--pretty` 与 `--compact` 并存（不改业务语义）。

---

## 9. 结论
当前阶段最优策略不是扩展新系统，而是：
- 以 Ground Profile 作为主开发与验证中心
- 以 shared core 固定语义与 contract
- 以 reduced Edge 作为后续抽取目标

这样可在不破坏 v0.1 baseline 的前提下，为 fake adapter 强化与 SITL 对接提供稳定输入。
