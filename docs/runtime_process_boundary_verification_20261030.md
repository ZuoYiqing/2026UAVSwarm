# 双 Runtime 独立进程无飞行验证（2026-10-30）

## 结论与范围

Windows 实际启动地面与 UAV-02 平台两个正式 Runtime CLI 进程，验证地面
退出不结束平台，重新启动地面可恢复链路，平台 boot/store/event 身份不变。
**不是一个验证进程内的 PlatformService/HTTP 线程模拟。**

平台固定 `--execution-mode fake`，地面强制
`UAV_RUNTIME_TELEMETRY_ENABLED=false`。本次进程实验没有启动 WSL、模型、
PX4/Gazebo，没有连接/绑定 MAVLink 端口，没有 POST 任务或任何飞行动作。
结果只证明进程与 HTTP 生命周期边界，不是 SITL 或前端联合验收。
后续另一次 Ubuntu 全量 pytest 使用 WSL，不能与此进程实验的范围混淆。

业务源码基线 `9869e6a744aa1a1c18a25b43a36a600e829342d9`。本轮仅新增
验证器、保护性测试、记录和契约导航，不改执行/Policy/配置/接口。
run_id 是明确的 `fake-process-smoke-*` 标签，不冒充受管仿真 run。

## 实际证据

北京时间 2026-10-30 23:55:22–23:55:27，Windows / CPython 3.11.7。
独立 worktree `runtime-action-lifecycle`，分支 `codex/runtime-platform-autonomy`。
启动要求 60 秒内宿主机 available ≥3 GiB，本次准入通过；不代表足够并发运行
模型与三相机仿真。

| 角色 | PID | 结果 |
| --- | ---: | --- |
| 平台 Runtime | 8468 | fake，8766，全程保持同一进程 |
| 首次地面 Runtime | 45876 | 8765，检查后通过自己的 Popen 句柄终止 |
| 重启地面 Runtime | 4156 | 8765，恢复链路后清理 |

initial/healthy/lost/restored 四阶段均保持：

- boot_id `d3e68e33-2987-4de2-b444-f1951c6fbb99`；
- store_id `41609b4e-d6b8-451e-87f1-ae1e354fcc00`；
- event_seq=0，active_task=null。

ground_link 为 `lost → healthy → lost → healthy`，通过地面退出使三秒租约
自然过期。本轮直接 ground→platform HTTP，没有故障代理、带宽/时延或受管
仿真身份验证，不能扩写为这些功能已实测。

八项实际检查全部通过：独立 CLI PID；无 bearer 返回401；地面 heartbeat
到达；fake 不成为 PX4 LIVE；地面停止后平台存活；lease lost；地面重启后
link healthy；平台 boot/store/event 不变且没有任务执行事件。

同时读取公共快照/telemetry/simulation/runtime-telemetry：三节点保留为
offline/stale、公共坐标不可用、遥测不 fresh、仿真不 ready。这里的离线节点
**不能作为 UAV-01/03 真实新鲜 disarmed 证据**。

所有本轮进程均已清理，8765/8766 无监听；额外只读核查 UDP14540/41/42
无绑定。没有杀其他进程或清理别人的文件。

## 原始产物与复现

Ignored 原始目录：
`D:/2026UAVSwarm-worktrees/runtime-action-lifecycle/.runtime/platform-process-smoke-20261030-155521-8e69ae/`

- report.json SHA256：`c0de7e6a92d2ee2591e38594af0efa375bd3f05fd739aac9fc3c5f03d8246e12`。
- 本次验证器 SHA256：`66f53eb2ffeb7c648013d9003edf4886498dbdc852336077bb3dc6c46c9fa0e9`。

目录还含日志、SQLite、本机随机 token；不提交、不上传或整体离线打包。
先协调单一操作者，确认8765/8766空闲并实测内存，设置
`PYTHONPATH=<Runtime worktree>/src`，再运行：

```text
python -B scripts/verify_runtime_process_boundary.py --runtime-commit <verified-source-sha> --host-available-gib <fresh-host-gib> --host-measured-at <fresh-unix-seconds> --output <new-ignored-owned-directory>
```

source-sha 是操作员记录，不是脚本对脏工作区/所有依赖的完整性证明。
输出目录必须不存在；端口占用则拒绝，不抢端口或杀已有进程。验证器没有
SITL 选项，硬编码 fake/关闭遥测，只发送 GET；既有地面进程自行发送链路
heartbeat，不发送飞行动作。清理只用本轮 Popen 句柄；强制退出兜底只适用于
这些明确 fake/无 MAVLink 的子进程，**不得用于正在飞行的 Runtime**。

## 测试和真实缺口

- 新验证器保护单测：12 passed，0 failed（0.30 s）。
- 平台任务/视图/独立遥测/验证器专项：115 passed，0 failed（5.88 s）。
- 两个新增 Python 文件 AST 语法检查通过。
- Ubuntu 全量首次复跑：1038 passed、12 skipped、1 failed（219.80 s）；失败为
  `test_three_uav_health.py::test_integrated_health_uses_runtime_telemetry_without_binding_mavlink`，
  期望 ready 实际 not_ready。原样单独复跑1 passed（9.92 s）。疑似真实时间
  fixture 在慢 I/O 下超过 freshness 窗口，已交 Simulation 核查，尚不能把疑因
  当作确定根因。未修改该负责人文件、未放宽 TTL、未隐瞒失败。
- Windows 原样全量交叉复跑：**1044 passed、7 skipped、0 failed（86.57 s）**。
  命令：`python -B -m pytest -q -rs -p no:cacheprovider --basetemp .tmp_runtime_process_full_win_20261031`。
  跳过为5个真实多PX4、1个真实巡检 opt-in、1个 Linux TCP 专用验证器测试。
  不能用此结果抹去上述 Ubuntu 失败；两个平台记录并列保留。
- 受控机制实验：原正向 fixture 注入 model_probe sleep 1.7 s，实际输出
  not_ready、三节点 reason=telemetry_stale。证明机制存在，不是原失败现场定案。
- Simulation 后续 `b2b7bfc` 仅修三个正向 fixture 使用采样后的 provider；
  未修改生产 health/TTL，待集成吸收后复跑。Runtime 本分支没有夹带该文件。

Simulation 另交付 b7d792f 的受管 SITL 启停、89a14d7 的可选 candidate-url；
属于其他工作线，离线 mock 结果不能当作本轮实际 SITL 证据。正式下一关仍是
统一版本、资源准入、受管 PX4/Gazebo、唯一 RX、健康/标定/HOME、模型候选和
两个前端同窗观测，再进行起降/故障链路/安全停止。相关 PR 保持 Draft。
