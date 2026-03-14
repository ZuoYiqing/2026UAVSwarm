# 产品设计说明书（PDD）- SwarmAI Platform

版本：v0.1（Demo）

## 1. 总体架构

### 1.1 逻辑分层

1. **应用层**：Web/桌面端/脚本工具
2. **平台服务层**：计划生成、协议生成、代码生成、评测、资产管理
3. **智能层（双引擎）**：
   - Teacher（强能力）：通用大模型 + 领域微调/蒸馏
   - Student（离线/自研 IP）：NanoGPT-Edge（<50M）+ SFT + 量化 + RAG
4. **控制平面协议层**：平台内部 canonical protocol_json
5. **适配器/网关层**：MAVLink/ROS2/MQTT/厂商 SDK
6. **设备层**：无人机/无人车/边缘节点/载荷

### 1.2 数据流（端到端）

`mission_json + scene_json -> (RAG) -> decision_json -> protocol_json -> codegen -> sim/eval`

## 2. 模块设计

### 2.1 Orchestrator（编排器）

职责：把“检索/决策/协议/代码/评测”串成单一流水线；产物可版本化与回溯。

- 输入：mission_json, scene_json
- 输出：decision.json, protocol.json, codegen/..., sim_report.json

### 2.2 RAG（知识库）

- 文档类型：协议字段定义、交互案例、约束规则、操作手册
- 检索策略：
  - MVP：关键词/向量检索（sentence-transformers 可选）
  - v1：多索引（字段索引、案例索引、错误码索引） + rerank

### 2.3 决策生成（Planner）

- RulePlanner：规则基线，100% 可审计
- LLMPlanner：对接 Teacher 模型服务（可内网部署）
- NanoGPTPlanner：对接 Student 小模型（端侧离线）

输出遵循 decision_schema，强调“规则级决策”而不是逐步控制。

### 2.4 协议生成（ProtocolSynthesizer）

- 从 KB 中检索已有消息定义
- 根据 decision_json 的“消息使用提示”选择需要的消息
- 输出 protocol_json 并通过 schema 校验

### 2.5 CodeGen（代码骨架生成）

- 输入：protocol_json
- 输出：
  - messages.h（C 结构体骨架）
  - messages.py（Python dataclasses）

### 2.6 Simulation & Eval（仿真与评测）

- MVP：2D 轻量仿真（覆盖率、丢包率、响应时间）
- v0.4：接入 PX4 SITL + Gazebo + ROS2，形成更高保真闭环

## 3. 数据规范

- 统一中间表示：mission_json / scene_json / decision_json / protocol_json
- 约束：所有输出必须可用 JSON Schema 验证

## 4. 可靠性与安全设计

- LLM 只产生“可审计的规则/计划/协议”，不直接控制执行器
- 适配器层实现硬约束（地理围栏、速度高度限制、权限控制）
- 所有自动生成产物必须通过：schema 校验 + 单元测试 + 仿真回归
