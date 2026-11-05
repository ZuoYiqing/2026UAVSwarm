# UAV-02 平台侧自治：2026-10-29 无飞行集成补充

本补充接续 `docs/uav02_onboard_autonomy_integration_report_20261023.md`，只记录新增的固定代码、离线制品与验证。它不覆盖此前证据，也不代表 PX4/Gazebo 或真实飞行验收。

## 新固定版本

组合分支 `codex/uav02-autonomy-integration` 已无冲突纳入当前 `origin/main=ea0d5fa`、Runtime `876bb92`（包含离线依赖文档 `442686f`，Draft PR #97）及算法 `735af74`（包含离线包文档 `527ef06`，Draft PR #96）。仿真 `db1c8e6`（#95）与主控台 `fc98648`（#94）未新增执行代码。`main` 的新提交属于运维/UGV 文档；本线未在 `main` 工作区写入或合并 PR。

Runtime 新提交添加 opt-in 的本地模型验证脚本与测试；执行 API、Policy、车辆配置、端口和动作完成判据未改。算法新提交在完整请求校验和原始输入哈希之后，构造带版本/哈希的精简模型视图；模型仍只选两个已授权 option ID，回复始终 `execution_authorized=false`。

## 本线复核

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| 跨线测试 + Runtime 本地模型验证器单测 | 22 passed，1 skipped | 本组合工作区；fake/loopback，不启动模型或飞控 |
| 算法候选适配器离线单测 | 16 passed | 包含精简视图校验与边界测试 |
| 全仓 `python -m pytest -q` | 1001 passed，7 skipped，92.07 s | 当前组合工作区；跳过项不算通过 |
| 算法 Ubuntu 22.04 CPU 归档 SHA256 | `4c5c25e37146c39599746effc3e29334386a43970bdad83c24d73f96eb7168ef` | 本机重新哈希，与算法交付记录一致 |
| Runtime Ubuntu 22.04/Python 3.10 归档 SHA256 | `412f5521d4936d3beabbb3af6cbae84efd1c25c9030d51a0a837dbce4c9ea853` | 本机重新哈希，与 Runtime 交付记录一致 |

Runtime 负责人另在 Ubuntu 22.04 WSL、两次独立 Linux CPU 模型进程中完成了真实模型服务 + fake 遥测/fake 动作验证：完整任务 12/12 个及时合法候选，记录的模型候选时延为 1004.288–1087.854 ms，0 次非预期回退；包括健康链路与 fake TAKEOFF 后地面 lease 丢失两种任务。原始完整请求在 ctx512 溢出、ctx2048 时仍超时，均在 `docs/runtime_local_model_verification_20261029.md` 保留失败证据、日志哈希与复现命令。本线没有再次启动模型服务；上述真实模型结果是 Runtime 负责人的已提交实验记录，不是本线现场复测，更不是飞行证据。

## 离线归档与算法源码版本不得混同

SHA256 为 `4c5c25e3…7168ef` 的 2026-10-24 CPU 归档，其 `manifest.json` 固定的是算法源码 `17017cd`，包内没有 `model_view.py`；校验这个 SHA 只能证明**旧归档未变**，不能证明它已包含 `735af74` 的精简视图。上述 12/12 成功实验复用了旧归档的 Linux CPU 引擎和 GGUF，但验证脚本以 `--candidate-source <absolute-algorithm_lab>` 单独加载了 `735af74` 的算法源码。

因此，下一次离线交付必须同时携带并核对新版算法源码及其实际加载路径，或另制带新版本、manifest 和 SHA256 的归档；不得覆盖原包，也不得把“旧归档单独运行”称为已经复现 12/12。若实际只加载旧包内 `17017cd`，不能忽略本机已记录的 ctx512 容量溢出与 ctx2048 超时，须重新实测后再下结论。组合分支包含新版源码，但 Git 提交与被忽略的模型归档是两份独立交付物。

## 尚未通过的门槛

模型同侧 fake 验证已不再是阻塞项，但**飞行与前端联合验收仍未完成**：未在同一受控窗口启动 PX4/Gazebo、地面 Runtime、平台代理、主控台和三维视图；未取得真实 UAV-02 ACK 后新鲜遥测、LAND/落地/上锁、唯一 `14541` owner、故障切链期间机载链路持续、01/03 始终 disarmed、同 `run_id` 的安全停止及进程清理证据。算法候选成功、fake 任务成功和真实飞行成功必须分开记载。下一阶段须先协调独占窗口与安全检查，不能自动发飞行指令或把 Draft PR 合入 `main`。
