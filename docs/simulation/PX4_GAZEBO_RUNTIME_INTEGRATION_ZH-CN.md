# PX4/Gazebo Runtime 集成补充手册

本线基于 `b4e2f6e`，在 `codex/px4-gazebo-runtime-integration` 开发。
Windows main、独立 worktree 和 WSL `/home/zyq/2026UAVSwarm` 不会自动同步。
执行前记录实际路径、HEAD、未提交变更、PX4 HEAD、Gazebo 版本及当前占用者。
本轮 WSL 执行目录为 `/mnt/d/2026UAVSwarm-worktrees/px4-gazebo-runtime-integration`。
不修改 Runtime、前端或共享 `config/vehicles.sitl.json`；漂移按 `shared_config_mismatch` 交 Runtime 协调。

## 独占与安全停止

三机固定 sysid 1/2/3、compid 1、endpoint 14540/14541/14542、instance 0/1/2、model x500_0/1/2。
运行 standalone 前停止 Runtime，检查进程和 UDP 占用。脚本前后预检查 endpoint，冲突返回
`runtime_session_active:endpoint_in_use`，不能使用端口复用抢占。检查并不替代工作线间独占约定。
不得宽泛杀进程；停止使用 harness，先校验 PID、PGID、starttime、executable、cmdline、cwd 和 run_id，
SIGTERM 超时后再次校验才能 SIGKILL。内核确认的 zombie 视为已退出；活进程空 cmdline 仍拒绝发送信号。
停止报告必须确认 world、进程和端口已释放；再次 stop 应安全且无新增信号。

```bash
cd /mnt/d/2026UAVSwarm-worktrees/px4-gazebo-runtime-integration
python3 simulation/px4_gazebo/harness.py validate-config
python3 simulation/px4_gazebo/harness.py start --headless
python3 simulation/px4_gazebo/scripts/health_three_uav.py --mode standalone --pretty
python3 simulation/px4_gazebo/scripts/validate_three_uav.py
python3 simulation/px4_gazebo/scripts/patrol_three_uav.py --pretty
python3 simulation/px4_gazebo/harness.py stop
python3 simulation/px4_gazebo/harness.py stop
```

不要在飞行脚本退出前直接停止物理引擎。失败报告中的 recovery LAND、landed/disarmed 也必须检查。
真实巡检通过必须同时满足航点、ACK、落地解锁、采样覆盖、局部与公共坐标标定、Gazebo 实测机间距离。
`requires_px4_multi` 是真实集成 marker；默认 skip，不把 skip 计为飞行通过。

## 三种坐标与标定

Gazebo ENU `(east,north,up)` 转公共 scene NED `(north,east,down)` 为 `(y,x,-z)`。
PX4 LOCAL_POSITION_NED 是地固方向的局部坐标，不是机体系。载具 spawn yaw 不能旋转 NED。
只支持 `scene = local + measured_translation`，拒绝非零显式 frame rotation。
定义参考 [PX4 local position](https://docs.px4.io/main/en/msg_docs/VehicleLocalPositionV0)
和 [MAVLink LOCAL_POSITION_NED](https://mavlink.io/en/messages/common#LOCAL_POSITION_NED)。

静态采样测每机原点偏差；动态航线分别检验北、东及上下运动。至少 10 对样本且覆盖 1 秒，
按仿真时间匹配，最大配对差 50 ms，平移残差上限 0.5 m。
静止样本的 `physical_axes_exercised=false`，不能以它证明运动方向。动态检查另比较初始标定误差，
上限 0.75 m；失败保留配对样本，不靠调宽阈值变为 PASS。

标定绑定 run_id、PX4 完整进程身份、ref_timestamp/ref_lat/ref_lon/ref_alt、xy/z reset counter、Gazebo model ID。
EKF 重置、PX4 重启、模型重新生成都会使旧标定失效。时间倒退也拒绝。标定版本为
`ned-translation-1`，报告同时保存 scene_position、vehicle_local_position、valid/status、calibration_version。
相对起飞高度以起飞前 local z 为基准；scene z_down 和公共高程以 scene 原点为基准。
AGL 需要独立地面/测距证据，未采集时不能把 local 高度当作 AGL。

集成只读采样不创建 MAVLink receiver，使用受管理 PX4 的 uORB listener 与 Gazebo：

```bash
python3 simulation/px4_gazebo/scripts/sample_calibration.py --duration 6
```

输出 `.runtime/px4_gazebo/calibration/latest.json`。`--publish-runtime http://127.0.0.1:8765/api`
仅向既有 `/coordinates/calibration` 发布证据，不发送飞行命令。
未经本轮动态物理验收的标定不能宣称生产验证完成。保存的历史文件不能更新时间戳后重放。

## Integrated health 与 Runtime 交接

Runtime 独占三个 session 后，禁止 standalone health/巡检。运行：

```bash
python3 simulation/px4_gazebo/scripts/health_three_uav.py --mode integrated \
  --runtime-telemetry /path/to/runtime-evidence.json \
  --runtime-output .runtime/px4_gazebo/health/runtime-evidence.json \
  --publish-runtime http://127.0.0.1:8765/api --pretty
```

仿真 health 输出版本 1.1；嵌套 `runtime_evidence` 为 Runtime 接受的 1.0 契约。
载体可为原子替换的 JSON 文件，亦可显式 POST 既有 `/simulation/evidence`；本线未修改 HTTP route。
source_timestamp 来自本次 clock 样本，TTL 5000 ms。publisher 保留采样时间并扣除文件已消耗的 TTL，
拒绝过期、超前时间、重定向和非 loopback API。Runtime 仍应独立检查 source time，不能只看接收时刻。

Runtime → health 文件必须包含 contract_version=1.0、scene_id、当前 run_id、source_timestamp、valid_for_ms、
vehicles 三节点；每节点包含精确 sysid/compid/endpoint、布尔 heartbeat_fresh/telemetry_fresh、
heartbeat_timestamp、position_timestamp 和 last_seen。心跳最多 2.5 秒，位置最多 1.5 秒；
独立消息时间戳不可由整份 snapshot 的时间替代。缺失、重复、身份漂移或过期均非 ready。
Runtime `3fa42eb` 已有接收 API，但独立消息时间戳出口尚需 Runtime 主责补齐，本契约仍待其确认。

integrated health 只读 Gazebo：正确 world、至少 1 秒 clock 窗口、RTF≥0.2、三 model 和受管理进程身份。
暂停、低 RTF、model 缺失、world 错误、身份不匹配、证据过期会产生明确 reason 和非零退出码。
`simulation_status=ready` 仅代表本地物理底座；Runtime evidence 缺失时 `system_status=unknown`，总 ready=false。
此时可发布真实的仿真局部证据，但不能宣称系统已就绪。

## G1 集成验收

记录实际 Runtime 与控制台 checkout/commit，确认唯一接收者是 Runtime。
在主控制台选择 UAV-02，发起正式起飞、保持、降落；仿真侧只观察真实 pose、clock、model 与身份。
记录 Runtime action_id、trace、ACK 与完成证据，并确认 UAV-01/03 位姿不动且始终 disarmed。
保持期间采样需覆盖整个区间；不得用 API-only、standalone 或旧日志代替 UI → Runtime 的完整链路。
原始数据保存在 `.runtime/px4_gazebo/`，可审查的脱离实时契约的历史 fixture 放在本目录 fixtures。
历史 fixture 只用于回归，不可作为当前健康证据或修改时间后发布。

G1 和坐标未通过之前保持 Draft，后续青岚市 100–300 米物理任务区暂不导入。
新场景必须有独立 scene/map version 与对象 ID 映射；旧 simple_recon_v0_1 保留作回归。
