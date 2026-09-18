# Algorithm Delivery Report — Step 1–2

## 1. Problem

建立本地 LLM Mission Proposal 实验闭环，为后续真实模型比较提供相同输入和判据。

## 2. Inputs

mission_context.schema.json 定义版本0.1。输入任务文本、权威结构化任务/航点清单、
scene/map/snapshot 标识、快照时效、载具资格、能力和 Policy DENY 摘要。
fixture 明确标记 synthetic_benchmark；未来规范化快照需由集成负责人确认。

## 3. Outputs

mission_proposal.schema.json 定义 proposed/degraded/rejected，完整分配或未分配任务、
原因码和解释。结果 envelope 分开保留 candidate 与 accepted_proposal。
accepted 不是执行授权；execution_authorized 固定false。

## 4. Algorithm / Model

已实现确定性 greedy reference baseline、严格 JSON 与语义校验、可选 loopback
推理 API 客户端。尚未运行或选择最终 LLM。基线不解析自然语言。

## 5. Alternatives Compared

本阶段没有真实模型质量比较。规则基线仅用于验证实验管线和作为以后对照。
prompt/schema约束优先；微调、LoRA、VLM和RL均未启动。

## 6. Benchmark

40 个 scaffold 案例；只有22 个是未来模型任务样本，其余用于验证输入和校验器。
本轮实测：19项单元测试通过（1.078秒）、40/40 scaffold通过、5个演示符合预期；pip check通过。
真实模型的语义准确率、自然语言理解率、延迟、吞吐和显存均待测。
实际本轮运行结果见 verification.json 和 scaffold_validation.json；
不得将 scaffold 通过率表述成 LLM 成功率。

## 7. Failure Cases

非法/重复JSON字段、非有限数、未知节点/任务/航点、任务遗漏、动作顺序错误、
离线/stale/电量未知或不足/忙碌节点、缺失能力、坐标不可用、Policy DENY、
快照超时和不允许的降级都会触发明确失败。
合法拒绝仍需检查是否过度拒绝；benchmark单独核对预期状态。
任意自然语言语义矛盾、完整三维几何及飞行可执行性不属于已验证能力。

## 8. Safety / Boundary

无 Runtime、Policy、仿真或飞控代码修改；不生成 endpoint、ARM 或 motor 操作。
LLM只返回文本。客户端拒绝 tool_calls、截断输出、重定向和非loopback地址。
Runtime 的最终授权与真实执行保持独立。

## 9. Runtime Integration Requirement

| 数据/保证 | 拥有者 | 算法需要什么 |
| --- | --- | --- |
| Mission Context | Integration Owner | 任务文本与结构化约束的优先级；冲突/澄清语义 |
| Capability Summary | Runtime | 按节点区分 proposal-supported 与 executable，不能只看元数据存在 |
| Fleet Snapshot | Runtime | node_id、连通性、电量未知语义、任务占用、每字段时效 |
| Spatial Snapshot | Simulation校准，Runtime发布 | scene_ned、scene/map版本、标定与位置有效期；不得复用旧origin |
| Policy feedback | Policy经Runtime提供 | 节点/动作/任务作用域、拒绝原因及有效期；算法不重新裁决 |
| Task/waypoint catalog | 任务/路径规划负责人 | 权威ID、坐标基准、几何约束验证证据 |
| Proposal admission | Integration Owner | schema映射、快照过期后的重新验证、人工确认和失效返回 |

快照更新频率和TTL由 Runtime 冻结，不能沿用合成数据的120秒窗口。
模型可能慢于遥测TTL：接入时需以新快照重新校验，或重新规划；不得延长TTL掩盖陈旧状态。
本阶段不自行实现主线Gateway、Plan IR或HTTP route。

## 10. Artifact

独立工作区 algorithm-lab-local-llm-poc 内 algorithm_lab/mission_llm_poc。
源码、两个schema、系统提示词、40案例、5演示输入、测试与本报告。
模型 artifact 尚无；没有权重提交。没有 git add/commit/push。

## 11. Deployment

使用独立 .venv，安装 requirements.lock 后安装本包。README给出复现命令。
当前硬件为6GB显存/约16GB RAM；本轮没有启动推理服务。
模型阶段需记录权重revision/哈希、推理框架版本、量化配置、上下文、seed和GPU占用。
当前 content hash 采用 Python规范化JSON，不声称是跨语言RFC8785哈希。

## 12. Recommendation

EXPERIMENTAL：可进入下一步本机模型选型和下载方案审核；
不能依据本轮框架测试将其接入真实无人机执行。先完成真实模型实验，再交 Integration Owner 评审。
