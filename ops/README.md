# `ops/` —— 运维与验收工具

这套脚本解决的核心问题：**系统需要 5 个以上进程协同**
（3×PX4 + Gazebo + Runtime + 2 个前端），手工启动容易漏、顺序容易错、
出问题难定位。

**这些脚本是集成侧维护的，不是产品的一部分。** 它们只做两件事：
把人从"记顺序、记端口、猜状态"里解放出来，以及在**不该继续飞**的时候拦住你。

> 迁移请看 [`docs/release/MIGRATION_20261009.md`](../docs/release/MIGRATION_20261009.md)，
> 新机器先跑 `python3 scripts/check_environment.py`。
>
> **完整的手工流程在 [`MANUAL_STARTUP.md`](MANUAL_STARTUP.md)** ——
> 那份是权威的逐步说明（含所有已知坑），本文件只说明工具怎么用。

---

## 先跑这一条：系统能不能用？

```bash
python3 ops/system_status.py          # 人读
python3 ops/system_status.py --quiet  # 只输出结论一行
python3 ops/system_status.py --json   # 机器读
```

**它回答"这套系统现在到底能不能用"，而不是"进程还在不在"。** 这区分很重要 ——
本项目实测踩过两次"进程数正常但系统是坏的"：

| 踩过的坑 | 进程数看起来 | 实际 |
| --- | --- | --- |
| Gazebo 掉了、三台 PX4 变孤儿 | `3/1/1` 正常 | 遥测全 null、`connected_nodes=0` |
| 起的是默认版而非相机版 | `3/1/1` 正常 | 端口对、health ready、飞机能飞，**只有相机动作失败** |

所以它查**六项独立证据**：进程 · 仿真时钟推进 · 三台遥测新鲜 · Runtime 响应 ·
标定可用 · manifest 是相机版。

**退出码**：`0` 可用 · `1` 不可用 · `2` 无法判定

> ⚠️ **`unknown` 不算通过。** 读不到与没问题、与坏了，是三件事。
> 工具会把它报成"无法判定"而不是绿色。

### 系统挂了怎么恢复

```bash
bash /mnt/d/2026UAVSwarm-worktrees/_ops/restore-system.sh
```

按正确顺序停（先 Runtime 后仿真，14540-14542 是单点）→ 起相机版 → 起 Runtime →
发布标定 → 验证。**每一步都有验证**，任一步失败会停下来并打印日志位置。

---

## 快速上手

```bash
# 起仿真 + Runtime（后台常驻，日志落 ops/logs/）
bash ops/ops.sh start

# 起前端（Windows 侧）：5178 主控台 / 5179 三维视图
bash ops/ops.sh win-start        # 会打印要执行的 Windows 命令

# 另开一个终端，保持标定常新（TTL 只有 60 秒）
bash ops/ops.sh calib-loop

# 体检
bash ops/ops.sh status

# 停止（顺序自动保证：先 Runtime 后仿真）
bash ops/ops.sh stop
```

### 环境变量

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `UAV_REPO` | `/mnt/d/2026UAVSwarm` | 仓库根。仿真状态与标定都写在它下面 |
| `UAV_SIM_CONFIG` | `simulation/px4_gazebo/config/three_uav_sitl.json` | 仿真 manifest。**相机版要显式指定** |
| `UAV_GPU_ADAPTER` | `NVIDIA` | 相机版用的 GPU 适配器变量 |

**`ops.sh status` 会显示当前用的是哪一份 manifest，并在它是无相机版时告警。**
这很重要：起默认版却以为在跑相机版时，**端口对、health ready、飞机能飞**，
只有相机动作会失败 —— 它不会自己暴露。

---

## `ops.sh` —— 主工具

| 命令 | 作用 |
| --- | --- |
| `status` | 只读体检：进程数、API、三台标定、端口、前端、**当前 manifest** |
| `start` | 启动仿真 + Runtime（后台常驻） |
| `stop` | 按正确顺序停止（**先 Runtime 后仿真**，因为 Runtime 占着 14540-14542） |
| `restart` | `stop` + `start`。⚠️ 会清空标定，之后必须重发 |
| `calib [秒]` / `calib-loop` | 发布标定（TTL 60 秒） |
| `win-start` / `win-stop` | 前端服务的启动命令 / 停止 |
| `logs [sim\|rt]` | 查看日志尾部 |
| `cleanup` | 清理 WSLg 孤儿图形窗口（**不动仿真进程**） |

### 为什么 `stop` 必须先停 Runtime

`14540-14542` 是**单点**：谁先 bind 谁收到数据。Runtime 占着它们时，
仿真侧的健康检查与巡逻脚本连不上（不是"都能连"，是"抢"）。

---

## `calib.sh` —— 标定发布

```bash
bash ops/calib.sh            # 发布一次（采样 2 秒）
bash ops/calib.sh loop       # 循环发布
bash ops/calib.sh once 6     # 采样 6 秒
```

**它自动读 harness state 里记录的、当前正在跑的那一份 manifest。**
这一点重要：标定原先不传 `--config`，于是用默认（无相机）manifest 去找
`x500_*` 的位姿，在相机版仿真上报：

```
ValueError: gazebo_model_pose_missing
```

那个错的形状很坏 —— 读起来像"Gazebo 里位姿丢了"，实际是"配置拿错了"，
两者要查的方向完全相反。现在它读状态，不要求你记住传参。

**TTL 只有 60 秒**，所以要在**要用之前**发布。长时间演示用 `loop`。

---

## 验收脚本

### `integrated-acceptance.py` —— 四模块集成验收（真飞）

```bash
python ops/integrated-acceptance.py
```

走 runbook 认可的序列：`smoke-takeoff` → `takeoff` → `hold-position` →
`return-home` → `land`，并在每步之后核对：

* Policy 决策存在
* ACK 是**真实结果**（不是 stub）
* **另两台纹丝不动**（隔离性）
* 结束状态三台都在地面、已 disarm

**它会自己发布标定**（在要飞的那一刻），因为 60 秒的 TTL 会让"先发布再过来跑"
必然过期 —— 那看起来像验收失败，实际只是时序问题。

### `verify-return-home.py` —— 补验 `return-home`

```bash
python ops/verify-return-home.py
```

`return-home` 的判据是"到 home 的三维距离缩小 ≥ `min_progress_m`"。
**垂直起飞后飞机全程在 home 正上方，这个判据无从成立** ——
所以本脚本先 `goto` 把它送出去（默认北 30 m），再返航。

### `live-state-json.py` —— 直连 MAVLink 读实时状态

```bash
python ops/live-state-json.py
# {"UAV-01": {"armed": false, "mode": "LOITER", "alt": 0.016, ...}, ...}
```

**不经 Runtime、不经标定**，用于交叉验证。这在两种情况下是必需的：

* 标定过期（`calibration_status: stale`）时，Runtime 的位置不可信
* **判"飞机是否落地"** —— 动作返回 `succeeded` **不等于**飞机落地

⚠️ **字段为 `null` 表示「读不到」，不表示「没落地」。**
调用方必须报 `unknown`，不得判成失败或成功。

### `watch-uav01-altitude.py` —— 高度时间序列

```bash
python ops/watch-uav01-altitude.py
```

连续采样判断飞机是**在下降**还是**停住了**。**这两个的处置完全不同**，
而单次读数分不出来 —— 实测踩过：把两个不同时刻的读数当成趋势，得出错误的
"看起来在下降"。

---

## 交接文档

| 文件 | 内容 |
| --- | --- |
| `HANDOFF_return_home_then_land.md` | 给仿真/Runtime 侧：`return-home` 后接 `land`，飞机停在约 10 m 且 `armed=False`。含完整证据与对照实验 |

---

## 本目录**不包含**什么

集成侧还写了很多一次性的调试脚本（约 150 个：端口占用查询、SDF 校验、
JSON 解析定位、GPU 诊断等）。它们**留在会话工作区 `_ops/`**，没有进仓库 ——
因为多数只在某一次排查中有用，进仓库会让 `ops/` 变成垃圾场。

**如果你需要其中某个，问集成侧要。** 值得进仓库的通用工具（例如
`scripts/check_environment.py`）已经单独提交了。

另外 `_ops/` 里还有项目的 `TODO_CITY_IMPORT.md`（青岚市场景导入），
那是**待办事项**而不是工具，需要时另行处理。
