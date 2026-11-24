# Mission LLM Lab v0.1

## 任务书到候选计划：隔离联调样例

本样例固定于项目基线 `6a680fe`。它复用现有 Mission Context / Proposal v0.1：
原话决定选择哪些目录设备，选中的设备才产生任务和航点。候选只给测试桩或隔离 Fake Adapter
作输入；示例包装不是新冻结契约，`execution_authorized` 和 `runtime_submission_allowed`
始终为 `false`。不启动模型、Runtime、仿真或执行链。

| 输入 | 结果 |
| --- | --- |
| 请巡检模拟冷却泵和模拟仪表柜。 | UAV-01 负责泵、UAV-02 负责柜，各有两个夹具航点并保留 `OBSERVE` |
| 请巡检模拟仪表柜。 | 只输出柜的两个航点和 UAV-02 分工，不生成泵的任务 |
| 请巡检模拟设备。 | 目标有两个候选，`TARGET_AMBIGUOUS`，无部分计划 |
| 有明确目标，但缺少夹具证据标识 | `FIXTURE_EVIDENCE_REQUIRED`，无计划 |

样例标记 `simple_recon_v0_1 / simple_recon_v0_1-map-1`、共享 `scene_ned`。试验泵/柜、
节点状态和航点不是物理场景导出或标定证据。任务分工只比较夹具里可用节点到入口的平面距离；
电量是筛选阈值，不是续航估计。已过滤 stale 节点；任务任一不确定就不交部分结果。
实际场景可供性清单仍不完整，本样例没有认证障碍物、禁飞区、几何间距、返航或相机能力。

Runtime 的 `PlanExecuteRequest` 不直接收 `assignments[]`：执行形状需要
`plan_id / scene_id / map_version / steps[]`，步骤需明确 `step_id / action_type / node_id / params`，
并由独立入口负责人工确认和 Policy。现有 `proposalToPlan` 会查同一份 Context 的有序航点 ID；
两份巡检候选都因为 `OBSERVE` 尚不可展开被**整份拒绝**。不删观察步骤把飞完当巡检完成。
候选只要求后续提供采集证据；目前没有观测、检测结果或完工声明。

另有**独立的仅移动用例**：`target-001` 是场景的绿色标记，不是真实设备或检测结果。
Fake 夹具假定 UAV-02 已在起始点，仅验证两个有序 `goto` 的输入形状及 `plan_id` 关联，
不含起飞、降落、返航、采集和观察。形状通过请求解析器时只使用内存里的 `decision=reject`，
不构造可以直接提交的外层审批请求。真实执行入口不能凭额外的 `scope` 或
`execution_authorized` 字段判断可执行；联调方必须把测试产物留在独立 Fake 入口。
用例的 `plan_id` 可给 Runtime 的 `mission_id` 做关联，`run_id` 只能由实际的 Fake
生命周期生成，算法不伪造。`completed` 也只能由对应执行阶段的证据产生。

移动例的已在位起点和去程两点，与仿真侧本地提交 `f6e5a1a` 的离线参考一致；
这个参考不作为本模块的依赖。起点不是 UAV-02 的实际起降点，也没有从起降点前往起点的
首航段。该样例不能作为实机或 SITL 上机许可。
前端和三维可把这些数据标为候选供审阅，但不能用候选点补载具位姿，也不能用轨迹经过目标、
模型文本或测试报告补造任务进度。进度只消费同一次执行的 Runtime 证据。

在本模块目录复现（新目录，文件不会覆盖）：

```powershell
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory artifacts/patrol-fixture-check
python -B -m uavswarm_llm_lab.patrol_candidate --input examples/patrol_candidate_requests_v0_1.json --output artifacts/patrol-fixture-check/candidates.json
node scripts/check_patrol_candidate_mapping.mjs artifacts/patrol-fixture-check/candidates.json artifacts/patrol-fixture-check/mapping-proof.json
$env:PYTHONPATH = 'src;../../src'
python -B scripts/check_patrol_candidate_runtime_shape.py artifacts/patrol-fixture-check/candidates.json artifacts/patrol-fixture-check/mapping-proof.json artifacts/patrol-fixture-check/runtime-schema-proof.json
```

## 离线协作评测（M-v0.1 / B-v0.2）

这两套题分别测模拟巡检的异构派工，以及抽象记分游戏里的队友协作和对手响应。
评测不调用 Runtime、主控台、Harness 或飞控，结果不授权执行。

- **原题仍在**：[A-v0.4 的 12 条草案](docs/ANCHORING_A_V04_SWARM_GAME_DRAFT.md)原样保留；
  它测读懂指代和顺序，不测分工。旧工作树的 B-v0.1 是一个模型替两枚棋子填答案的单轮快照，
  与下述多回合题不混比分。
- **异构派工 M-v0.1**：[8 个决策快照和 1 局反馈模拟](src/uavswarm_llm_lab/benchmarks/platform_coordination_m_v0_1.json)。
  无人机查光伏板，无人车读表；同一资产的已核实异常才触发地面复核。覆盖只拍到图、
  串错证据、掉线换人、没有合适平台等情况。固定派工 7/8，反馈局未跑完；可重分配规则 8/8，
  三轮完成模拟任务：原机掉线 → 备用机只补未完成的屋顶任务 → 地面按核实证据复核。
- **独立棋盘 B-v0.2**：[3 局 × 4 轮](src/uavswarm_llm_lab/benchmarks/board_coordination_b_v0_2.json)。
  两个棋子分别作答，只在共享条件下向第二枚公开队友意向，只查已结算的对手历史。
  三种规则策略均 24/24 合法；独选、共享意向、再看对手历史分别得 30、54、69 分，
  同队重复 12/12、0/12、0/12 轮。最后一种在有 5 次前轮争抢的情况下 0 次重复原选；
  本队得分提高不等于分差或胜率提高。

### 本地 0.8B 实测（2026-11-20）

RTX 4050、D 盘既有 Qwen3.5-0.8B Q4、llama.cpp b10964、2048 上下文、seed 0、temperature 0。
题集与规则基线的内容哈希一致。第一轮 83 次请求，单变量对照 70 次，均收到回复，无执行链、
训练或模型下载；这些含同题复跑，不能当作 153 道新题。复跑的原派工和棋盘共享意向条件
与第一轮同分。两轮可用 RAM 最低点样 2751 MiB，GPU 最高点样 49 °C，临时模型进程均已关闭。

- **派工**：原模型方案 0/8 合法，三轮反馈局未完成。模型给足了字段，但对 8 个状态都返回
  同一组四个派工、`deferred: []`。例如只有 RGB 时仍派地面复核；原机掉线后仍将 B 区给原机，
  同时重排已有证据的 A 区。去掉每项任务的 `preferred` 字段（其余提示、知识和裁判不变），
  8 份候选仍逐题等价，结果 0/8，不能把失败只归因于默认人选。合格的规则基线是 8/8 并完成反馈局。
- **棋盘**：模型每项条件各 24 个真实选择，均是单步合法动作。分数与同队重复率另计。
  看对手历史比只看队友意向少重复上一轮被争抢的牌（2/8 对 6/10），但仍每轮队内撞牌。
  另给棋子 2 加一句明确的避重提醒、保持选项和裁判不变后，它 12/12 轮弃权，没有提高得分。

| 0.8B 条件 | 本队得分 | 队内重复 / 12 轮 | 有其他不撞牌选项却弃权 |
| --- | ---: | ---: | ---: |
| 独立选择 | 17 | 9 | 0 |
| 共享队友意向 | 13 | 12 | 0 |
| 再看对手历史 | 19 | 12 | 0 |
| 共享意向 + 明确避重提醒 | 13 | 0 | 12 |

裁判新增「有不同于队友的公开牌却弃权」和「实际得到分的不同牌张数」指标。前者不假定知道
对手本轮的选择；用原始选牌重新计分，没有再次推理或覆盖历史数据。最终 **64 项单元测试通过**。

- 逐题规则基线与模拟反馈：`artifacts/coordination-baselines-20261120T035046332Z/`。
- 真实原答及对照：`artifacts/coordination-qwen08-real-20261120T061228971562Z/` 和
  `artifacts/coordination-qwen08-ablation-20261120T061602190555Z/`。
  两个目录的 `responses.jsonl` 留存模型实际看到的消息、约束和原始回复，而非仅最终得分。
- 新指标复算：`artifacts/coordination-board-regrade-20261120T061820694326Z.json`。制品均由 Git 忽略。

在本模块目录复现两套无模型基线：

```powershell
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory artifacts/coordination-check -Force
python -B -m uavswarm_llm_lab.coordination_bench --suite mission --method rules --output artifacts/coordination-check/mission-rules.json
python -B -m uavswarm_llm_lab.coordination_bench --suite board --method history --output artifacts/coordination-check/board-history.json
```

输出文件不能事先存在。已有同机离线模型时，切换到 `model` 或 `model-history`，并显式提供
`--model-url`（回环地址，例如 `http://127.0.0.1:18116/v1`）与 `--model-id`。
下一步先由规则筛掉掉线、缺证据和已完成的任务，再用新的优先级冲突题检验模型是否能在
多个合法候选之间做取舍。本轮未测 4B；不把少撞牌、语义正确或模拟完成当作真实巡检通过。

2026-11-20：[主控台的模型实测回放](../../frontend/swarm-console/README.md#当前已接入的按钮)。
它只验证限定目录中的目标楼栋选择，不测完整任务规划。程序从
`simple_recon_v0_1 / simple_recon_v0_1-map-1` 的部分导出中选最近的正北坐标排，
再取东坐标为正的楼栋；本轮候选 1 高 32 米，候选 2 高 22 米。
模型只看到短语和编号描述，可返回候选编号、`unknown` 或 `clarify`。
程序独立计算 `20 + 差值` 并比对该范围的目录高度：唯一匹配时检查 ID，无匹配时检查
`unknown`，并列时检查 `clarify`。模型不一致时保留原始响应，输出待澄清且不绑定。
0.8B 模型这三次均答候选 1，只有 32 米题正确；这不是泛化准确率。

若已有同机离线推理服务，从本目录执行以下 PowerShell 命令重跑三条，并保存在新目录：

```powershell
$env:PYTHONPATH = 'src'
New-Item -ItemType Directory artifacts/scene-preview-try
python -B scripts/export_local_model_scene_preview.py ../../docs/fixtures/simple_recon_v0_1_scene_affordances.json artifacts/scene-preview-try --local-model-url http://127.0.0.1:18116/v1 --model-alias qwen3.5-0.8b-q4-lab
```

端口与别名须对应已启动的本地模型；脚本不自动启动模型、不覆盖原证据、不向 Runtime 提交。
每条输出包含可导入的 `*.preview.json` 和可追溯的 `*.raw.json`。

### 本机实时试推理接口（开发版）

这和已合入主控台的回放是两个入口。模型已经在本机运行后，从本目录启动算法服务：

```powershell
$env:PYTHONPATH = 'src'
python -B scripts/serve_semantic_preview.py
```

默认 Lab 端口为 `127.0.0.1:18118`，推理服务为 `127.0.0.1:18116/v1`，模型别名为
`qwen3.5-0.8b-q4-lab`。Lab 不调用 Runtime，不启动模型，不写审计或飞行状态。
浏览器只允许 5178 控制台的两个回环来源：`http://127.0.0.1:5178` 和 `http://localhost:5178`。

- `GET /lab/semantic-preview/health`：只检查 Lab 服务，`model_status: "not_checked"` 不表示模型可用。
- `POST /lab/semantic-preview`：JSON 只允许 `objective`。例如 `{"objective":"请登记已导出目录里，北侧首排东半幅比20米高2米的那栋楼。"}`。首版仅受理这一范围的楼栋题。
- HTTP 200 返回 `api_version: "0.1"`、`mode: "live"`、`elapsed_ms`、`preview`（沿用回放
  格式）及 `evidence_json`（与 `preview.source.evidence_sha256` 对应的原始 UTF-8 文本）。
  200 不一定是绑定成功；看 `preview.status`。外层和预览都明确声明 `execution_authorized: false`。
- 422（目标不受理）、429（已有推理进行）、502（模型回复被拒）、503（模型不可用）、504（模型超时）
  通过 `error.reason_code` 区分；均无可用预览，不用回放数据替代实时失败。未加载前端也可用
  本模块的回环 HTTP 测试验证协议（`python -B -m unittest discover -s tests -q`）。

2026-10-05 最新：[三款模型的逐例输入输出及测试方法](docs/MODEL_EXPERIMENT_WALKTHROUGH_20261005.md)，
[MiniCPM 采样/格式实验与背景地标修复](docs/MINICPM_SAMPLING_AND_ROLE_FIX_20261005.md)。
旧报告的分数均是旧代码实验记录；修复后的规则基线另列，不能回写成旧实验的成绩。

2026-10-05 后续：[MiniCPM5-1B 异厂实测与 18 条新题](docs/MINICPM5_1B_EXPERIMENT_20261005.md)。
面壁官方 Q4_K_M 已在 D 盘核验并运行；不是仅做模型调研。
新题暴露规则基线会把背景地标当成目的地：`accepted` 不能证明语义正确，
当前目标绑定路径仍须人工核对，不可据此自动提交执行。原始失败和旧基线保持不变。

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
`ground-model` 允许本地模型提出语义绑定候选；真实模型结果见文首实验记录。
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

4B 重新启动仍要求至少 5GiB 可用 RAM；显式 0.8B / MiniCPM5-1B 实验配置要求 3GiB。
这是实验准入预算，不是通用运行最低配置，也没有降低 4B 的门槛。
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
