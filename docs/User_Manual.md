# 产品说明书（用户手册）- SwarmAI Platform

版本：v0.1（Demo）

## 1. 适用范围

- 适用于民用科研、巡检演训、数字孪生仿真验证、协议/代码自动生成等场景。

## 2. 快速开始（本地）

### 2.1 安装

```bash
python -m venv .venv
source .venv/bin/activate   # Windows 用 .venv\Scripts\activate
pip install -r requirements-min.txt
```

### 2.2 运行 Demo

```bash
python -m swarm_ai_platform.cli demo
```

你会在 `generated/` 下看到：

- `decision.json`：分层决策方案
- `protocol.json`：协议定义
- `messages.h` / `messages.py`：代码骨架
- `sim_report.json`：仿真指标

### 2.3 启动 API 服务

```bash
python -m swarm_ai_platform.cli serve --host 0.0.0.0 --port 8000
```

然后访问：

- Swagger 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 3. 常见问题

### Q1：如何替换为大模型/自研模型？

- 规则后端：默认 RulePlanner（可稳定跑通闭环）
- Teacher：使用 `orchestrator/llm_planner.py` 中的 `TransformersTeacherPlanner`（需要安装 transformers）
- Student：训练 NanoGPT-Edge 后，在 pipeline 中替换 planner 即可

### Q2：如何接入真实设备？

本 Demo 仅提供适配器接口 `DroneAdapter`，真实对接请在合法合规前提下实现：

- MAVLink（PX4/ArduPilot）
- ROS2（DDS）
- MQTT/HTTPS/WebSocket（物联网/云）
- 厂商 SDK（如 DJI Mobile SDK / OSDK / Payload SDK / Cloud API）
