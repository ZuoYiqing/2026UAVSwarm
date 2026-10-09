# 迁移手册（2026-10-09 冻结，含 10-09 屋顶着陆更正）

> **这份文档说清三件事**：迁移到新机器要做什么、当前**验过什么**、以及**哪些坑还在**。
>
> **用它之前先选 tag**（见 §6）：
>
> | tag | 提交 | 什么时候用 |
> | --- | --- | --- |
> | **`v0.1.1-rooftop-landing-corrected`** | `e317a22` | **默认选这个** —— 文档结论已更正、含仿真侧 PR #87 |
> | `v0.1-four-module-integrated-pass` | `bfa75e8` | 只在需要复现"当时以为通过"的状态时用。**它的 §5.2 内容是错的** |
>
> 迁移后**第一件事**是跑环境自检，不要靠人工核对清单：
>
> ```bash
> cd /mnt/d/2026UAVSwarm        # 或新机器上的仓库路径
> python3 scripts/check_environment.py
> ```
>
> 它会逐项实测并给出可执行的下一步。**必需项全绿**再往下走。

---

## 1. 这份冻结的基线

| | |
| --- | --- |
| **提交** | `e317a22`（tag 见 §6；不带 tag 时以 `origin/main` 为准） |
| **测试** | Python **760 passed / 6 skipped**；主控台 **108**；三维视图 **80**；算法侧 **45** |
| **已验证的集成** | 五个飞行动作真飞**跑通**（HTTP → Policy Gate → MAVLink → PX4）—— ⚠️ 但 `return-home` 的**完成语义过松**，见 §5.2 |
| **相机** | 三路 1280×960、约 30 fps、首帧哈希互不相同、图像有效 |
| **仿真证据通道** | 已打通（`/api/simulation/evidence`，之前一直是空的） |

> ⚠️ **"五个动作跑通"不等于"动作链通过验收"。** `return-home` 曾在距离刚开始
> 缩短时就报成功，随后 `LAND` 变成"在当前位置降落"，飞机落在了 10 m 屋顶上。
> **细节见 §5.2 —— 迁移前请务必读那一节。**

**环境的已实测数字**（用于迁移后对照）：

```
实时因子 RTF            0.822 ~ 0.999（门槛 0.2）
相机版帧率              30.30 fps × 3 路
每帧                   1280×960, 3,686,400 字节
GPU                    RTX 4050 Laptop, 6141 MiB, 驱动 566.24
内存                   15.7 GiB（2× 8 GB DDR5-5600）
CPU                    i7-13620H, 10 物理核 / 16 逻辑核
WSL                    eth0 172.19.109.240, 网关 172.19.96.1
```

---

## 2. 新机器上要准备什么

### 2.1 操作系统与路径

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| Windows | 10/11 + **WSL2** | 仿真必须在 WSL 里跑（harness 明确拒绝非 Linux） |
| WSL 发行版 | Ubuntu 22.04 或更高 | 提供 `python3` 3.10+ 与 `bash` |
| 仓库路径 | **建议保持 `/mnt/d/2026UAVSwarm`** | 见下方说明 |
| PX4 源码 | `~/PX4-Autopilot`，需**已编译** | `make px4_sitl_default` |
| Gazebo | Harmonic（`gz sim --versions` 应输出 `8.x`） | 版本必须与 PX4 匹配 |
| NVIDIA 驱动 | Windows 侧装，WSL 通过 `/usr/lib/wsl/lib` 使用 | 无需在 WSL 内重复装 |

> **关于路径**：`harness.py` 的 `REPO_ROOT` 是它所在目录的上两级，
> **仿真状态与标定证据都会写在那里**；而 Runtime 只认 `<repo>/.runtime/px4_gazebo/`。
> 因此仓库路径本身可以变，但**必须从同一个仓库启动仿真与 Runtime**。
>
> 若路径变了，仓库根目录下的 `.runtime/` **建议删除后重建** ——
> 它里面存的是**上一次运行的进程身份**（`run_id` / PID / `proc_start_time_ticks`）。
> 实测过它会让 harness 拒绝启动并报 `stale state`。

### 2.2 Python 依赖

```bash
# WSL 内
python3 -m pip install pymavlink        # 必需：仿真与检查工具都用
python3 -m pip install pytest           # 可选：只在跑测试时需要
```

**前端不需要安装依赖**：主控台是静态 SPA（无构建步骤），三维视图用 Vite。

### 2.3 GPU（相机版仿真必需）

```bash
# 相机版启动时必须带这个变量
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA \
  bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless \
    --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
```

**不设它的实测后果**：WSL 会挑到集显，实时因子 **0.839 → 0.175**。
0.175 意味着 1 秒墙钟只推进 0.175 秒仿真，飞行控制与观测窗口都会失效。

---

## 3. 启动与验证（按序）

### 3.1 环境自检

```bash
cd /mnt/d/2026UAVSwarm
python3 scripts/check_environment.py
```

### 3.2 启动前自检（选好配置）

**两份 manifest 只能选一份，且 `--config` 只在启动时生效：**

| 配置 | 模型 | 相机 |
| --- | --- | --- |
| `three_uav_sitl.json`（默认） | `x500_0/1/2` | ❌ |
| `three_uav_mono_cam_sitl.json` | `x500_mono_cam_0/1/2` | ✅ |

```bash
python3 simulation/px4_gazebo/harness.py preflight \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
```

它会报三件事：这份配置有没有相机、harness state 是否写在**别的仓库**、
以及**当前实际在跑的是不是被检查的这一份**。错位时退出码非 0。

### 3.3 启动顺序

```bash
# ① 仿真（相机版）
cd /mnt/d/2026UAVSwarm
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA \
  bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless \
    --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
# 该看到三行 "UAV-0x ready" + 一张表，gazebo_model 列是 x500_mono_cam_*
# 表格出来后**再等 5-10 秒**让 PX4 的 MAVLink 实例开始外发

# ② Runtime（必须 setsid —— 普通 nohup 在 WSL 里会随父 shell 被回收）
PYTHONPATH=/mnt/d/2026UAVSwarm/src setsid nohup python3 -u -m uav_runtime.http.server \
  > /tmp/rt.log 2>&1 < /dev/null &

# ③ 健康检查（standalone：不占 MAVLink）
python3 simulation/px4_gazebo/scripts/health_three_uav.py \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json --stability-window 10

# ④ 标定（TTL 只有 60 秒，所以**要用之前**发布）
python3 simulation/px4_gazebo/scripts/sample_calibration.py \
  --duration 2 --publish-runtime http://127.0.0.1:8765/api

# ⑤ 前端（Windows 侧）
python -m http.server 5178 --directory frontend\swarm-console
# 三维视图：cd frontend\swarm-console\simulation-3d && npm run dev

# ⑥ 浏览器打开 http://127.0.0.1:5178
```

### 3.4 验证集成真的通了

```bash
# Runtime 活着
curl -s http://127.0.0.1:8765/api/health

# 三台都在、已连、标定可用
curl -s http://127.0.0.1:8765/api/vehicle-snapshot | python3 -m json.tool | head -40
#   看 spatial.calibration_status == "calibrated" 且 public_position_usable == true

# 仿真证据通道有内容（不应是 simulation_evidence_unavailable）
curl -s http://127.0.0.1:8765/api/simulation/status
```

**最后一条是这次冻结新打通的**：在本次之前它一直是
`"evidence": []` / `"reason": "simulation_evidence_unavailable"`。

### 3.5 一次真飞（证明"能控制"，不只是"能看到"）

```bash
curl -s -X POST http://127.0.0.1:8765/api/actions/smoke-takeoff \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"UAV-01","altitude_m":3}'
```

**判定标准**（缺一不可）：

* 出现 `policy_decision`，`decision_code` 为 `allow`
* 四条 ACK 都是 `MAV_RESULT_ACCEPTED`
  （`MAV_CMD_SET_MESSAGE_INTERVAL` / `MAV_CMD_COMPONENT_ARM_DISARM` /
  `MAV_CMD_NAV_TAKEOFF` / `MAV_CMD_NAV_LAND`）
* `completion_evidence.observed == true`
* **不能出现** `mavlink_stub_not_configured`
* **UAV-02/03 必须纹丝不动**（隔离性）

> ⚠️ **动作返回 `succeeded` 不等于飞机落地。** 判"是否落地"必须读遥测
> （直连 MAVLink 读 `LOCAL_POSITION_NED` 的 `-z`），本次冻结过程中就出现过
> "`land` 报成功但飞机停在约 10 m"的情况（见 §5.2）。

### 3.6 安全停止（顺序不能反）

```bash
pkill -f 'uav_runtime.http.server'          # 先停 Runtime（它占 14540-14542）
sleep 2
cd /mnt/d/2026UAVSwarm
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
sleep 3
for p in 14540 14541 14542; do
  ss -lunp | grep -q ":$p " && echo "$p 仍占用" || echo "$p 空闲"
done
# 若还有孤儿 Gazebo（stop 按进程身份校验，state 被清后就不再动它）：
pgrep -af 'gz sim'
```

---

## 4. 已经验证过的（可以依赖）

| 项 | 证据 |
| --- | --- |
| 五个飞行动作真飞 | `takeoff` / `goto` / `land` / `hold_position` / `return_home` 全部经 HTTP → Policy Gate → MAVLink → PX4 |
| `hold_position` | `max_drift_m = 0.054 m`（容差 2.0），`completion_state = stable_within_tolerance` |
| `return_home` | `initial_distance_m 28.625 → final 23.704`，`completion_state = converging_on_home` |
| 三路相机 | 407 帧 × 3、30.30 fps、1280×960、首帧哈希互不相同、图像有效 |
| 仿真证据通道 | `/api/simulation/evidence` 发布成功，Runtime 侧 `evidence_fresh: true` |
| 多机隔离 | `goto` 期间 UAV-02/03 的 armed/mode 全程未变 |
| 超时分类 | `completion_state` 区分 `partial_evidence` / `insufficient_evidence` / `not_on_ground_after_land` |

---

## 5. 还没验证 / 还在的坑

### 5.1 `camera_not_validated` **仍然不变**

**相机链路只验到"Gazebo 侧三路在出流"**，没有验到端到端的感知动作。

关键事实：`src/uav_runtime/adapters/payload_adapter.py` **是硬件无关的桩**，
该文件 66/81 行注释明确写着：

> Keep this adapter deterministic and hardware-free …
> This is not hardware success and must not be described as real capture/angle/…

**所以 `camera_capture` 动作返回的成功不是"真的拍了照"。**
要做端到端感知验收，必须先决定相机证据怎么进 Runtime
（现成通道是 `/api/simulation/evidence`，`evidence_source` 可标 `simulation_*`）。

### 5.2 `return-home` 之后接 `land`，飞机落在 **10 m 屋顶**（2026-10-09 查明）

> **本节原先记的现象与推测是错的，已按根因重写。** 原记录称"飞机停在约 10 m
> 空中悬停"并推测"`RTL` 与 `land` 冲突"——**两者都不对**。
> 完整物理证据见
> [`docs/simulation/RETURN_HOME_LAND_ROOFTOP_20261009_ZH-CN.md`](../simulation/RETURN_HOME_LAND_ROOFTOP_20261009_ZH-CN.md)。

**真实过程**（ULog + world SDF 证据）：

```
LAND 正常执行了。PX4 Commander 的 VEHICLE_CMD_NAV_LAND 分支强制请求 AUTO_LAND，
并记录 "Landing at current position"；ULog 显示 nav_state 从 RTL(5) 切到 AUTO.LAND(18)，
随后下降。

它在**当前位置的正下方**降落 —— 而正下方是 building-001 的 10 m 屋顶。
  world 中 building-001 是实际碰撞体：ENU 中心 (E=0, N=15, U=5)，箱体 6×6×10 m
  该机停在 N≈15.6, E≈-0.7 —— 正在屋顶覆盖范围内（N=[12,18], E=[-3,3]）
  PX4 dist_bottom ≈ 0.01 m 与碰撞体接触相符 → 报 landed 并 disarm
```

**所以"离地 10 m 且 armed=False"是屋顶着陆，不是悬停。** 飞控的行为与物理相符。

**原先为什么会误判**：只看了"相对原点高度约 10 m"，没有对照 `dist_bottom`
与场景碰撞体。**相对高度单独一个数不足以判断"在空中"还是"在东西上面"。**

#### 两个必须分清的问题

| 问题 | 归属 | 状态 |
| --- | --- | --- |
| **① `return_home` 的完成语义过松** | **Runtime** | ⚠️ **未修** |
| ② standalone 巡逻把屋顶 `landed` 当成场景地面着陆成功 | 仿真 | ✅ 已修（PR #87） |

**① 的具体内容**（Runtime 审计记录）：

```
return-home 当时: initial_distance_m = 28.625,  final_distance_m = 23.704
审计里的 5.039 m "进度" = 途中 max_distance − final_distance
                          **不是** 28.625 − 23.704（= 4.922）

→ 它只证明"开始向 home 收敛"，**不能证明已到 home**。
→ 于是 Runtime 在距离刚开始缩短时就把 return-home 报成成功，
  随后发出的 LAND 变成"在当前位置降落"。
```

**这条判据过松是本次事故的直接原因之一。** Runtime 侧的正式动作判据、
逐机起降点证据及真实联调**仍待完成**。

**② 的修法**（仿真侧，已合并 `af1136b`）：standalone 巡逻现在要求
`landed` + disarmed + **公共 `scene_ned` 高度在地面 ±0.3 m 内** + 至少 3 个
新位姿样本并保持 0.5 秒；屋顶的 `landed=True` 会报 `scene_ground_not_reached`，
已上锁但没有地面证据时恢复流程不会重复发送 LAND。

> ⚠️ 该判据**不**使 Runtime 的 `land` 动作自动变安全，也**不是**新场景
> 任意高度地面/屋顶的通用规则。

#### 起降点本身还没有证据

```
landing-pad-UAV-01/02/03: 公共坐标中心 (N,E,D) = (0,0,0) / (0,+8,0) / (0,-8,0)
  在 world 中是半径 1.5 m 的圆柱**视觉对象**，顶面 U=0.05 m
  **没有 collision** —— 承重面是 ground_plane 的 U=0 碰撞平面
```

**所以不能把"视觉半径 1.5 m"当成已验证的安全半径。** 仿真侧的建议是：
先提案中心到位容差 ≤0.75 m，**需逐机真实着陆验证后**再标 `valid=true`，
并以单独版本化的站点证据向 Runtime 发布；**无证据时 Runtime 应拒绝
"已在指定起降点"这一任务完成声明**。


### 5.3 降落后可能停在 `LAND` 模式，此后无法再起飞

**实测复现过一次**：`land` 之后 UAV-01 的 `mode` 停在 `LAND`，
此后 `takeoff` 立刻被拒：

```
arm_ack: MAV_RESULT_TEMPORARILY_REJECTED
code:    arm_rejected_or_timeout
```

**而链路是好的**（`local_position_stream` 的 ACK 是 `ACCEPTED`）—— 纯粹是模式问题。

**无软件解法**：Runtime 全仓**没有任何模式切换代码**，且这是**有意设计**
（`px4_sitl_backend.py:68` 注释写明 "Do not add arm/set_mode/..."）。
**只能重启仿真。**

> 注意：`_ops/MANUAL_STARTUP.md` 第 6.10 节当初的结论是
> 「"降落会导致卡在 LAND"这个推断是错的，已被实验推翻」。
> **本次它真的发生了** —— 所以那条结论需要修正，而不是继续引用。

### 5.4 动作记录重复

`/api/actions/recent` 里同一个动作会出现多次：

```
action_id  : act_755094d78099     ← 三条完全相同
request_id : req_e2f080f65e8b
唯一性: action_id 1 个、request_id 1 个  → 是**重复记录，不是重试**（无重复执行风险）
```

根因：`src/uav_runtime/http/state_store.py:222` 的 `record_action_result` 无去重。

**两个后果**：任何读原始 API 的脚本会把一次动作数成三次（而"动作是否重复执行"
是安全审查的核心问题）；`limit=50` 的窗口被重复项挤占，真实历史提前丢弃。

前端已经自己绕过（`console-model.js:242` 按 `action_id` 去重），
**所以界面看起来正常、原始 API 是脏的**。

### 5.5 `gz topic` CLI 会段错误（已有缓解）

仿真侧实测 240 次并发采样中 1 次 `SIGSEGV`（退出码 -11，stderr 为空、stdout 已有
48,384 字节）。现有缓解：只对 `SIGSEGV` 重试一次，且**丢弃崩溃进程的输出**、
不延长总超时。**恢复路径未被真实崩溃触发过**（修复后 240 次一次没崩），
只由 mock 单测覆盖。

### 5.6 相机验证脚本收尾时 SIGABRT

`verify_three_uav_cameras.py` **能正确完成**（写出完整 JSON），
但收尾时 DDS 线程析构崩溃：

```
terminate called after throwing an instance of 'std::runtime_error'
  what():  scoped_acquire::dec_ref(): thread state must be current!
```

**退出码非零不代表验证失败** —— **判据必须看输出文件**。
把它当失败会误报。

### 5.7 其他已知项

| 项 | 影响 |
| --- | --- |
| 主控台 `.runtime/` 有历史残留 | 排查时容易与当前运行混淆 |
| 标定仍需手动发布（TTL 60 秒） | 更好的做法是 harness 启动后自动发布 |
| 5 个前台窗口 | 关窗即挂。长期方案是做成服务 |
| 智飞区没有物理约束 | `nfz-001-marker` 在 SDF 里只有 `<visual>` 没有 `<collision>` |
| 青岚市场景未导入 | 三维视图只能显示 `simple_recon` 参考网格 |

---

## 6. 冻结与回滚

**两个 tag，用途不同：**

```bash
# 【推荐】带更正的版本
git checkout v0.1.1-rooftop-landing-corrected      # → e317a22
git log --oneline -1 v0.1.1-rooftop-landing-corrected

# 【仅用于复现历史】"当时以为通过"的状态
git checkout v0.1-four-module-integrated-pass      # → bfa75e8
#   ⚠️ 这个提交处的 §5.2 说"飞机停在 10 m 空中、推测 RTL 与 land 冲突"，
#      两条都是错的。看它的时候请对照 §5.2 的更正说明。

# 确认工作区干净后
python3 scripts/check_environment.py
python -m pytest -q                          # 期望 760 passed / 6 skipped
cd frontend/swarm-console && npm test        # 期望 108
cd frontend/swarm-console/simulation-3d && npm test   # 期望 80
```

> **测试数会随 main 前进而变，别把它当固定值。**
>
> | 提交 | Python |
> | --- | --- |
> | `bfa75e8`（tag `v0.1-four-module-integrated-pass`） | 757 passed / 6 skipped |
> | `e317a22`（tag `v0.1.1-rooftop-landing-corrected`） | **760 passed / 6 skipped** |
>
> **判断标准是"全绿"，不是"等于某个数"** —— 数字对不上时先看 diff，
> 而不是先怀疑环境。

---

## 7. 迁移时的四条最要紧的话

1. **不要只看"起来了"。** 本项目的坑几乎都是"看起来完全正常"：
   起的是默认版却以为在跑相机版、检查的配置不是在跑的、标定读的是过期证据。
   **每一项都要用独立信号确认。**

2. **动作返回成功 ≠ 事情做成了。** `land` 返回 `succeeded` 而飞机落在屋顶上
   就是实例（见 §5.2）。判"飞机在哪"只能读遥测 —— **而且要看对字段**。

3. **一个数不足以判断状态，要问"它相对于什么"。**
   这是 §5.2 那次误判的根因，值得单独列出来：

   | 我当时看到的 | 我据此判断 | 实际 |
   | --- | --- | --- |
   | "相对原点高度约 10 m、水平不动" | 飞机**悬停在空中** | 它**落在 10 m 屋顶上** |
   | `armed=False` 却在 10 m | 状态自相矛盾 | 完全正常：屋顶着陆后 disarm |

   **缺的那一项是 `dist_bottom`（离下方表面的距离）**，它是 `0.01 m` ——
   一眼就能看出"脚下有东西"。

   **同类的坑**：`return_home` 的进度取自"途中 `max_distance` − `final_distance`"
   而不是"起点 − 终点"，于是"距离确实在缩短"被当成了"回到 home 了"。
   **问一句"这个数是从哪儿到哪儿"，就能避免。**

4. **读不到不等于否定，算错了也不等于对。** 遥测 `None`、`/proc/net/udp` 空、
   脚本退出码非零 —— 这些都要报 `unknown` 并人工确认，**不能判成失败，
   也不能判成通过**。而反过来，**数值算得对、口径不对**同样会给出错误的结论
   （§5.2 的 5.039 m 就是"算得对但口径不是它声称的那个意思"）。
   本次冻结过程中，我自己在三个地方犯过"把缺失当结论"的错
   （见 `39607bd` 的提交信息）。
