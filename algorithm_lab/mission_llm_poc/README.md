# Mission LLM Lab v0.1

独立的任务提案实验模块。当前完成 Step 1–2；尚未下载或运行大模型。

验证结果：19/19 单元测试、40/40 框架案例、5/5 规则基线演示通过。
证据见 docs/verification.json 与 docs/scaffold_validation.json。

输入结构化任务、自然语言目标和集群快照，输出受 JSON Schema 及语义校验约束的
Mission Proposal。现有 demo 使用明确标注的规则基线；它不理解自然语言。
本实验的 schema 是 Algorithm Lab 草案，不是对主线 Plan IR 的修改。

## 快速运行（PowerShell）

工作目录：

```powershell
Set-Location 'D:\2026UAVSwarm-worktrees\algorithm-lab-local-llm-poc\algorithm_lab\mission_llm_poc'
.\.venv\Scripts\python.exe -m uavswarm_llm_lab demo examples/three_uav_inspection.json
.\.venv\Scripts\python.exe -m uavswarm_llm_lab demo examples/uav02_offline.json
.\.venv\Scripts\python.exe -m uavswarm_llm_lab demo examples/policy_denied.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m uavswarm_llm_lab benchmark --output results/scaffold-new.json
```

输出文件拒绝覆盖，复跑时选择新文件名。CLI 返回码：0 表示本轮检查通过；
1 表示提案未通过或 benchmark 未全部达标；2 表示输入/模型/文件错误。
一个合规的 rejected 提案本身可通过校验，但不代表任务可以执行。
benchmark 另外核对预期状态，避免把“全部拒绝”当成模型成功。

在新机器上建立环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps .
```

所有依赖只进入本模块的 .venv。修改源码后需重新安装本包。
运行时依赖为 jsonschema 及其锁定的间接依赖；测试使用 Python unittest。
依赖文件锁定版本但未锁定下载制品哈希；模型部署阶段再记录完整制品清单。

## 模块与契约

- src/uavswarm_llm_lab/schemas：输入、输出 JSON Schema，拒绝额外字段。
- contracts.py：严格 JSON、schema 校验、内容哈希。
- semantic_validator.py：任务完整性、载具资格、Policy DENY、快照时效检查。
- mission_planner.py：规则基线与可选模型推理流程。
- local_model_client.py：显式指定的 loopback 文本推理服务，无工具调用。
- benchmark.py：框架验证和真实模型实验分开统计。
- examples：5 个合成场景，绝不是当前无人机遥测。
- tests：单元验证，无网络/飞控/模型权重依赖。
- docs：代码审计、硬件核查及 Algorithm Delivery Report。

输入必须提供权威 task/action/waypoint 清单。第一版只让模型提出分配并解释，
尚未实现从自然语言自由生成任务图、覆盖路径或坐标。模型不得发明新航点。
同一节点可承担多个任务；输出不是并发飞行时间表。
规则基线按 task_id 排序，选择已分任务最少的合格节点，以 node_id 打破平局；
这是参考方法，不能证明分配最优或穷尽所有可行解。

position_m 使用 north/east/down 米，正 down 表示向下；
高度检查采用相对 scene origin 的 -down，不能解释为 AGL/MSL。
只接收可信的 scene_ned 位置，vehicle_local_ned 不可参与跨机分配。
模块不执行坐标标定，也不会根据机身 yaw 推测坐标变换。

## 真实模型入口（Step 3 之后使用）

先确定模型版本、量化、权重路径、许可证和推理框架，再另行批准下载。
已有经过确认的本机模型服务时，可显式运行：

```powershell
.\.venv\Scripts\python.exe -m uavswarm_llm_lab infer examples/three_uav_inspection.json --base-url http://127.0.0.1:18080/v1 --model APPROVED_MODEL_ID
.\.venv\Scripts\python.exe -m uavswarm_llm_lab benchmark --local-model --base-url http://127.0.0.1:18080/v1 --model APPROVED_MODEL_ID --output results/model-run-001.json
```

上述地址仅为待配置示例，当前未启动服务。客户端只支持 HTTP literal loopback；
不使用环境代理、不跟随重定向、不重试、不发送 tools。
默认请求约束 JSON；如服务不支持会明确失败。--unconstrained 仅用于显式对比。
后续需按实际推理框架验证 schema 子集兼容性、模型身份和推理设置。

记录原始文本、输入/提示词/输出哈希、服务返回模型名、token usage 和端到端耗时。
尚未采集首 token 延迟、峰值显存、权重 revision 或 GPU 吞吐；未知值保持 null。
seed 和 temperature=0 不保证不同硬件/推理实现逐字一致。
当前不做自动修复；原始成功率和未来修复后成功率应分别统计。

## 检验范围

40 个框架案例包含 22 个任务场景、6 个非法输入及12 个输出变异测试。
真实模型 benchmark 只运行22 个任务场景；变异测试不计入模型样本数。
这些用例以结构化任务为判据，不能当成自然语言理解准确率。
合成 fixture 的120秒时效窗口便于测量推理，不能直接用作实机遥测 TTL。

accepted 仅表示通过本模块列出的检查。障碍物、禁飞区、航迹间距、
能源预算、航迹可飞性、时间协调、任务文本与结构化目标的一致性尚未证明。
自然语言若与结构化任务冲突，提示词要求拒绝；当前必须由人工进一步核验。
后续 Runtime 必须重新检查实时状态、Policy 和执行能力。

模块不导入 Runtime，不连接 PX4/MAVLink，不拥有执行权。
execution_authorized 恒为 false。所有模型结果始终是实验提案。
