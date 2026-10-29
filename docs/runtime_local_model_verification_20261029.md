# Linux 本地模型与 Runtime 无飞行验证（2026-10-29）

## 范围与判定口径

本轮在 Runtime 独立 worktree `runtime-action-lifecycle`、分支
`codex/runtime-platform-autonomy` 继续此前因内存不足未执行的模型验证。
Runtime 业务源码基线为 `442686f1c3ae1e20e8bc4c3f4360f7aad47cf51e`。
新增 opt-in 验证脚本和脚本单元测试，不改变执行 API、Policy、车辆配置、端口映射或完成判据。

**当前结论：采用算法 `735af74` 后，两次独立模型进程启动的本地 fake 全链路均通过，
完整任务共 12/12 个及时合法模型候选，0 次非预期回退；真实飞行/前端联合验收仍未完成。**
这不是通用任务规划、地面/屋顶感知或实车自主驾驶完成。

验证真实的 Linux CPU 模型和候选 HTTP 服务；遥测与动作执行明确为 `fake`。
没有启动 PX4/Gazebo、地面三机 HTTP 服务、控制台或三维，也没有连接无人车。
**模型候选通过、确定性回退完成、真实飞行完成是三种不同结论。**
脚本的 `verification_completed=true` 只表示实验已跑完；
`model_candidate_integration_passed` 才表示本脚本两种完整任务均取得三个及时合法候选并完成。
脚本最终版本在后一判据不成立时返回退出码 2，不以“实验跑完”冒充接入通过。

## 固定依赖与运行边界

- Windows 主机：`ZYQ-LAPTOP`，系统可用总内存 15.73 GiB。
- CPU：Intel Core i7-13620H，10 个物理核心、16 个逻辑处理器；实验只使用 4 个推理线程。
- 17:07 清理后 Windows available 8.17 GiB；每轮启动前独立复测，不与 WSL available 相加。
- WSL 发行版：`Ubuntu`，Ubuntu 22.04、x86_64、CPython 3.10.12。
- 独立环境：`/home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024`。
- 模型与引擎：原 2026-10-24 CPU 包，不下载新权重，不使用 CUDA。
  引擎 llama.cpp b10964/b29c606e2，Qwen3.5-0.8B Q4。
- GGUF SHA-256：`bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517`。
- 原离线包 SHA-256：`4c5c25e37146c39599746effc3e29334386a43970bdad83c24d73f96eb7168ef`。
- 原算法源码：`17017cd711c96fbabb424540ae8467565e3c9f70`；2026-10-24 原包只读保留。
- 模型/候选只监听 `127.0.0.1:18080/8872`。Runtime 实验服务使用临时 loopback TCP 端口。
- Runtime 始终保持 2000 ms 模型预算、原有 Policy、不可变授权、幂等与恢复规则。
- 最低 3 GiB 可用内存保护保留；WSL 同时检查 Linux available 和 60 秒内的 Windows 主机测量。
- 脚本只终止自己启动并持有句柄的子进程，不清理或抢占其他进程。

## 实验一：原包 ctx512

实际时间：2026-10-29 17:12:30–17:13:11（北京时间）。
启动前 Windows available 5.456 GiB、Linux available 6.979 GiB，保护通过。
模型及候选服务就绪约 16.912 秒；这不是一次决策的延迟。

简短的直接候选请求结果：

| 请求 | 端到端延迟 ms | 结果 |
| --- | ---: | --- |
| 首次请求 | 1968.082 | candidate / execute_authorized_step |
| 后续 TAKEOFF | 1492.202 | candidate / execute_authorized_step |
| 后续 TAKEOFF | 1543.115 | candidate / execute_authorized_step |
| HOLD | 1548.542 | candidate / execute_authorized_step |
| HOLD | 1520.749 | candidate / execute_authorized_step |
| LAND | 1523.599 | candidate / execute_authorized_step |

6/6 有效候选，均 `execution_authorized=false`。但这不是完整 Runtime 接入通过：
真实任务请求含 UUID、ground lease、授权等完整字段，模型日志报输入
530/531/523/543/546/535 tokens，超过 ctx512。

| 完整任务场景 | 任务结果 | 真实模型候选 | 确定性回退 |
| --- | --- | ---: | ---: |
| 链路健康 | succeeded，三个 fake 动作 | 0 | 3 |
| fake TAKEOFF 后地面 lease 过期 | succeeded，三个 fake 动作 | 0 | 3 |
| 模型关闭 | succeeded，三个 fake 动作 | 0 | 3 |

这里的 succeeded 是 fake 执行和预授权回退通过，不能写成模型控制或飞行通过。

## 实验二：原算法、ctx2048

只增大本地实验模型上下文，不改请求字段、模型权重、线程数或 Runtime 截止时间。
模型及候选服务就绪约 24.917 秒。首次简短请求 2003.867 ms，返回 MODEL_TIMEOUT；
后续五个简短请求 1487.416–1566.786 ms，有效候选 5/5。

完整 Runtime 请求不再溢出上下文，但 CPU 推理端到端延迟仍经常超过 2 秒：

| 完整任务场景 | 任务结果 | 真实模型候选 | 确定性回退 |
| --- | --- | ---: | ---: |
| 链路健康 | succeeded，三个 fake 动作 | 0 | 3（deadline exceeded） |
| fake TAKEOFF 后地面 lease 过期 | failed，包含恢复 LAND | 1 | 2（deadline exceeded） |
| 模型关闭 | succeeded，三个 fake 动作 | 0 | 3 |

断链场景最后的合法候选为 `abort_to_land`。Runtime 执行预授权恢复 LAND，
保留任务 failed；没有因恢复动作完成而把原任务改成 succeeded。
原候选服务遇到 Runtime 已超时断开时还打印了 BrokenPipeError；不能把这个日志等同模型进程崩溃。
因此 **ctx2048 只解决容量，不解决完整输入的稳定时延**。

## 实验三、四：算法精简模型视图，保留 ctx512 和 2 秒预算

算法负责人在自己的工作区实现并提交：
`735af7485a5d953bdea2e48c8d634e256d325af5`（Draft PR #96）。
Runtime 不复制或改写算法实现；通过脚本 `--candidate-source` 引用该版本，旧包保持只读。

算法仍严格校验完整 Runtime 请求，响应继续关联完整 node/task/execution/request/trace/snapshot，
保留 `evidence.input_sha256`。仅从模型输入中去掉重复关联 ID、重复选项参数等非决策内容，
保留全部本地观测、授权边界、新鲜度和链路信息。增加可追溯的内部视图：

- `model_view_version=uav02_candidate_view_v1`；
- `model_view_sha256`：真正送给模型的视图正文哈希；
- `model_view_at`：构造视图的 UTC 时刻。

视图不是新授权，模型响应始终 `execution_authorized=false`。
`offline_policy=continue_authorized` 的语义保留：地面断链本身不等于本地状态异常，
但模型仍可依据本地异常提出恢复 LAND，不强制它输出继续。

| 观测 | 第一次新模型进程（17:28） | 独立重启复跑（17:31） |
| --- | --- | --- |
| 模型/候选服务就绪 | 21.906 s | 20.403 s |
| 首次直接请求 | 1286.280 ms，candidate | 1287.082 ms，candidate |
| 后续五次直接请求 | 858.788–929.608 ms，5/5 candidate | 887.155–928.977 ms，5/5 candidate |
| 健康链路完整任务 | 3/3 candidate，0 回退，succeeded | 3/3 candidate，0 回退，succeeded |
| TAKEOFF 后断地面 lease | 3/3 candidate，0 回退，succeeded | 3/3 candidate，0 回退，succeeded |
| 完整任务六步候选耗时 | 1004.288–1063.107 ms | 1043.557–1087.854 ms |
| 模型关闭 | 三步均 MODEL_UNAVAILABLE；预授权 fake 回退完成 | 三步均 MODEL_UNAVAILABLE；预授权 fake 回退完成 |
| 任务重复请求 | 相同 execution_id，没有重复动作 | 相同 execution_id，没有重复动作 |
| `model_candidate_integration_passed` | true | true |
| 本轮子进程退出 | 全部退出，端口释放 | 全部退出，端口释放 |

合计：12/12 次直接模型候选、12/12 次完整任务步骤模型候选均在 2 秒内；
两个正常完整任务和两个断链完整任务通过，另两个模型不可用回退任务通过。
两轮完整任务的 12 个响应原始输入哈希均与 Runtime 的 model_request 事件一致。
模型日志中直接请求结束时 slot 的 `n_tokens` 为 280–284，完整请求结束时为 324–329；
这是**包含生成内容的 slot token 计数，不是独立测得的纯输入 token 数**。
两轮均无 ctx512 溢出或非预期截止超时。

该结果只证明当前固定软件、CPU/线程数和合成状态下的可行性。
后续请求共享模型/进程缓存；“独立重启”也不代表操作系统磁盘缓存冷启动。
本轮不是长时间压力/P99 或其他硬件的 2 秒实时性保证，不外推到 Jetson、Windows GPU 或真实飞行。

第一次准备独立复跑时，端口探测把前一轮 HTTP 的 Linux TIME_WAIT 误判为占用，
在模型启动前停止。最终脚本使用 Linux SO_REUSEADDR 区分 TIME_WAIT 与真正 listener，
并新增单测证明已有 listener 仍会被拒绝；未杀掉任何其他进程。失败启动记录未当作模型样本。

## 共同的安全/一致性证据

- stale 输入：`INPUT_INVALID / OBSERVATION_STALE_OR_FUTURE`，无候选、无执行授权。
- lost-link TAKEOFF：`INPUT_INVALID / OFFLINE_TAKEOFF_NOT_ALLOWED`，无候选、无执行授权。
- 未携带 bearer 的平台状态请求：HTTP 401。
- 重复 POST 同一个不可变任务：`idempotent_replay=true`、execution_id 不变、fake 动作没有重复执行。
- TAKEOFF 后停发 ground heartbeat 并等待 3.3 秒；后续 fresh fake HOLD/LAND 的 Policy
  记录 `ground_link=lost`，并仍逐步裁决。
- 关闭本轮模型后，Runtime 按已接受授权回退，仍保留每步 Policy 和动作结果。
- 原始报告包含请求、身份、trace、模型请求/候选/不可用事件、Policy 事件、任务与执行结果。
- 每轮结束只关闭本轮模型/候选进程，检查 18080/8872 不残留监听。
- 未绑定、连接或发送 14540/14541/14542 MAVLink 数据。

## 可复现脚本

`scripts/verify_local_model_runtime.py` 是显式运行的实验工具；不会被普通 pytest 自动加载模型。
它始终启用 fake 遥测/动作，不能拿来执行 SITL/实体动作。

从 Windows 核对自己 worktree 的 `git rev-parse HEAD`，测量内存并启动 WSL：

```powershell
$runtimeModelOs = Get-CimInstance Win32_OperatingSystem
$runtimeModelFree = ($runtimeModelOs.FreePhysicalMemory/1MB).ToString('F6',[cultureinfo]::InvariantCulture)
$runtimeModelAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
if ([double]$runtimeModelFree -lt 3) { throw 'Host memory guard failed' }
```

随后立即向 WSL 中的脚本传入 `--host-available-gib` 与 `--host-measured-at`，以及
Windows Git 核对的完整 `--runtime-commit`。Linux 示例（替换参数中的占位值）：

```text
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024/bin/python scripts/verify_local_model_runtime.py --runtime-commit <verified-full-sha> --host-available-gib <fresh-host-gib> --host-measured-at <fresh-unix-seconds> --context-size 512 --bundle <absolute-original-bundle-dir> --output <new-output-dir>
```

`--candidate-source <absolute-algorithm_lab>` 可使用另一个已核对版本的算法源码，
模型与引擎继续来自只读旧包。脚本记录算法 Python 源码逐文件哈希及脚本自身哈希；
报告中必须另注明实际算法 commit，不能把新算法结果归给原离线包。

Windows worktree 的 `.git` 文件指向 Windows 路径，WSL Git 无法直接解析，故不在 WSL 中伪造 Git 基线。
当前 WSL 禁用了 Windows 可执行文件互操作，故不在 WSL 中调用 powershell.exe 获取内存。
两个初次脚本启动失败均发生在模型启动前，保留为环境边界问题，不计入推理样本。

## 测试结果

- 平台原有定向回归：45 passed，0 failed。
- 平台 + 新验证脚本保护/fixture：57 passed，0 failed（16.40 s）。
- Runtime 工作区全量：968 passed，12 skipped，0 failed（165.74 s）。
- 补充 TIME_WAIT/listener 单测后，最终脚本定向：13 passed，0 failed（10.52 s）。
- 最终 Runtime 工作区全量：**969 passed，12 skipped，0 failed（162.24 s）**。
- 最终 compileall、git diff --check、git diff --cached --check 通过。
- 12 skipped：5 个需要三机真实 PX4、1 个显式真实巡检、6 个需要 Node/转换器。
- 没有为了消除 skip 安装 Node、开启飞控端口或放宽标记。

实际命令（独立 Linux venv，checkout 根目录）：

```text
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024/bin/python -m pytest -q -rs -p no:cacheprovider --basetemp /home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024/pytest-runtime-full-20261029
```

最终全量命令相同，`--basetemp` 改为同一环境下 `pytest-runtime-final-20261029`，
不覆盖首次回归证据。

## 证据保留

原始证据在 Linux 独立环境目录下，并复制到本线忽略目录
`.runtime/model-verification-20261029/`，不提交日志、模型、SQLite、token 或运行产物。

| 证据文件（目录内） | SHA-256 |
| --- | --- |
| model-verification-20261029-ctx512-r3/report.json | a4ef37cf5f79a983b7b524ec1fa0c509a6bcdead0b3fa179a8f14c1763ab936d |
| model-verification-20261029-ctx512-r3/model.log | 1895553444c28b01b09038cb8a997396ba0c1e37a6f583f6417f87c6d72fde81 |
| model-verification-20261029-ctx2048/report.json | 772ecb6f7ac4a9983a87f388c0786a33db4751fac6bc4b308ea3a12aa04485b3 |
| model-verification-20261029-ctx2048/model.log | 9e8980e35b3d581f93269ae1614452460ae6c000c0d0347917b7a9e5e7492d72 |
| model-verification-20261029-compact512/report.json | 3f7febcc7ab47954a6e5ef2b9a7b8a3611778af7825d24b5b810c45ed7dffb88 |
| model-verification-20261029-compact512-repeat2/report.json | f6f58b0893b35b96cf66fb2794955b6198c6423b2019ae853ee32c4017d51ed4 |

## 尚未验收的边界

前两轮结果不允许据此宣称完整模型接入或当前阶段真实飞行通过。
Runtime 与算法线协作处理完整输入冗余后的两轮本地结果已通过，见实验三、四；
不能将它归到原算法 `17017cd`，也不能声称原 2026-10-24 模型包已更新。
后续仍需固定集成版本、真实模型与 PX4/Gazebo、控制台、三维的联合验收。
本轮未验证物理无人车上的 Runtime；用户明确该项仍未试过。
ARM64 依赖、ROS 双向反馈/动作适配、停车与人工接管、跨台式机网络均仍是独立开发任务。
不得把 x86_64 实验包直接搬作 Jetson 可执行包，也不能把发零速当作停车证明。
