# Mission LLM Lab v0.1

2026-10-05 新增：[Qwen3.5-0.8B 独立真实实验](docs/QWEN_0_8B_EXPERIMENT_20261005.md)。
已在 D 盘下载并核验，4050 完成 54 次语义请求；原提示词三轮均 3/8，显式开发提示词三轮均 5/8。
原三机提案另请求两次，均因输出截断拒绝；已补齐截断响应证据记录。
这是推理，不是训练或飞行；没有证明自主巡检或板端部署可用。
面壁等异厂候选和板端差异见[小模型路线](docs/SMALL_MODEL_CANDIDATES_20261005.md)。
下文保留各阶段的历史记录，不代表这些阶段都已完成真实模型评测。

独立的任务提案实验模块。已完成Step 1–2及Step 3的D盘下载、校验和首次模型加载。
2026-09-22：[本地准备与资源实测](docs/LOCAL_MODEL_PREPARATION_20260922.md)。
4B Q4模型已加载并完成一次真实任务提案；原始JSON有效且三项分配正确，
但因顶层原因码错误被校验器拒绝。详见[首次提案与加固记录](docs/FIRST_MODEL_REQUEST_20260928.md)。

截至首次本地模型请求的验证：21/21单元测试、40/40框架案例、9/9离线下载器测试通过；
真实模型1次请求完成但0次被接受。历史证据见docs/verification.json，
当前证据见[verification_20260928.json](docs/verification_20260928.json)。
与 Runtime `524cdf8` 的接口约定见[执行接口交接](docs/RUNTIME_EXECUTION_HANDOFF_20260928.md)。
原三机巡检样例仍是研究提案，包含尚不可执行的观察与返航动作；
另有[仅飞行验证样例](examples/flight_validation_only.json)供转换器验证，不能报告为巡检完成。
2026-09-29 新增[目标语义绑定与集成交接](docs/INTENT_GROUNDING_HANDOFF_20260929.md)：
新输入不带 `tasks[]`，由目标与带来源的场景可供性派生任务；
[simple_recon_v0_1 输入](examples/simple_recon_flight_intent.json)和
[转换器可读输出](examples/simple_recon_flight_handoff.json)均为合成飞行验证证据。
本地 4B Q4 模型已真实运行一次受限目标绑定（通过）和一次加固后三机提案（原文含未经证明的
路径/能源结论，离线回放已拒绝）。本轮记录见
[verification_20260929.json](docs/verification_20260929.json)；29/29 单元测试通过。
2026-10-05：[本地语义模型评测入口与诚实状态](docs/GROUNDING_MODEL_EVAL_20261005.md)。
9 条人工标注的合成输入和独立评分器已建立；规则基线 5/8 可评分语义匹配、9/9 接受判定。
受当前可用系统内存低于 5 GiB 门槛限制，本轮尚未加载 4B 模型，不能报告新的模型成绩。
2026-09-30 新增[物理场景引用绑定与第二轮交接](docs/ROUND2_SCENE_BINDING_HANDOFF_20260930.md)：
`bind-scene` 读取主线导出的楼群/建筑可供性，将自然语言方位绑定到真实实体 ID，
但不把建筑中心当成飞行航点。最高建筑并列时要求澄清；巡检/观察需求因感知执行能力未确认
而阻止生成可执行提案。见[本轮验证记录](docs/verification_20260930.json)；34/34 单元测试通过。

2026-09-20 更新：[离线分层模型研究与下一步实验](docs/OFFLINE_LAYERED_MODEL_RESEARCH_20260920.md)、
[参考资料核实记录](docs/REFERENCE_INTAKE_20260920.md)。已同步合并后的主线6116912；
早期报告和verification.json是当时的历史记录，不表示当前Git提交状态。
首轮待批准的[下载清单](docs/DOWNLOAD_PROPOSAL_20260920.json)已固定文件版本、大小和发布方哈希，
三个主要制品合计约3.39GB；现已获批准、下载并在本地校验。
原清单保持历史提案状态，实际进度见[准备记录](docs/local_model_preparation_20260922.json)。

部署要求：所有任务推理完全离线，禁止闭源云模型调用、云端回退和自动联网下载。
制品准备阶段与断网部署阶段分开验收。独立准备脚本显式下载批准制品，
推理启动不自动联网取件；尚未完成隔离网络的真实引擎冷启动验收。

输入结构化任务、自然语言目标和集群快照，输出受 JSON Schema 及语义校验约束的
Mission Proposal。现有 demo 使用明确标注的规则基线；它不理解自然语言。
本实验的 schema 是 Algorithm Lab 草案，不是对主线 Plan IR 的修改。

## 快速运行（PowerShell）

工作目录：

```powershell
Set-Location 'D:\2026UAVSwarm-worktrees\algorithm-lab-local-llm-poc\algorithm_lab\mission_llm_poc'
.\.venv\Scripts\python.exe -m uavswarm_llm_lab demo examples/three_uav_inspection.json
.\.venv\Scripts\python.exe -m uavswarm_llm_lab ground examples/simple_recon_flight_intent.json
.\.venv\Scripts\python.exe -m uavswarm_llm_lab bind-scene 'D:\2026UAVSwarm\docs\fixtures\simple_recon_v0_1_scene_affordances.json' '飞到北边那片楼群的东侧'
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

本地实验脚本会显式从本模块的 `src` 加载当前源码，并把主动配置的临时目录和缓存放在
D盘 `artifacts` 下，因此修改实验代码后无需为了试跑反复构建安装包。
直接执行Python测试时，先把 `PYTHONPATH` 设为本模块的 `src`；不要使用系统临时目录构建。

## 模块与契约

- src/uavswarm_llm_lab/schemas：输入、输出 JSON Schema，拒绝额外字段。
- contracts.py：严格 JSON、schema 校验、内容哈希。
- semantic_validator.py：任务完整性、载具资格、Policy DENY、快照时效检查。
- mission_planner.py：规则基线与可选模型推理流程。
- local_model_client.py：可选的本机推理适配器，只调用 loopback 文本推理服务，无工具调用。
- benchmark.py：框架验证和真实模型实验分开统计。
- examples：5 个合成场景，绝不是当前无人机遥测。
- tests：单元验证，无网络/飞控/模型权重依赖。
- docs：代码审计、硬件核查及 Algorithm Delivery Report。

原有 `demo` / `infer` 路径仍以结构化 task/action/waypoint 清单为权威输入。
新增 `ground` 路径从明确标签的自然语言目标派生 `tasks[]`，不生成新坐标；
`ground-model` 允许本地模型提出语义绑定候选，但真实模型结果仍待复跑。
两条路径的能力指标分别记录，不能把规则绑定结果当作模型理解能力。
同一节点可承担多个任务；输出不是并发飞行时间表。
规则基线按 task_id 排序，选择已分任务最少的合格节点，以 node_id 打破平局；
这是参考方法，不能证明分配最优或穷尽所有可行解。

position_m 使用 north/east/down 米，正 down 表示向下；
高度检查采用相对 scene origin 的 -down，不能解释为 AGL/MSL。
只接收可信的 scene_ned 位置，vehicle_local_ned 不可参与跨机分配。
模块不执行坐标标定，也不会根据机身 yaw 推测坐标变换。

## 真实模型入口（Step 3 之后使用）

这里的client只是程序之间传递输入/输出的适配器，不是新的前端控制台，
也不是模型本身；不要求安装Ollama。当前实现使用本机HTTP，未来也可实现
同进程Python/C++或硬件厂商SDK后端，仍返回同样的实验提案；这些后端尚未实现。
无人平台上是伴随计算机加载本地权重，不是把聊天页面或大模型装进飞控。
现有前端不变；如何集成由Integration Owner决定。

首轮模型、量化和便携引擎已固定并获批；新增制品仍须先确认。
已有经过确认的本机模型服务时，可显式运行：

```powershell
.\.venv\Scripts\python.exe -m uavswarm_llm_lab infer examples/three_uav_inspection.json --base-url http://127.0.0.1:18080/v1 --model APPROVED_MODEL_ID
.\.venv\Scripts\python.exe -m uavswarm_llm_lab benchmark --local-model --base-url http://127.0.0.1:18080/v1 --model APPROVED_MODEL_ID --output results/model-run-001.json
```

本机已在该地址完成一次加载及任务请求，当前服务已停止；重新启动仍要求至少5GiB可用RAM。
客户端只支持 HTTP literal loopback；
不使用环境代理、不跟随重定向、不重试、不发送 tools。
默认请求约束 JSON；如服务不支持会明确失败。--unconstrained 仅用于显式对比。
后续需按实际推理框架验证 schema 子集兼容性、模型身份和推理设置。
loopback限制只约束本适配器，不能证明其后面的服务不会联网。
正式部署还需预置全部权重/分词器/视觉处理器、限制引擎出站网络、
关闭遥测及自动更新，并在隔离网络环境完成冷启动测试。

记录原始文本、输入/提示词/输出哈希、服务返回模型名、token usage 和端到端耗时。
单请求已采集总耗时、服务端吞吐及资源点样；首token、可靠峰值和p50/p95仍未知。
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
