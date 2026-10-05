# 三款本地模型：实际输入、输出与测试方法

目前下载并在这台电脑上运行过三款文本模型：Qwen3.5-4B Q4、Qwen3.5-0.8B Q4、MiniCPM5-1B Q4。
它们并未在完全相同的题目和设置下做统一排名：4B 是较早的单次任务实验，
0.8B 和 1B 才在 9 条旧题与 18 条新题上进行对照。三者都没有做训练或板端运行。

## “场景绑定”究竟是什么

另有一段**确定性代码**读取 Runtime/仿真侧导出的建筑清单；它不是由上述模型“看图认楼”，
也没有从真实相机取画面。清单的 `scene_id=simple_recon_v0_1`，记录了 12 栋楼、一个楼群摘要及 `scene_ned` 参考坐标。
输入“飞到北边那片楼群的东侧”，输出摘录（以下字段来自同一响应）：

```json
{"bindings":[{"target_id":"city-block-4-3","target_kind":"building_cluster","relation":"east_side","reference_geometry":{"center_north_m":350.0,"center_east_m":-10.0}}],"reason_code":"ROUTE_PLANNING_REQUIRED","proposal":null,"execution_ready":false}
```

参考中心用于确认指的是哪片楼，并非飞机目标点；建筑可能占据那一位置。
输入“到最高的那栋楼旁边”，清单里两栋 52 米，输出 `AMBIGUOUS_HIGHEST_BUILDING`，
候选为 `link-block-4-3-2-1` 与 `link-block-4-3-3-2`，要求人指定 ID。
清单仍标记待提供方复核、物理覆盖不完整；结果会带上这些警告。
实现见 `src/uavswarm_llm_lab/scene_binding.py`，清单见主仓库
`docs/fixtures/simple_recon_v0_1_scene_affordances.json`。

## 模型收到什么

9 题集固定 `source=synthetic_benchmark`：一架虚构载具、两个区域 `route-a/route-b`、
标签 `A区/B区/东区` 和事先给定的虚构航点；每条题只替换 objective。
18 题集改用 `r-north/r-south/r-east`、北仓/南库/东塔及不同顺序、否定、别名和背景说明。
输入文件分别是 `src/uavswarm_llm_lab/benchmarks/grounding_cases_v0_1.json` 和
`src/uavswarm_llm_lab/benchmarks/grounding_challenge_v0_1.json`。

目标绑定请求的 user 消息只含客观任务文本和候选 ID/标签，格式示意：

```json
{"objective":"飞行验证：起飞、前往A区、降落。","choices":[{"region_id":"route-a","labels":["A区","route-a","东区"]},{"region_id":"route-b","labels":["B区","route-b"]}]}
```

本地客户端按固定 system 提示词请求严格 JSON；模型必须回答 `intent_type`、有序 `bindings[]`
及一句解释。模型不创建航点坐标，也不负责按载具分配任务；后一步仍由规则基线做。
同一次请求结束后，程序校验 JSON、区域 ID、原文引用、重复/顺序、输入时效、任务动作及候选结果，
并保存原文、哈希、耗时、接受/拒绝理由。

旧 9 题中真实原文的两种结果：

```text
Qwen 0.8B, “起飞、前往A区、降落”
返回 bindings=[route-a/A区, route-b/B区]
结果：拒绝；B区根本没有在 objective 中，MATCHED_TEXT_NOT_IN_OBJECTIVE:route-b。

Qwen 0.8B, “起飞、前往B区，再前往A区，降落”
返回 bindings=[route-b/B区, route-a/A区]
结果：候选接受；但这只表明任务语义与本模块校验一致，不是飞行许可。

MiniCPM 1B, “起飞、前往A区、降落”
返回 bindings=[route-a/A区, route-b/B区, route-a/起飞, route-b/前往, route-a/降落]
结果：拒绝；出现重复区域、虚构的 B区及顺序问题。
```

新 18 题中，“北仓只是背景地标；起飞后只前往南库，最后降落”，
Qwen 0.8B 返回 `r-south/南库`；旧版精确标签规则却把 `r-north` 一并选中。
新版本已对明确的背景/参照表达处理并补了拒绝测试；之前的实测分数保留为修复前成绩。

4B 的早期单次目标绑定使用另一个输入：“对 verified-flight-route-001 做飞行验证：起飞、前往已验证航点、降落。”
模型返回 `flight_validation` 和 `verified-flight-route-001`，候选通过。
4B 在结构化三机输入上也曾正确分给 UAV-01/02/03，但其解释宣称路径和能源满足约束，
严格安全回放拒绝该说法。它没有参加上述 9/18 题多轮测试，因此不能用这次单题通过去比较胜率。

## 哪些是真模型请求，哪些只是测试

`start_local_engine.ps1` 启动 D 盘量化权重和便携推理引擎；服务仅监听 `127.0.0.1:18080`。
`run_local_smoke.ps1 -Mode ground-eval` 调用本模块客户端逐题发请求、采资源点样，完成后停止实验服务。
旧集三轮原提示词、三轮改进提示词就是 `9×6=54` 次**真实 0.8B 模型请求**。
18 题另做三轮、共 54 次；Mini 旧集和新集目标绑定共 108 次，另有两次三机提案请求。
这些都是推理，不是 Python 单元测试。

`python -m unittest discover -s tests` 则用假响应检验数据契约、评分和拒绝逻辑；
`benchmark` 的 40 个案例也是离线框架验证。它们不加载权重，不能证明模型答题能力。
本轮没有启动 Runtime、Policy、PX4/Gazebo、前端或相机，也没有提交给 `/api/plans/execute`。
模型和评分器的完整原文在 D 盘 `artifacts/runs/request-*/proposal.json`，Git 忽略该目录；
跟踪的验证 JSON 保存了每份原始文件的 SHA256，便于本机复核。

资源门槛由启动脚本检查，单轮脚本监控主机内存、GPU 温度和 300 秒上限。
推理机够跑这些小模型；训练、真实图像观察、路径可飞性及 Jetson/昇腾板端性能都另行验证。
