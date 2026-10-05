# 本地语义绑定模型评测：待真实运行

日期：2026-10-05。本文**不是模型成绩报告**。本轮恢复真实模型实验为下一优先级，
先完成一套可重放、与规则基线分开的有标注评测入口；4B 模型没有在本轮加载。

## 样本与评分

`src/uavswarm_llm_lab/benchmarks/grounding_cases_v0_1.json` 含 9 条合成中文任务：
精确标签 A/B、双区域顺序、同义说法、否定区域、未知 C 区、巡检意图与禁止降落。
样本答案只供离线评分，不发送给模型。所有坐标、载具和区域都明确标为
`synthetic_benchmark`，绝不可当作真实飞行验证点。

固定语料规范化 JSON 哈希：
`07b569340306dc331e859d83b3f7a493783024df7ef81808a48d909e9207c331`。
每例保留模型原文、输出哈希、意图与有序区域 ID、校验错误、接受状态和延迟。
`candidate_semantic_match_rate` 与 `acceptance_match_rate` 分开统计；
接受错误语义或负例时另计 `false_accept_count`。不自动修复、重试、替换模型答案。

这 9 例只是入口冒烟集，不是既定的 ≥20 条独立中文标注集，也不能用于声明泛化准确率。
特别是未提供排除区字段时，“不要去 B 区”被明确拒绝
`OBJECTIVE_EXCLUSION_UNREPRESENTABLE:route-b`；模型原文仍可用于研究评分。
同义目标即便模型猜对，也暂留人工审核候选，不生成可执行提案。

## 已运行的非模型对照

规则基线：9 例中可评分语义样本 8 例，匹配 5/8；接受/拒绝判定 9/9，错误接受 0。
未知 C 区不在供应方选择里，当前候选输出 schema 也不允许空绑定，因此它只计入
拒绝安全率，不计入候选语义准确率；报告显式列出分母，作为待演进的契约限制。
完整逐例结果仅保存在 D 盘被 Git 忽略的
`artifacts/tests/grounding-baseline-20261005-v2.json`。38/38 Python 单元测试通过，
其中脚本客户端只验证评分逻辑，**不是模型推理**。

已运行 `start_local_engine.ps1 -CheckOnly`：已批准的 4B GGUF、引擎与 CUDA
制品哈希校验通过，引擎报告 build 10964，并识别 RTX 4050 6 GiB。
内存读数在本轮从约 4.93 GiB 降至约 3.5 GiB，低于脚本已有的 5 GiB
启动门槛；没有绕过门槛或关闭用户进程。没有调用 Runtime、Policy 或飞控。

## 内存满足条件后的真实复跑

从本模块目录、PowerShell 7 运行。启动脚本只读本地 D 盘制品，
不自动下载，绑定 `127.0.0.1`，启动前要求 ≥5 GiB 可用 RAM。

```powershell
./scripts/start_local_engine.ps1
# 把上一命令返回的 D 盘 launch.json 路径填入下一行：
./scripts/run_local_smoke.ps1 -LaunchRecord '<D盘launch.json绝对路径>' `
  -Mode ground-eval `
  -ContextFile 'src/uavswarm_llm_lab/benchmarks/grounding_cases_v0_1.json'
```

九例套件最长运行 300 秒，期间持续监测内存、整卡显存和温度；
请求结束默认关闭模型服务。
输出及资源采样写入新的 `artifacts/runs/request-*`，不会进 Git。
接下来先取得这 9 条的真实 4B 结果和失败案例，再扩充到 ≥20 条人工标注样本；
随后才考虑按单独制品清单准备 2B/0.8B 资源—质量对照。
