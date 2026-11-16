# Runtime demo r2 合并报告 · 2026-11-14

R6/R7 本地验证。第一父提交：`421aa2753f373bc6f5696464923e15f7eb06d6c0`
（`origin/integration/demo-20261113`）；第二父提交：
`8d94a802d7b275066520a0a2c3276c18973887f8`（#97）。
原 `demo-20261113` tag 解引用后也是第一父提交，其树为
`a5ca15b60879c1a83245ff893f25c1c530ac150f`。
仅在 `integration/demo-20261113-r2` 独立 worktree 合入 #97，
没有 rebase、改 main、移动旧标签或并入其他线的第二阶段提交。

## 九处冲突

| # | 位置 | 保留及依据 | 取舍 |
| --- | --- | --- | --- |
| 1 | routes.py imports | 两边都留：演习和任务进度仍需原处理器，平台预检还要校验其他节点隔离。 | 合并重复的 preflight import。 |
| 2 | routes.py vehicle_snapshot | 先融合平台、再覆盖演习值。确认 `merge_projection` 深拷贝本地和远端车辆行，不能写回缓存。 | 远端失鲜或无有效 LIVE 分数时归零；保留演习覆盖和实测分之别。 |
| 3 | routes.py dispatch | 两边都留：进度、演习、平台 relay 各用独立命名空间。 | 保留平台不可用/未配置错误，不把演习转发到平台。 |
| 4 | server.py POST | 两边都留：演习仍要求 127.0.0.1，平台与证据仍要求原 Origin；共用 JSON 检查。 | 校验路径与 dispatcher 一样去尾斜杠，每个拒绝立即返回。 |
| 5 | server.py 请求长度与 SSE | 两边都留：演习独立限制 1–4096 字节；平台 SSE 仍走专用流处理。 | 独立 early return，不把 SSE 当 JSON，也不放宽演习体积限制。 |
| 6 | server.py JSON 写入 | 两边行为相同，保留 #97 注释及状态行、头、体的断连保护。 | 不把业务异常视为写端断连。 |
| 7 | server.py startup | 两边都留：按 #97 过滤注册表并先取得租约，再启动 gateway 和演习。 | 模块旧别名可能指向未过滤注册表，只使用 `routes.VEHICLE_REGISTRY` 的选中对象，绝不启动两份。 |
| 8 | server.py cleanup | 通过 ExitStack 反向释放 demo、gateway、注册表、全部已取得租约、HTTP。 | 即使 gateway 启动或 demo 关闭报错也继续释放；TransportLease 是 TCP 保留，不是另一条 MAVLink UDP receiver。 |
| 9 | mavlink_backend_session.py RX | 先保留 `matched_source`，同时采集 #97 的 `_health_sample_sources`；两种观测都依赖真实输入。 | 不更改 #97 解码包装器隔离和身份门，也不让演习值喂给健康生产者。 |

组合适配：双角色模式中 UAV-02 仍归平台所有，演习目标与实测评分只读缓存视图，
不会在地面侧创建 UAV-02 接收器。过滤注册表时保留现有场景元数据供面积接口查询。
本次并未把现有地面任务执行器扩展为跨角色、跨节点调度器；不能把 #97 的平台任务
等同于任意 GOTO 计划，也不能把演习重分配当成真实动作。

## R7

原 `mode: "DEMO"`、`execution_authorized:false`、`flight_command_sent:false`
保留；同一演习事件写入点增加 `simulated:true`。策略查询
`GET /api/policy/decisions?n=5` 与 `/api/actions/recent` 保留该字段，
`/api/events` 的原始 payload 和 `/api/replay` 包含注入及撤销事件。
旧/真实事件的投影可以为 `null`，不可推断为演习。现有主控台根据兼容的
`mode` 显示 DEMO，详情可见原始布尔标记；无需修改前端或开启真实动作。

## 验证

- 标记检查 `rg -n '^(<<<<<<<|=======$|>>>>>>>)' src tests` 无匹配；
  `python -m compileall -q src/uav_runtime` 和 staged/unstaged `git diff --check` 通过。
- Windows：设置 `PYTHONPATH=src`，运行
  `python -B -m pytest -q -rs -p no:cacheprovider --basetemp .tmp_runtime_r2_verified_20261114`
  → **1087 passed, 8 skipped, 0 failed**（96.78 s）。
  六项真实 SITL opt-in、一项 Linux 传输语义、一项 pymavlink 实际对象跳过。
- Ubuntu / 本地离线 venv：同参数，临时目录
  `/tmp/uavswarm-runtime-r2-full-20261114`
  → **1083 passed, 12 skipped, 0 failed**（135.43 s）。
  六项真实 SITL opt-in、六项 Node/转换器环境跳过。
- Ubuntu #97 与演习组合专项 → **166 passed, 0 skipped, 0 failed**（20.78 s）。
  已覆盖 Windows 跳过的 Linux 传输、pymavlink 实际对象。
  新增九个组合用例，未修改既有测试断言。新增远端覆盖用例初次暴露无评分接口时
  的异常，改为缺证据计零后通过；未用放宽测试处理。
- 控制台 `npm run check`、`npm test` → **114 passed, 0 failed, 0 skipped**。
  用 Runtime 测试实际落盘的 R7 审计事件喂入现有前端 JS VM，确认新到事件
  横幅有 DEMO、规则名，审计详情有 DEMO 和 `simulated`。
  首屏历史回填依原设计不弹横幅；验证不是浏览器联合验收。

## 未验收及保留项

不启动 PX4/Gazebo、不发送飞控指令、不启动模型、不操作 weier，未完成 11 条现场
验收。Runtime 支持此前验证的同机 Linux CPU 推理，不以 GPU 或非回环跨机调用
为此次验收前提。#101 和 S7 未并入此合并，不宣称第二阶段全部收敛。
旧工作区只读发现 78 个未跟踪匹配目录，与材料的 69 不同；
不执行 `git clean`，不移动或删除 worktree、历史分支。
