# 手动启动流程（离线可用）

> 本手册为**离线环境**编写：不依赖网络、不依赖 AI 助手、不依赖任何我写的脚本。
> 每一步都给出**命令**和**该看到什么**（判定标准），失败时查第 6 节。

---

## 0. 系统架构（先理解，再操作）

这套系统是 **5 个进程 + 1 个浏览器页面**，跨界运行：

```
┌─ Linux / WSL ────────────────────────────────┐
│  终端 1: PX4 ×3 + Gazebo ×1   ← 物理仿真      │
│  终端 2: Runtime HTTP bridge  ← 控制与遥测中枢 │
│  终端 3: 标定发布循环          ← 让飞机可见    │
└──────────────────────────────────────────────┘
                    ▲ HTTP 8765
┌─ Windows ────────────────────────────────────┐
│  窗口 4: 静态服务器 5178  ← 主控制台页面       │
│  窗口 5: Vite 服务器 5179 ← 三维视图 iframe    │
│  浏览器: http://localhost:5178/               │
└──────────────────────────────────────────────┘
```

### 端口分工（关键，很多"失败"其实是理解错了端口）

| 端口 | 协议 | 谁在监听 | 用途 |
|---|---|---|---|
| `14540/41/42` | UDP | **Runtime** | 收 PX4 遥测、发飞控命令（UAV-01/02/03 各一个） |
| `14580/81/82` | UDP | **PX4 自己** | PX4 的内部 MAVLink 实例 |
| `18570/71/72` | UDP | PX4 自己 | 地面站通道 |
| `14280/81/82` | UDP | PX4 自己 | 载荷 |
| `13030/31/32` | UDP | PX4 自己 | 云台 |
| `8765` | **HTTP** | **Runtime** | 前端所有 `/api` 调用 |
| `5178` | HTTP | Windows Python | 主控制台静态页 |
| `5179` | HTTP | Windows Vite | 三维视图 |

**记忆要点**：`1454x` 是"收件箱"（由控制器打开），`1458x` 是 PX4 自己开的；
**同一时刻 `1454x` 只能有一个占用者**。

### 路径约定

| 项 | 路径 |
|---|---|
| Git 仓库 | `/mnt/d/2026UAVSwarm` = `D:\2026UAVSwarm` |
| PX4 源码/构建 | `~/PX4-Autopilot`（= `/home/zyq/PX4-Autopilot`） |
| 运行产物 | `/mnt/d/2026UAVSwarm/.runtime/px4_gazebo/` |

---

## 1. 前置检查（首次在新机器上必做）

在 **WSL** 里执行：

```bash
cd ~/PX4-Autopilot
git rev-parse HEAD
gz sim --versions
test -x build/px4_sitl_default/bin/px4 && echo "PX4 BINARY OK" || echo "NOT BUILT"
python3 -c "import pymavlink; print('pymavlink', pymavlink.__version__)"
```

**判定标准**：

| 检查 | 期望 |
|---|---|
| `git rev-parse HEAD` | 打印一个 40 位 commit（参考值 `171f0f38cffa95f28d5e159f7aaf7599756f9e0e`） |
| `gz sim --versions` | 打印版本号（参考值 `8.14.0`） |
| PX4 binary | 必须 `PX4 BINARY OK` |
| pymavlink | 必须打印版本号（参考值 `2.4.49`，要求 ≥2.4.40） |

**如果 PX4 binary 不存在**：

```bash
cd ~/PX4-Autopilot
make px4_sitl
```
（这一步很慢，第一次要 20-60 分钟，且需要联网装依赖。**迁移要在有网时先做完这一步。**）

再确认仓库状态：

```bash
cd /mnt/d/2026UAVSwarm
git log -1 --oneline
git status --short
```

---

## 2. 启动顺序（严格按序，共 5 步）

### 【WSL 终端 1】仿真 —— 必须先启动

> **先自检（推荐，2026-10-09 新增）**
>
> ```bash
> cd /mnt/d/2026UAVSwarm
> python3 simulation/px4_gazebo/harness.py preflight \
>   --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
> ```
>
> 它检查三件事并给出结论：① 这份配置有没有相机；② harness state 是否写在**别的仓库**
> （那会让 Runtime 读到过期标定）；③ **当前实际在跑的是不是被检查的这一份**。
> 错位时退出码非 0，可直接在脚本里消费。

#### 先想清楚要哪种配置

| 配置 | 模型 | 相机 | 用途 |
|---|---|---|---|
| `three_uav_sitl.json`（**默认**） | `x500_0/1/2` | ❌ 无 | 只验飞行与链路 |
| `three_uav_mono_cam_sitl.json` | `x500_mono_cam_0/1/2` | ✅ 1280×960 RGB | **感知相关验收** |

**下面这条命令起的是默认版（无相机）：**

```bash
cd /mnt/d/2026UAVSwarm
bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless
```

**该看到**（约 15-30 秒后）：

```
UAV-01 ready: pid=xxxxx
UAV-02 ready: pid=xxxxx
UAV-03 ready: pid=xxxxx

node_id  instance  sysid  gazebo_model  endpoint                    spawn NED (m)      runtime_dir
--------------------------------------------------------------------------------------------------
UAV-01   0         1      x500_0        udpin:127.0.0.1:14540       (0,0,0)            .runtime/px4_gazebo/UAV-01
UAV-02   1         2      x500_1        udpin:127.0.0.1:14541       (0,8,0)            .runtime/px4_gazebo/UAV-02
UAV-03   2         3      x500_2        udpin:127.0.0.1:14542       (0,-8,0)           .runtime/px4_gazebo/UAV-03

Harness state: /mnt/d/2026UAVSwarm/.runtime/px4_gazebo/harness_state.json
```

**⚠️ 要相机版就用这条**（多了 `--config` 与 GPU 适配器变量）：

```bash
cd /mnt/d/2026UAVSwarm
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA \
  bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless \
    --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
```

**`MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` 不能省。** 不加它 WSL 会挑到集显，
实时因子从 **0.84 掉到 0.18**（实测，见 `docs/simulation/MONO_CAM_3UAV_ACCEPTANCE_ZH-CN.md`）。
这个变量只作用于**本次进程**，不改系统设置。

起对了的表现：表格里 `gazebo_model` 一列是 **`x500_mono_cam_0/1/2`**。

> **⚠️ 两种配置不能混，`--config` 只在启动时生效。**
> 已经用默认版跑起来了，就必须**先停再起**，不能"补一个参数"。
>
> **症状**：世界里是 `x500_0/1/2`（无相机），但你以为在跑相机版。
> 那个状态**表面完全正常** —— 端口对、`health` ready、飞机能飞，**只有相机动作会失败**。
>
> **怎么发现**（三个独立信号，任一个命中就说明混了）：
> · `gz model --list` 里是 `x500_0/1/2` 而不是 `x500_mono_cam_*`
> · `harness preflight` 报 `running_manifest_mismatch`
> · `health` 报 `gazebo_models_missing`

**然后这个窗口就放着别动。** 命令已经返回（后台常驻），但**不要关闭窗口**——
关掉会让 WSL 会话结束，三套 PX4 + Gazebo 会被连带回收。

> **等待就绪**：跑完表格后**再等 5-10 秒**，让 PX4 的 MAVLink 实例开始外发。
> 下一步的 Runtime 如果起太早会连不上（见第 6.3 节）。

### 【WSL 终端 2】Runtime

```bash
cd /mnt/d/2026UAVSwarm
PYTHONPATH=/mnt/d/2026UAVSwarm/src python3 -m uav_runtime.http.server
```

**该看到**：

```
uav_runtime_http_bridge listening on http://127.0.0.1:8765/api
```

**这是前台常驻进程，窗口不能关。**

**验证三个 endpoint 已被接管**（在**另一个**终端里跑）：

```bash
ss -lunp | grep -E '14540|14541|14542'
```

**该看到三行**，且都是同一个 python3 PID：

```
UNCONN 0 0 127.0.0.1:14540 0.0.0.0:* users:(("python3",pid=NNNNN,fd=4))
UNCONN 0 0 127.0.0.1:14541 0.0.0.0:* users:(("python3",pid=NNNNN,fd=5))
UNCONN 0 0 127.0.0.1:14542 0.0.0.0:* users:(("python3",pid=NNNNN,fd=6))
```

**只有 2 行 = 有节点没连上**，看第 6.3 节。

### 【WSL 终端 3】标定发布

**为什么需要这一步**：PX4 只知道"我在我自己 EKF 原点以东 2.3 米"，而三维视图要
把载具画在**共享场景原点**的坐标系里。这两张坐标表之间的偏移量，PX4 不知道、
前端也不知道 —— 必须由仿真侧实测出来并发布给 Runtime。**没有标定，三维视图
会拒绝显示载具**（这是安全设计：防止用凭空猜的坐标把飞机画在错误位置）。

```bash
cd /mnt/d/2026UAVSwarm
python3 simulation/px4_gazebo/scripts/sample_calibration.py --duration 2 \
  --publish-runtime http://127.0.0.1:8765/api
```

**该看到**：`"status": "PASS"`，`publications` 数组有 **3 条**，每条 `"http_status": 200`，
且 `published_valid_for_ms` 约 **59800**（≈60 秒）。

**有效期 60 秒**（2026-09-24 修改，原为 5000ms）。所以：

- **普通演示**：起飞前发布一次即可，够用一分钟；
- **需要长时间持续可见**：用下面的循环，每 55 秒刷新一次：

```bash
cd /mnt/d/2026UAVSwarm
while true; do
  python3 simulation/px4_gazebo/scripts/sample_calibration.py --duration 2 \
    --publish-runtime http://127.0.0.1:8765/api > /dev/null
  sleep 50
done
```

**Ctrl+C 停止。** 这个窗口也要一直开着。

> 脚本限制 `--duration` 必须在 2~10 秒之间。
>
> **为什么不能更长**：Runtime 侧 `state_store.py` 把 `valid_for_ms` 钳制在
> `[100, 60000]`，60000 就是它接受的上限。想要更长需要改 Runtime 契约。
> 而标定的**真正有效性**并不靠 TTL —— 它由 `local_origin_id`（PX4 原点字段 +
> reset counter + 完整进程身份 + Gazebo model_id 的哈希）保证：身份一变标定立即
> 失效，与 TTL 无关。TTL 只是兜住"标定本身很旧"这种情况。

### 【Windows 窗口 4】主控制台

**新开一个 PowerShell 窗口**：

```powershell
cd D:\2026UAVSwarm
python -m http.server 5178 --directory frontend\swarm-console
```

**该看到**：`Serving HTTP on :: port 5178 (http://[::]:5178/) ...`

**这个窗口不能关**（前台进程，关窗口即停止服务）。

### 【Windows 窗口 5】三维视图

**再新开一个 PowerShell 窗口**：

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d
npm run dev
```

**该看到**（3-5 秒）：

```
VITE v7.0.6  ready in xxx ms
➜  Local:   http://127.0.0.1:5179/
➜  press h + enter to show help
```

**该窗口不能关。** 如果报 `Failed to resolve import "lucide"`，见第 6.4 节。

### 【浏览器】

打开 **`http://localhost:5178/`**

- 左侧点「三维集群态势」
- 场景下拉框选第三项 **`simple_recon · 后端任务坐标`**
- 按 `Ctrl + F5` 强制刷新

**该看到**：参考网格上三台飞机 +
- 面板显示 `3 个节点 · 1 种平台`、`数据已连接`
- 状态行显示「公共坐标已校验」
- 顶部 `Runtime API LIVE`、`数据已连接`

> **必须用 `localhost` 或 `127.0.0.1`，不能用 IP。** Runtime 的 CORS 白名单
> 写死了 `localhost:5178` / `127.0.0.1:5178` / `localhost:5173` / `127.0.0.1:5173`。

---

## 3. 验证主链路（四模块集成的核心）

前面五步只证明"能看到"。**下面这一步才证明"能控制"。**

```bash
curl -s -X POST http://127.0.0.1:8765/api/actions/smoke-takeoff \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"UAV-01","altitude_m":3}'
```

**含义**：让 UAV-01 执行 ARM → 起飞到 3 米 → 观察高度 → 自动降落。
**UAV-02/03 应该纹丝不动**（这是隔离性）。

**然后查三段证据**：

```bash
curl -s "http://127.0.0.1:8765/api/actions/recent?n=5" | python3 -m json.tool
curl -s "http://127.0.0.1:8765/api/policy/decisions?n=5" | python3 -m json.tool
```

**判定标准**：
- 出现 `policy_decision_event`（Policy Gate 真的裁决了）
- 出现 `action_result`，且 `ack` 里是**真实结果**
- **不能出现** `mavlink_stub_not_configured`（那是历史 stub 记录，不是这次）

---

## 4. 健康检查与随时体检

### 快速看三台状态

```bash
curl -s http://127.0.0.1:8765/api/vehicles | python3 -m json.tool
```

关键字段：`connected` 应为 `true`，`last_error` 应为 `null`。

### 看坐标标定与可用性

```bash
curl -s http://127.0.0.1:8765/api/vehicle-snapshot | python3 -c "
import json,sys
d=json.load(sys.stdin)
for v in d['vehicles']:
    s=v.get('spatial') or {}
    print(v['id'],
          '| axis_alignment =', s.get('axis_alignment'),
          '| calibration_status =', s.get('calibration_status'),
          '| usable =', s.get('public_position_usable'))
"
```

**期望**（三台都满足）：
```
UAV-01 | axis_alignment = ned_aligned | calibration_status = calibrated | usable = True
UAV-02 | axis_alignment = ned_aligned | calibration_status = calibrated | usable = True
UAV-03 | axis_alignment = ned_aligned | calibration_status = calibrated | usable = True
```

**如果 `calibration_status = stale`** → 标定过期了，重跑第 2 步的终端 3。
**如果 `axis_alignment = None`** → 见第 6.5 节（这是 Runtime 的代码 bug）。

### 仿真侧健康检查（不带 Runtime 时用）

```bash
cd /mnt/d/2026UAVSwarm
python3 simulation/px4_gazebo/scripts/health_three_uav.py --mode standalone --pretty
```

> ⚠️ **必须先把 Runtime 停掉**，否则它俩抢 `14540-14542`。
> Runtime 在跑时只能用 `--mode integrated`，但那需要 Runtime 侧产出遥测 JSON。

### 逐机起降验证（不带 Runtime 时用）

```bash
cd /mnt/d/2026UAVSwarm
python3 simulation/px4_gazebo/scripts/validate_three_uav.py
```

同样**必须 Runtime 停止**。会逐台执行 ARM/TAKEOFF/LAND，并验证另外两台保持 disarmed。

---

## 5. 正常停止（顺序不能反）

```
① 关浏览器页面
② Windows 窗口 5: Ctrl+C   （停 5179 Vite）
③ Windows 窗口 4: Ctrl+C   （停 5178 主控制台）
④ WSL 终端 3:     Ctrl+C   （停标定循环）
⑤ WSL 终端 2:     Ctrl+C   （停 Runtime）
⑥ WSL 终端 1:     执行下方停止命令（停仿真）
```

```bash
cd /mnt/d/2026UAVSwarm
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
```

**该看到** `"status": "stopped"` 且 `cleanup.clean: true`、`world_stopped: true`、`ports_released: true`。

**为什么必须先停 Runtime**：它独占 `14540-14542`。如果先停仿真，Runtime 还攥着
端口，下次启动时 harness 的 preflight 会报 `UDP ports are already occupied` 并拒绝启动。

**为什么不要用 `pkill`**：harness 靠 `/proc/<pid>` 的启动时刻 + cmdline + cwd + run_id
做进程身份校验。手工杀会让状态文件变成孤儿，之后 stop 会返回 `stale_state` 并
**拒绝发信号**。手册明确禁止 `pkill -f px4` / `pkill -f gz` / `killall`。

**验证停止干净**：

```bash
pgrep -a px4        # 应无输出
pgrep -a "gz sim"   # 应无输出
```

---

## 6. 已知问题与解法（**离线时全靠这一节**）

### 6.1 `UDP ports are already occupied`（harness 拒绝启动）

**原因**：有残留的 Runtime 或旧仿真占着 `14540-14542`。

```bash
ss -lunp | grep -E '1454[0-2]'    # 看谁占着
pgrep -af 'uav_runtime'           # 如果是 Runtime
```

先停 Runtime（终端 2 按 Ctrl+C，或 `kill <pid>`），再重试启动仿真。

### 6.2 前端显示 `Runtime API OFFLINE`

**原因**：Runtime 没起，或浏览器访问的地址不在 CORS 白名单。

1. 确认 Runtime 在跑：`curl -s http://127.0.0.1:8765/api/health`
2. 确认浏览器地址是 `http://localhost:5178/` 或 `http://127.0.0.1:5178/`（**不能用 IP**）
3. 前端页面里 `Adapter / Backend → Runtime API 与传输端口` 确认 Base URL 是
   `http://127.0.0.1:8765/api`

### 6.3 某台飞机不显示，`/api/vehicles` 里 `connected: false`

**症状**：通常只有一台（常见是 UAV-03），另两台正常。它的
`calibration_status` 可能还是 `calibrated`（因为标定走 uORB 直读，不依赖 MAVLink），
所以容易误判。

**查真因**：

```bash
curl -s http://127.0.0.1:8765/api/vehicles | python3 -c "
import json,sys
for v in json.load(sys.stdin)['vehicles']:
    print(v['node_id'], '| connected =', v['connected'], '| last_error =', v.get('last_error'))
"
```

**如果看到 `vehicle_start_failed:TimeoutError:heartbeat_timeout`**：

**原因**：Runtime 启动太早，那台 PX4 的 MAVLink 还没开始外发，collector 等心跳超时。
**`start_vehicle` 失败后不会自动重试**，该节点会永久 offline。

**解法**：重启 Runtime（只需重启它，不用动仿真）。

```bash
# 找到并停掉 Runtime
pgrep -af 'uav_runtime.http.server'
kill <上一步列出的 PID>

# 等 5 秒，确认 PX4 在发（看 PX4 日志里的 MAVLink 行）
grep -h 'mode: Onboard' /mnt/d/2026UAVSwarm/.runtime/px4_gazebo/UAV-0*/stdout.log

# 重新启动 Runtime
cd /mnt/d/2026UAVSwarm
PYTHONPATH=/mnt/d/2026UAVSwarm/src python3 -m uav_runtime.http.server
```

**预防**：第 2 步起仿真后多等 5-10 秒再起 Runtime。

### 6.4 三维视图报 `Failed to resolve import "lucide"` 或 `"three"`

**原因**：`simulation-3d` 目录没装依赖（main 分支新增了 `lucide` 和 `three`）。

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d
npm install
npm run dev
```

**迁移提示**：`node_modules` **不在 Git 里**，新机器上必须重新 `npm install`
（离线环境需要预先准备好 npm 缓存或拷贝整个 `node_modules` 目录）。

### 6.5 前端永远"场景未对齐"（**这是一个已修的代码 bug，迁移时必须确认**）

**症状**：场景选 `simple_recon · 后端任务坐标` 后，提示 `axis_alignment 未确认或不受支持`。

**根因**：Runtime 的 `vehicle_snapshot()` 组装 `spatial` 输出时**漏传 `axis_alignment`**。
标定里明明有这个字段（值为 `"ned_aligned"`），Runtime 也用它做了自己的校验，
但没往输出里复制。前端 `scene-alignment.js` 检查该字段，拿到 `undefined` 就拒绝显示。

**检查是否已修**：

```bash
grep -n 'axis_alignment' /mnt/d/2026UAVSwarm/src/uav_runtime/http/state_store.py
```

**该看到四处**（545 / 549 / 556 是校验逻辑，**734 是修复**）：
```
545:    axis_alignment = str(evidence.get("axis_alignment") or "")
549:    and axis_alignment == "ned_aligned"
556:    "axis_alignment": axis_alignment,
734:    "axis_alignment": calibration.get("axis_alignment") if calibration else None,   ← ⚠️ 这行是修复
```

**如果只有前 556 行、没有 734 行**，说明修复丢失了。在
`src/uav_runtime/http/state_store.py` 的 `spatial` 字典里，
`"origin_continuity": ...` 那一行**下面**加一行：

```python
"axis_alignment": calibration.get("axis_alignment") if calibration else None,
```

然后重启 Runtime。

**修复的提交信息**（便于在新机器上核对）：

```
提交: f2e8abc
标题: fix(runtime): expose axis_alignment in vehicle-snapshot spatial block
```

⚠️ **这个提交只存在于本地，没有推到 origin/main。** 所以：

- 如果迁移方式是**拷贝整个 `D:\2026UAVSwarm` 目录** → 修复自动跟着走；
- 如果迁移方式是**在新机器 `git clone` 从 GitHub** → **拿不到这个修复**，
  必须用 `_ops/axis_alignment-fix.patch`（`git am` 或 `git apply`），
  或者按上面的说明手工加那一行。

### 6.6 飞机显示约 60 秒后消失（症状：`calibration_status = stale`）

**这是正常设计，不是 bug。** 标定过期后 Runtime 置 `calibration_status = stale`，
前端拒绝显示载具（防止用过期坐标把飞机画错位置）。

**有效期 60 秒**（2026-09-24 由 5000ms 改为 60000ms，见第 2 节终端 3 的说明）。

**解法**：
- 只是短暂演示 → 起飞前重新发布一次标定即可；
- 需要长时间可见 → 用第 2 节终端 3 的循环发布（`sleep 50`）。

**查询当前是否过期**：

```bash
curl -s http://127.0.0.1:8765/api/vehicle-snapshot | python3 -c "
import json,sys
for v in json.load(sys.stdin)['vehicles']:
    s=v.get('spatial') or {}
    print(v['id'], s.get('calibration_status'), s.get('calibration_age_ms'), 'ms',
          'usable=', s.get('public_position_usable'))"
```

`age` 超过 `valid_for_ms`（≈60000）就是过期了。

### 6.7 `ss -lunp | grep 14540` 没有任何输出

**在 Runtime 未启动时这是正常的** —— `1454x` 是"接收端口"，由控制器（Runtime）
打开。没有控制器时它们就是空的。

**真正该看的是 `1458x`**（PX4 自己的监听端口）：

```bash
ss -lunp | grep -E '1458[0-2]'    # Runtime 未起时也应该有输出
```

### 6.8 关掉终端窗口后服务消失

**原因**：所有进程都是**前台进程，挂在终端会话上**。关窗口 = 杀进程。

| 窗口 | 关掉的后果 |
|---|---|
| WSL 终端 1（仿真） | **飞机消失**（PX4/Gazebo 被 WSL 会话回收） |
| WSL 终端 2（Runtime） | 浏览器显示 OFFLINE |
| WSL 终端 3（标定） | 飞机 5 秒后消失 |
| Windows 5178 | 页面打不开 |
| Windows 5179 | 三维视图白屏 |

**这是本系统当前最大的运维脆弱点**。长期方案是做成 systemd 服务（Linux 侧）
和 Windows 服务/计划任务（Windows 侧），让进程不依赖终端。

### 6.9 端口被占但找不到进程

```powershell
# Windows 侧：按端口找进程并杀掉（一行，不用手抄 PID）
Get-NetTCPConnection -LocalPort 5179 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

```bash
# WSL 侧
ss -ltnp | grep 8765      # 看 PID
kill <PID>
```

---

### 6.10 【未解决】起飞被拒：`MAV_RESULT_TEMPORARILY_REJECTED` + 飞机停在 LAND 模式

**状态：已调查，未能复现，暂不改代码（属于已知问题，非已修问题）。**

### 现象（实测记录，2026-09-23）

某台飞机（当时是 UAV-02）按"起飞"按钮后：

```
accepted = False
result   = fail
status   = timed_out
failure_reason = arm_rejected_or_timeout
arm_ack.result_name = MAV_RESULT_TEMPORARILY_REJECTED
```

同时 `/api/vehicle-snapshot` 显示这台飞机：

```
mode  = LAND      ← 停在 LAND 模式
armed = False
高度  ≈ 0 m
```

之后**所有**起飞尝试都在约 **0.008 秒**内失败（本地快速拒绝，不是超时）。审计日志里
这个循环连续出现 4 次。

### 已确认的事实

| 事实 | 证据 |
|---|---|
| Runtime 的 `arm()` **只发 ARM，不设置飞行模式** | `mavlink_backend_session.py:492-496` |
| Runtime 的 GCS 心跳 `base_mode=0`、`custom_mode=0`，**不设置任何模式** | 同文件 `:319-336` |
| Runtime 全仓库**没有任何模式切换代码** | 搜 `DO_SET_MODE` / `set_mode` 只命中无关处 |
| 这是**有意设计**，不是遗漏 | `px4_sitl_backend.py:68` 注释写明 "Do not add arm/set_mode/..." |
| **结论：模式由 PX4 自己管理，Runtime 不介入** | 上述证据综合 |

### 已尝试但**未能复现**的操作序列

| 尝试 | 序列 | 结果 |
|---|---|---|
| 1 | 正常起飞 → 降落 → 再起飞 | ✅ 成功，降落干净，模式自己回 LOITER |
| 2 | 起飞（带可疑参数）→ 降落 → 再起飞 | ✅ 成功 |
| 3 | 在已落地的飞机上发 LAND → 再起飞 | ✅ 成功 |

**所以"降落会导致卡在 LAND"这个推断是错的**，已被实验推翻。

### 为什么当时抓不到证据

第一次失败是 **HTTP 404**（那一刻 Runtime 没在服务），**请求根本没到 Runtime**，
所以审计日志里没有记录。等 Runtime 恢复后，坏状态已经形成了，但**形成的原因没有留痕**。

### 下次再出现时必须做的事

**不要重试、不要点降落**（点降落可能让状态更乱）。**立刻**运行现场捕获：

```bash
python3 /mnt/d/2026UAVSwarm-worktrees/_ops/capture.py "描述你做了什么、看到什么"
```

它会把那一刻的全部可观测状态抓成一个 JSON（连接状态、每机 mode/armed/高度/标定、
最近 20 条策略裁决、最近 30 条事件），存到
`_ops/logs/capture-<UTC时间戳>.json`。**这个文件是唯一能还原现场的东西。**

然后再记录：**出现这个现象之前，你连续点了什么**（起飞/降落/其他，几次，间隔多久）。
触发它的那个动作很可能不在审计日志里（如果连 Runtime 都没走到）。

### 一个尚未验证的缺口（**不要在没有证据时修改**）

`arm()` 不检查也不设置飞行模式，因此只要 PX4 处于任何禁解锁状态
（LAND / RETURN / OFFBOARD / 飞手手动切到的模式），Runtime 的起飞就必然失败，
而且**没有任何恢复手段**。

理论上可以"起飞前先发 `MAV_CMD_DO_SET_MODE` 切到 LOITER，再 ARM"来解决。
**但这属于修改安全关键路径**（MAVLink 时序），且当前**无法复现坏状态 →
无法验证修复是否有效**。在不能复现的情况下改飞控时序，风险大于收益。

**建议**：等再次出现并抓到完整现场后，再决定是否实施。届时可以用
"正常起飞→降落→起飞"的回归来证明改动不破坏现有流程。

#### 【2026-09-28 更新】已复现，根因确认

**复现了**，而且找到了根因：**这不是独立的缺陷，而是 goto 收尾把飞机留在
`AUTO/RTL` 状态后的后遗症**（详见 6.12 缺陷二）。

复现路径：

```
goto 收尾错误地落到 RTL（自主返航）
  → 飞机飞回原点后自动降落、disarm
  → 但 PX4 的 nav_state 停在非正常值
  → 此后 Runtime 报 mode=UNKNOWN，且 ARM 一直被
     MAV_RESULT_TEMPORARILY_REJECTED 拒绝
  → 只有重启仿真才能恢复
```

当时的诊断方向（"MAVLink 时序问题，需要在起飞前补切模式"）是**错的** ——
真正要修的是 goto 的收尾逻辑，不是 takeoff 的前置动作。

**结论**：6.12 的两个修复落地后，这个症状应该不再出现。若再次遇到
`MAV_RESULT_TEMPORARILY_REJECTED` + `mode=UNKNOWN`，先查**上一次 goto 的
`restored` 证据**（`still_in_offboard`、`observed_sub_mode`），而不是去改 takeoff。

---

### 6.11 动作接口的探测陷阱（**我踩过，务必注意**）

`/api/actions/takeoff`、`/api/actions/smoke-takeoff`、`/api/actions/land` 这三个端点
**只接受 POST，而且 POST 就是真的发飞控命令**。

**所以不能用"发个请求看返回码"来判断路由是否存在**：

- 用 **GET** 探测 → 必然 404（路由只挂 POST），会误判成"路由不存在"；
- 用 **POST 空 body** 探测 → **真的会让飞机起飞**（`node_id` 默认 UAV-01，
  `altitude_m` 默认 3.0）。我就这样误触发了三次真实起飞。

**正确的探测方法**：用**非法的**参数，让参数校验先拦下来：

```bash
curl -s -X POST http://127.0.0.1:8765/api/actions/takeoff \
  -H 'Content-Type: application/json' -d '{"altitude_m":-1}'
# 期望 HTTP 400 invalid_parameter → 说明路由存在（且没有执行任何动作）
```

同理，路由不存在的表现是 **404 `not_found`**。区分 400 和 404 就能既确认路由、
又不触发副作用。

### 6.12 goto（飞到指定坐标）—— 2026-09-28 实测通过，含两个已修的真实缺陷

**功能已可用**。`POST /api/actions/goto` 能让飞机飞到共享 `scene_ned` 坐标系的
指定点并稳定悬停。实测结果（UAV-01，目标 N=4.0，高度 3.0）：

```
result           : pass
mode_confirmed   : True   (PX4 确实进入 OFFBOARD)
arrival_observed : True   误差 0.144 米，稳定保持 1.6 秒
restored         : AUTO_LOITER，still_in_offboard=false
悬停 20 秒漂移   : N 在 4.04~4.07 之间，高度恒为 2.99~3.00 米
```

**但前两次实测都失败了，暴露两个只有活体才能发现的缺陷。迁移后若从旧代码
重新构建，务必确认这两个修复都在。**

#### 缺陷一：`type_mask` 语义搞反 → 飞机原地不动（已修）

`SET_POSITION_TARGET_LOCAL_NED` 的 `type_mask` 是"**忽略哪些字段**"（1=忽略）。
要让位置生效，必须把**速度位也置 1 忽略**：

```
X|Y|Z=7        位置生效（必须为 0）
VX|VY|VZ=56    必须为 1 ← 漏掉这三个位就出事
AX|AY|AZ=448   必须为 1
YAW|YAW_RATE=3072  必须为 1
合计 = 3576
```

漏掉速度位（掩码成了 3520 一类）时，语义从"使用位置"变成"使用速度"，
而速度字段填的是 0,0,0 → PX4 理解为"以 0 速度飞行" = **原地悬停**。

**危险之处是完全静默**：ACK 正常、setpoint 流 10Hz 正常发出、没有任何报错，
只表现为"飞机一动不动直到超时"。单元测试（只校验字段排列）发现不了。

#### 缺陷二：收尾把 `AUTO/RTL` 当成安全悬停 → 飞机自行飞走（已修）

`AUTO` 主模式下**子模式决定实际行为**，只看主模式会出大事：

| 主模式 | 子模式 | 行为 |
|---|---|---|
| AUTO(4) | LOITER(3) | 定点悬停 ✅ |
| AUTO(4) | **RTL(5)** | **自主返航：爬升后飞回原点** ❌ |

实测事故：goto 报 `pass`，随后飞机进入 RTL，爬升到 8.57 米、以 2.46 m/s
飞回原点。当时立即发 LAND 才安全落地。

根因有两层：① 收敛判据只比主模式；② 收尾命令用了 `set_mode(main_mode=4,
sub_mode=0)`，而 `sub_mode=0` 在 AUTO 下未定义，PX4 落到了 RTL 行为。

**修复**：收敛判定改为白名单，只接受真正"定点"的模式
（`POSCTL`、`ALTCTL`、`AUTO+LOITER`）；默认收尾目标改为 `AUTO+LOITER`。

#### 使用要点

```bash
# 目标是 scene_ned：北/东/下（z 向下为正，所以 -3 = 高度 3 米）
curl -s -X POST http://127.0.0.1:8765/api/actions/goto \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"UAV-01","north_m":4.0,"east_m":0.0,"down_m":-3.0}'
```

* **必须先有有效标定**，否则直接拒绝（`coordinate_calibration_unavailable`），
  不会"尽力而为"地飞。标定 60 秒过期，长任务要开 `calib-loop`。
* 飞机需要**已在空中**（goto 不会自己解锁起飞）。先 takeoff。
* `restored.still_in_offboard` 是**必须看的字段** —— 若为 true，说明飞机还停在
  OFFBOARD，属于危险状态。
* 若要观察飞行，先开 `calib-loop`，否则三维视图会因标定过期而隐藏载具。

---

### 6.13 起的是默认版却以为在跑相机版（**2026-10-09 新增，我踩过**）

#### 现象

世界里跑的是 `x500_0/1/2`（**无相机**），但操作者以为在跑相机版。
那个状态**表面完全正常**：

* 端口对（`14540-14542` 有人收）
* `health` 可能报 ready
* **飞机能飞** —— TAKEOFF / GOTO / LAND 全都正常

**只有相机动作会失败。** 所以它不会自己暴露。

#### 为什么会踩

第 2 节的默认命令**不带 `--config`**，起的就是无相机版：

```bash
bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless   # ← 默认，无相机
```

而 `ops.sh start` 也是同一条（它写死了不带 `--config`）。**两条最常走的路都通向无相机版。**

`--config` **只在启动时生效**，已经跑起来之后不能"补一个参数"——必须先停再起。

#### 三个独立的发现信号（任一个命中就说明混了）

```bash
# ① 直接问 Gazebo 里有哪些模型
gz model --list | grep x500
#   无相机版: x500_0 / x500_1 / x500_2
#   相机版  : x500_mono_cam_0 / x500_mono_cam_1 / x500_mono_cam_2

# ② 自检会明确报出来（推荐，退出码非 0 可直接在脚本里消费）
cd /mnt/d/2026UAVSwarm
python3 simulation/px4_gazebo/harness.py preflight \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
#   → [error] running_manifest_mismatch
#     本检查针对的是 …/three_uav_mono_cam_sitl.json，
#     但当前实际在跑的是 …/three_uav_sitl.json

# ③ health 报 gazebo_models_missing（它期望的名字与实际不符）
```

> **关于 ② 的一个教训**：这个检查最初**只回答"你给我的这份配置有没有相机"**，
> 不回答"现在实际跑的是哪一份"。于是拿相机配置去检查一个无相机的运行，
> 它会乐观地报 `camera.present=True`、`ok: True` —— **恰好把该抓的问题放过去**。
> 现在它会读 harness state 里的 `manifest_path` 做显式比对。
>
> **判据读的是状态里记的"用了哪一份"，不靠模型名反推** ——
> 推断是多余的，而且会错。

#### 解法

```bash
# 先停（--config 只在启动时生效，不能热改）
cd /mnt/d/2026UAVSwarm
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
# 确认停干净
for p in 14540 14541 14542; do ss -lunp | grep -q ":$p " && echo "$p 仍占用" || echo "$p 空闲"; done

# 再按相机版重启（第 2 节那条带 GPU 变量的命令）
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA \
  bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless \
    --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
```

#### 相关：`ops.sh` 的默认值

`ops.sh start` 起的是默认版。要它起相机版，用环境变量：

```bash
UAV_SIM_CONFIG=simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json \
  bash /mnt/d/2026UAVSwarm-worktrees/_ops/ops.sh start
```

`ops.sh status` 会显示当前用的 manifest，并在它是无相机版时给出警告。

---

## 7. 迁移到新电脑的检查清单

### 7.4 待处理的技术债（迁移后建议尽快做）

| 项 | 影响 |
|---|---|
| **【未解决】起飞被拒 + 停在 LAND 模式** | 见 6.10 节。已调查但未复现，未改代码。再出现时先跑 `capture.py` 抓现场 |
| **前端失败提示信息不足** | 动作失败时只显示 `status=timed_out`，而真正有用的 `arm_ack.result_name`（如 `MAV_RESULT_TEMPORARILY_REJECTED`）被埋在后面。应优先展示 ACK 结果 |
| **起飞前不检查飞行模式** | 若飞机处于 LAND 等禁解锁模式，起飞必然失败，UI 也不提前提示。可在点按钮前检查 `telemetry.mode` 并给出明确指引 |
| 5 个前台窗口 | 运维脆弱，关窗即挂。长期方案是做成 systemd 服务（Linux 侧）+ Windows 服务/计划任务 |
| **标定仍需手工发布** | 有效期已从 5 秒延长到 60 秒，但每次重启 Runtime 后仍需跑一次。更彻底的做法是让 harness 启动后自动发布，或由 Runtime 在收到仿真证据时自动刷新（都属于改契约，需走流程） |
| 青岚市物理场景未导入 | 三维视图只能显示 `simple_recon` 参考网格，看不到城市 |
| `goto` 等 17 个动作无 HTTP 端点 | 注册表有 21 种动作，HTTP bridge 只实现了 4 个。**"让飞机到处飞"需要的就是这个** |
| **禁飞区没有物理约束** | `nfz-001-marker` 在 SDF 里只有 `<visual>` 没有 `<collision>` —— 飞机可以直接飞进去，物理上无阻碍，Runtime 也没有禁飞区检查 |
| 主目录 `.runtime/` 有 8 月残留状态文件 | 排查时容易与当前运行混淆 |

> **已修复并已推送到 GitHub 的项**（无需再处理）：
> `f2e8abc` 补 `axis_alignment` 透传 · `1fc4494` 三维视图起飞/降落控制 +
> 选择 bug 修复 + CORS 白名单加 5179 · 标定有效期 5000ms → 60000ms。

---

## 8. 参考：验收证据位置

```text
/mnt/d/2026UAVSwarm/.runtime/px4_gazebo/
├── harness_state.json              仿真进程状态（run_id / PID / cwd / 端口）
├── UAV-01/ UAV-02/ UAV-03/
│   ├── stdout.log                  PX4 输出（含 MAVLink 端口分配行）
│   ├── stderr.log
│   └── log/YYYY-MM-DD/*.ulg        飞行日志
├── calibration/latest.json         最近一次标定
├── health/latest.json              最近一次健康检查
└── validation/                     历史验收证据（validate / patrol）
    ├── three_uav_validation_*.json
    └── three_uav_patrol_*.json
```

**排查时先看 `run_id`**：它每次启动都变。对不上 run_id 的证据是**上一轮的**，
别当成当前状态。

---

## 9. 三个最容易踩的坑（离线时记住这三条）

1. **关窗口 = 杀进程。** 五个窗口一个都不能关。飞机凭空消失、页面突然打不开，
   第一个要查的就是"是不是关了哪个窗口"。

2. **Runtime 起太早会让节点永久 offline。** 起完仿真**多等 5-10 秒**再起 Runtime。
   单节点 `connected: false` 就是这个原因，靠重启 Runtime 解决。

3. **`1454x` 空着是正常的（Runtime 未起时）。** 该看的是 `1458x`。
   而 Runtime 起来后 `1454x` 必须**正好三行**，只有两行就是有节点没连上。
