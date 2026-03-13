# 部署与运行说明（Deployment Guide）

版本：v0.1（Demo）

## 1. 运行环境

- OS：Linux / macOS / Windows（推荐 Linux）
- Python：3.10+
- （可选）GPU：用于 NanoGPT 训练/推理

## 2. 模块部署拓扑（推荐）

### 2.1 单机 Demo

- orchestrator + RAG + sim + API 全部在一个 Python 虚拟环境运行。

### 2.2 生产建议（多进程/多机）

- Orchestrator(API) 服务：提供 /v1/plan, /v1/sim/run
- KB 服务：可拆分为向量库（Chroma/ES 等）
- 模型服务：Teacher/Student 独立部署（vLLM/TGI/自研服务）
- 设备网关：MAVLink/ROS2/MQTT/厂商SDK 适配器

## 3. 安装

### 3.1 最小依赖

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-min.txt
```

### 3.2 完整依赖（含 RAG 向量检索 + 模型）

```bash
pip install -r requirements-full.txt
```

## 4. 运行

### 4.1 一键 Demo

```bash
python -m swarm_ai_platform.cli demo
```

### 4.2 启动 API

```bash
python -m swarm_ai_platform.cli serve --host 0.0.0.0 --port 8000
```

## 5. 联动说明（模块如何协作）

1) `/v1/plan`：Orchestrator 调用 KB 检索 -> Planner 生成 decision_json -> ProtocolSynthesizer 生成 protocol_json -> CodeGen 生成骨架
2) `/v1/sim/run`：Simulation 读取 mission/scene/decision -> 在受限链路下跑闭环 -> Eval 产出指标

## 6. 常见问题

- Q: 没安装 sentence-transformers 会怎样？
  - A: 自动降级为关键词检索，不影响 demo 运行。
- Q: ROS2/Gazebo/PX4 怎么接？
  - A: 请把本仓库的 adapters/ 当作网关接口，生产中在 Linux 上部署 ROS2 + SITL，并将 Telemetry/Command 映射到 canonical protocol_json。
