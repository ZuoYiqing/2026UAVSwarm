# SwarmAI Platform (可运行 Demo)

> 民用科研 / 仿真演训用途的「无人系统集群智能决策 + 协议/代码生成 + RAG 知识库 + 仿真闭环评测」一体化平台。
>
> 本仓库是一个 **可运行的工程化 Demo**：默认用“规则引擎”走通端到端闭环；你可以后续把后端替换为：
> - 通用大模型（Teacher / 强能力）
> - 你自研的 NanoGPT-Edge（Student / 端侧可部署 / 自主 IP）

**核心理念**：

`任务/场景 -> 分层决策(decision_json) -> 协议(protocol_json) -> 代码骨架(codegen) -> 仿真闭环(sim) -> 指标评测(eval)`

> ⚠️ 安全说明：
> - 本项目仅提供仿真和软件框架，不包含现实世界危险用途实现。
> - 若接入真实设备，请务必在合法合规前提下，并启用地理围栏/速度高度限制/人工接管等安全策略。

---

## 0. 目录结构（你关心的部分）

```
.
├── swarm_ai_platform/            # Python 包
│   ├── api/                      # FastAPI 服务
│   ├── orchestrator/             # 端到端编排：RAG -> 决策 -> 协议 -> 代码生成
│   ├── rag/                      # 知识库：本地向量/关键词检索
│   ├── protocol/                 # 协议 JSON + 代码生成（C头文件 / Python dataclasses）
│   ├── sim/                      # 2D 轻量仿真（搜索覆盖 + 丢包链路 + 目标上报）
│   ├── adapters/                 # 真实设备适配器（MAVLink/ROS2/MQTT/厂商SDK Stub）
│   └── cli.py                    # 一键跑通 demo
├── examples/                     # 示例 mission/scene（来自你提供的最小场景）
├── kb/                           # 知识库样例（协议字段 + 交互案例）
├── generated/                    # 运行后生成：decision/protocol/代码骨架/评测报告
└── docs/                         # 产品/接口/部署文档（公司化交付模板）
```

---

## 1. 快速开始（最小依赖，3 分钟跑通闭环）

### 1.1 安装

建议 Python 3.10+。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -U pip
pip install -r requirements-min.txt
```

> 如果你希望启用向量检索（sentence-transformers / chromadb）或 NanoGPT 训练/量化，请装：
>
> ```bash
> pip install -r requirements-full.txt
> ```

### 1.2 一键运行 demo

```bash
python -m swarm_ai_platform.cli demo
```

运行后你会得到：
- `generated/decision.json`
- `generated/protocol.json`
- `generated/codegen/messages.h`（C 头文件骨架）
- `generated/codegen/messages.py`（Python dataclasses）
- `generated/sim_report.json`（仿真评测指标）

---

## 2. 启动 API 服务（给前端/其他系统调用）

```bash
python -m swarm_ai_platform.cli serve --host 0.0.0.0 --port 8000
```

打开：
- Swagger: http://localhost:8000/docs

常用接口：
- `POST /v1/plan`  输入 mission/scene，返回 decision/protocol + 代码生成产物路径
- `POST /v1/sim/run`  输入 mission/scene/decision，运行仿真并返回指标

---

## 3. 如何替换“规则引擎”为你的模型（Teacher / NanoGPT-Edge）

### 3.1 替换决策后端

在 `swarm_ai_platform/orchestrator/planner.py` 中：
- `RulePlanner`：默认规则引擎
- `LLMPlanner`：预留 LLM 接口（可接本地 transformers / vLLM / 你内网部署的模型服务）
- `NanoGPTPlanner`：预留 NanoGPT-Edge 权重加载与生成

### 3.2 训练 NanoGPT-Edge（从零实现 Transformer + MoE + SFT + 量化）

代码位置：`swarm_ai_platform/models/nanogpt/`。

> 训练数据：你可以用本仓库自带的 `kb/` 与 `examples/` 生成 SFT 数据，也可以接入你现有的 Teacher 样本库。

---

## 4. 对接真实设备（异构无人机/物联网）建议架构

建议采用 **“统一控制平面协议 + 适配器网关层”**：

- 控制平面（你自定义的 protocol_json + 编码/解码）
- 适配器（MAVLink / ROS2 / MQTT / 厂商 SDK）

本仓库默认只提供 Stub 与接口定义，避免误用。你可以在合法合规前提下完善：
- `adapters/mavlink.py`
- `adapters/ros2.py`
- `adapters/mqtt.py`
- `adapters/vendor_sdk_stub.py`

---

## 5. 许可与引用

- 本项目是教学/科研性质 demo，不含第三方模型权重。
- NanoGPT 训练框架参考了 Andrej Karpathy 的 nanoGPT 思路（请在你正式交付/开源时补充清晰引用）。
