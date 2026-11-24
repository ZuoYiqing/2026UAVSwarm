# 平台公共状态回传契约 v1.0

2026-10-30 兼容扩展：内部 view 新增可选 `runtime_telemetry`，用于 Simulation
integrated-health 的独立心跳/位置 RX 证据；旧四类 UI projections 不变，诊断对象
不进入公共 `platform_view` 元数据。新只读 route、fixture、run_id 和原子文件导出见
[Runtime telemetry health v1.0](runtime_telemetry_health_contract_v1.md)。缺少此扩展时
旧页面仍可读取，但不得将 UI telemetry/latest 冒充 integrated-health evidence。

日期：2026-10-30。主责：Runtime；消费者：主控制台、三维、Simulation integrated health、集成验收。
本补丁不改车辆 manifest、端口/sysid、Policy、动作完成判据、模型输入或 Gazebo 生命周期。

## 为什么必须补齐

平台进程独占 UAV-02 的长期 session/14541，地面进程以 `--exclude-node UAV-02` 只拥有 01/03。
原公共快照只看地面 registry，因而省略 UAV-02；三维将完整快照中的省略解释为删除。
地面原 `/api/preflight?node_id=UAV-02` 同样无法在本地 registry 解析目标。
修复不能在地面重开 14541，也不能让前端把 raw local 坐标伪装成公共坐标。

## 已实现的接口

| 接口 | 生产者/行为 | 执行权限 |
| --- | --- | --- |
| `GET /api/platform/view` | 平台 bearer 认证，只读返回本机公共 projections；也可经已有 ground facade 查询 | `execution_authorized=false`；不续 ground lease、不创建任务 |
| `GET /api/vehicle-snapshot` | 地面合并本地 01/03 与缓存的 02；保持三维现有 schema 和完整快照语义 | 仅缓存，不做上游 HTTP 或 MAVLink 请求 |
| `GET /api/snapshot` | 合并节点、fleet summary、活动动作、backend 状态；任务终态仍以平台持久记录为准 | 仅缓存 |
| `GET /api/telemetry/latest` | 合并三节点；`?node_id=UAV-02` 只返回 02 | 仅缓存 |
| `GET /api/vehicles` | 保留平台节点的注册身份及 stale 状态 | 仅缓存 |
| `GET /api/simulation/status` | 汇总全机连接数，并核对独立 Gazebo 证据中的全部启用模型，不能漏掉 02 | 不从 heartbeat 推断 world 健康 |
| `GET /api/preflight?node_id=UAV-02` | 经同一 ground-agent 代理向平台做既有 HOME/RTL 只读检查，返回前重查本地 01/03 隔离证据 | 始终 `flight_command_sent=false`、`execution_authorized=false` |

地面 HTTP 及平台启动命令不新增参数，不改变既有 loopback 绑定。
平台真实 SITL 仍须显式 `--execution-mode sitl --run-id <run-id>`。
默认 fake 服务的 view 中 `projections=null`，不会把 fake 观测发布成真实 PX4 公共位置。

内部 view 的实际结构（动态值省略，不是飞行授权）：

```json
{
  "contract_version": "1.0",
  "node_id": "UAV-02",
  "store_id": "<persistent-store-id>",
  "run_id": "<simulation-run-id>",
  "execution_mode": "sitl",
  "source_timestamp": "<UTC ISO8601>",
  "valid_for_ms": 3000,
  "execution_authorized": false,
  "projections": {
    "telemetry": {"version": "1.0", "nodes": []},
    "vehicles": {"version": "1.0", "vehicles": []},
    "runtime_snapshot": {"version": "1.0", "nodes": [], "active_actions": []},
    "vehicle_snapshot": {"version": "1.0", "full_state": true, "vehicles": []}
  }
}
```

上段只展示字段结构，真实 SITL view 的 `vehicles` 与 `vehicle_snapshot.vehicles`
各有且只有 UAV-02；未收到遥测时 `telemetry.nodes` 可以为空。
可实际运行断言的 fixture：`docs/fixtures/platform_view_v1.json`。
其中 `response_projection` 是真实生产者响应的子集断言，不是完整 schema；
`calibration_request` 的 1970 年时间是单元测试受控时钟，不是现场证据。

## 字段来源与一次转换

- 原始遥测：UAV-02 唯一 PX4 session；平台按既有 RuntimeStateStore 输出兼容节点/三维结构。
- 标定：Simulation 发布的 scene/map/origin/translation、连续性和有效期；Runtime 不凭空生成。
- `spatial.raw_vehicle_local_pose` 明确是每机 local 诊断信息。
- `spatial.scene_pose` 在**平台 Runtime** 依据有效标定转换一次；地面和前端不再叠加出生偏移。
- `public_position_usable` 只有标定、原点、位置新鲜度等判据都满足时才为 true。
- 平台额外复查 session 的独立位置样本时间。新 HEARTBEAT/电池消息不能把旧 local position 刷新为 LIVE。
- 采样前后位置时间/坐标不一致时，保留诊断 pose 但公共位置不可用；不把一个新样本的时间贴到另一个旧 pose 上。
- scene 不一致时，地面把公共位置标为不可用，不把它换个 frame 名称继续使用。
- 模型仍只消费原 `SitlActions.observe()` 和候选契约；新公共 view 中的标定/场景信息不送入模型。
- `run_id` 是运行关联字段，不独立证明进程身份；Simulation/集成仍须核对真实进程与 run。

## 新鲜度与断链降级

3000 ms 是**动态 view 传输缓存**的上限，不是给静态 ground_reference 设置新 TTL，
也不延长 health、标定、位置或任务授权的原有有效期。

平台 view 和 ground heartbeat 由地面两个独立线程处理；慢快照不能拖断 1 Hz heartbeat。
只读 view GET 不续租。客户端断开、刷新、view 读取失败均不等于平台任务已停止。

地面缓存使用来源时间戳加接收后的 monotonic elapsed：

- 重读相同旧 view 不会把来源年龄清零。
- 节点/位置年龄继续增加；标定年龄独立增加，提前过期就立即停止公共空间使用。
- 读取失败/超时/错误节点、transport、版本、时间戳或 fake 混入时，保留上次节点及 pose，
  但 `connected=false`、`telemetry.stale=true`、`spatial.public_position_usable=false`。
- ground 公共响应增加 `platform_view` 元数据，含 `fresh`、`observation_status`、`reason`、
  `source_timestamp`、`age_ms`、`store_id`、`run_id`。`fresh` 指传输 view，不替代逐节点样本或标定新鲜度。
- 活动动作保留最后确认状态并加 `observation_stale`，不因 HTTP 断开改成 failed/succeeded。
- 从未收到平台数据时，依据 manifest/scene 元数据保留注册身份和 `scenario_initial` 诊断 pose；
  明确 stale、公共位置不可用，不能把初始 pose 当真实遥测。
- 字段缺失或旧缓存 `armed=false` 不能证明已 disarm；真实验收必须同时有显式 false 和新鲜样本证据。

view 校验/诊断错误包括：`platform_view_invalid`、`platform_view_unavailable`、
`platform_view_node_mismatch`、`platform_view_node_missing`、`platform_view_transport_mismatch`、
`platform_view_freshness_invalid`、`platform_view_timestamp_invalid`、`platform_view_run_id_required`、
`fake_platform_view_cannot_publish_px4`。公共缓存不可用返回 unknown/stale 元数据，不删除节点。
预检上游失败返回 `status=not_ready`、`reason_codes=["platform_link_unavailable"]`，不会伪造 ready。

## 兼容性、归属与下一步

公共路径、`version=1.0`、NED 兼容字段和三维 schema 保留；增加内部 versioned view 及可忽略的元数据。
未配置 platform gateway 的普通三机进程沿用原来的本地快照和预检行为。
旧版本平台不提供 view 时，地面节点保留但未知；不得绕过缺口去开第二个接收者。
前端仍需按已确认平台归属禁止旧执行入口，不能因 snapshot 里重新出现 endpoint 就解除归属。

Runtime 主责实现、fixture、生产者测试和本契约；主控台/三维消费公共 API 并记录真实观测；
Simulation 主责真实标定/健康、进程与端口；Integration 主责更新固定组合和唯一动作发送窗口。
本轮只运行 fixture/loopback/回归，不启动模型、PX4/Gazebo 或实体无人车。
真正联合验收需要用户在集成负责人对话明确恢复任务和独占窗口，并满足主机内存保护。

## 本轮验证证据

在 Runtime 独立 worktree、WSL `Ubuntu`、既有 Python 3.10 venv 执行，未安装新依赖：

- 第一轮平台/view/三维 schema 定向：71 passed，0 failed。
- 加入独立位置样本、fake 不能变 live、跨 scene 等边界后：76 passed，0 failed（19.45 s）。
- 只读消费固定集成 `fbdc3b2` 的跨线测试、以本线源码覆盖 Runtime：10 passed（12.99 s）。
  这不是已更新固定集成提交，更不是飞行验收。
- 中间全量：991 passed，12 skipped，0 failed（162.36 s）。
- 补齐平台模型健康聚合后：993 passed，12 skipped，0 failed（170.12 s）。
- 加入前后采样一致性后：995 passed，12 skipped，0 failed（156.38 s）。
- 未知位置年龄保持 null、不被普通遥测年龄覆盖：995 passed，12 skipped，0 failed（143.99 s）。
- 最终交付版本同时核对单节点 telemetry wrapper 的 backend/endpoint/有效期元数据：
  **995 passed，12 skipped，0 failed（142.35 s）**。
- 本轮新增 view 专项共 26 个测试；最终源码跨线 fixture 另复跑 10 passed（13.15 s）。
- 12 skipped：5 个真实三机 PX4、1 个显式真实巡检、6 个 Node/转换器依赖用例。
- compileall 与 git diff/staged diff 检查通过；没有修改三维 schema 来使测试通过。

最终全量命令（checkout 根目录）：

```text
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024/bin/python -m pytest -q -rs -p no:cacheprovider --basetemp /home/zyq/.local/share/uav-runtime-envs/linux-x86_64-py310-20261024/pytest-runtime-view-handoff-20261030
```

跨线命令在同一目录，用 `PYTHONPATH=src:/mnt/d/2026UAVSwarm/.runtime/uav02-autonomy-integration`、
`-c pyproject.toml`，只读运行集成目录的 `tests/integration/test_uav02_onboard_autonomy.py`，
临时文件分别在上述环境的 `pytest-crossline-view-20261030`、`pytest-crossline-view-final-20261030`
与最终交付的 `pytest-crossline-view-handoff-20261030`。

这是生产者/缓存/契约的 fixture 与 loopback 证据。HTTP LIVE 联合观察、真实 ACK 后的高度/落地判据、
01/03 新鲜 disarmed、安全停止以及模型与三相机仿真的并发资源验证仍未完成。
不把 fixture 中显式的 PX4 标签、受控时钟或坐标当作现场真实数据。
