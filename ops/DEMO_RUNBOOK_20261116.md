# 四模块串联演示手册（本机版）

**日期**：2026-11-16
**版本**：`main` @ `408215d`，tag `demo-20261113-r3`
**目标**：把四个模块（PX4/Gazebo + Runtime + 主控台 + 三维）串起来跑通，并给出可直接照做的演示剧本

---

# 零、先认清两台机器的差别（**这个差别会决定演示怎么做**）

| | **本机（开发机）** | **weier（验收机）** |
|---|---|---|
| Windows 版本 | **11，Build 26200** | **10，Build 19041** |
| WSLg（Linux 图形） | ✅ **有** | ❌ **没有** |
| Gazebo `--gui` | ✅ 能出窗口 | ❌ **出不来** |
| WSL 默认用户 | **`zyq`**（必须 `-u root`） | `root`（import 的镜像就是 root） |
| WSL 内存 | 7.6 GB（`.wslconfig` 没配） | 63.6 GB 物理，WSL 默认 8 GB |

## 结论（很重要）

> **演示的主视图必须是"网页三维"（5179），不能依赖 Gazebo 窗口。**
>
> 因为 weier 上 Gazebo 窗口根本出不来。如果演示流程里"看 Gazebo 里的飞机"
> 是必要环节，那在 weier 上一定翻车。

**Gazebo 窗口只用于本地调试时确认物理在跑，不作为演示内容。**

---

# 一、前置检查（跑一次就够）

```powershell
wsl -d Ubuntu -u root -e bash -c "ls -la /root/PX4-Autopilot/build/px4_sitl_default/bin/px4; /usr/bin/python3 -c 'import importlib.util as u; print(\"pymavlink:\", bool(u.find_spec(\"pymavlink\")))'; command -v gz"
```

**三个都要有输出**：

```
-rwxr-xr-x ... /root/PX4-Autopilot/build/px4_sitl_default/bin/px4
pymavlink: True
/usr/bin/gz
```

---

# 二、启动（四个终端，顺序不能乱）

> **全部用 `wsl -d Ubuntu -u root`**（本机默认用户是 `zyq`，不加 `-u root` 会写不进 `/root`）。

## 终端 1 —— 三机仿真（最先起，最慢）

```powershell
wsl -d Ubuntu -u root
```

```bash
cd /mnt/d/2026UAVSwarm
bash simulation/px4_gazebo/scripts/start_three_uav.sh --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json --gui
```

**本机用 `--gui`（有 WSLg，能看到 Gazebo 窗口）。
weier 上把 `--gui` 换成 `--headless`。**

**等它稳定**：大约 30~60 秒，看到三架都起来（Gazebo 里三个 x500，或日志里三架 PX4 都 `Ready for takeoff`）。

**先验证仿真这一层通了**：

```bash
ss -lunp | grep -E '1454[0-2]|1458[0-2]'
```

**应该有 6 个端口**：14540/14541/14542（Runtime→PX4）和 14580/14581/14582（PX4→Runtime）。

## 终端 2 —— Runtime

```powershell
wsl -d Ubuntu -u root
```

```bash
cd /mnt/d/2026UAVSwarm
PYTHONPATH="$PWD/src" /usr/bin/python3 -m uav_runtime.http.server
```

**必须看到**：`uav_runtime_http_bridge listening on http://127.0.0.1:8765/api`

> ⚠️ **必须是 `/usr/bin/python3`**（3.10）。pymavlink 只装在这个解释器下。

## 终端 3 —— 主控台

```powershell
wsl -d Ubuntu -u root
```

```bash
cd /mnt/d/2026UAVSwarm/frontend/swarm-console
python3 -m http.server 5178 --bind 0.0.0.0
```

## 终端 4 —— 三维（**必须用反代脚本**）

```powershell
wsl -d Ubuntu -u root
```

```bash
cd /mnt/d/2026UAVSwarm
python3 ops/serve_3d_proxy.py --dir frontend/swarm-console/simulation-3d/dist
```

> 🚨 **绝对不能用 `python3 -m http.server 5179`**。
> 三维包里写死了相对路径 `/api`，纯静态服务器会让它 404（终端刷
> `code 404, message File not found`），画面白屏或"数据源断开"。
> `serve_3d_proxy.py` 会把 `/api/*` 转发到 `127.0.0.1:8765`。

---

# 三、启动后验证（**演示前必须全过**）

## 3.1 三层各自活着

```powershell
wsl -d Ubuntu -u root -e bash -c "curl -sS http://127.0.0.1:8765/api/health"
```

**期望**：JSON，`"status": "ready"` 或至少能返回。

```powershell
wsl -d Ubuntu -u root -e bash -c "curl -sS http://127.0.0.1:8765/api/vehicle-snapshot | head -c 600"
```

**期望**：三架 `UAV-01/02/03` 都在，且 `link_quality` 有数（不是 0）。

```powershell
wsl -d Ubuntu -u root -e bash -c "curl -sS http://127.0.0.1:5179/api/health"
```

**期望**：和 8765 一样的 JSON（证明反代在工作）。

## 3.2 位置真的在动（**这是"LIVE 是真的"的硬证据**）

```powershell
wsl -d Ubuntu -u root -e bash -c "curl -sS http://127.0.0.1:8765/api/telemetry/latest | grep -o 'local_position[^}]*' | head -3; sleep 3; echo '--- 3 秒后 ---'; curl -sS http://127.0.0.1:8765/api/telemetry/latest | grep -o 'local_position[^}]*' | head -3"
```

**两次的 x/y/z 必须不同。**

## 3.3 两个前端都能打开

| 地址 | 期望 |
|---|---|
| `http://localhost:5178` | 主控台首屏，**三机 3/3** |
| `http://localhost:5179` | 三维场景，三无人机可见，**数据源已连接** |

---

# 四、演示剧本（五幕）

> **总时长约 6~8 分钟。**
> 每一幕都有"看点"（观众看到什么）和"话术"（你说什么）。

## 第一幕 · 开场：三机在飞（约 60 秒）

**操作**：什么都不做，让画面停留。

**看点**：
- 三维里三架在不同的位置
- 主控台显示 **3/3 在线**
- 链路质量在 80~100 之间波动

**话术**：
> "三架无人机在同一个 Gazebo 世界里跑 PX4 SITL，位置是真实的物理仿真结果，
> 不是动画。左边主控台读到的是 Runtime 从 MAVLink 拿到的实时遥测。"

**⚠️ 关键**：**不要说"演示数据"** —— 这一屏是真遥测。

## 第二幕 · 任务与覆盖（约 90 秒）

**操作**：点起飞（或提示已自动起飞），打开任务地图。

**看点**：
- **航点完成度**（分子/分母）
- **面积覆盖率**（分子/分母）
- **覆盖网格**在地图上逐格点亮，沿任务区边界裁剪

**话术**：
> "这两个指标是分开的 —— 航点完成度是'到了几个点'，
> 面积覆盖率是'实际扫了多大范围'。混成一个百分比会骗人。"
>
> "网格只画有覆盖记录的格子，缺证据时显示'覆盖分布未知'，不会用假数据填。"

## 第三幕 · 链路下降 → 系统自主处置（约 120 秒，**这是核心**）

**操作**：注入链路下降

```powershell
wsl -d Ubuntu -u root -e bash -c "curl -sS -X POST http://127.0.0.1:8765/api/demo/inject -H 'Content-Type: application/json' -d '{\"node_id\":\"UAV-02\",\"link_quality\":20,\"reason\":\"现场演示注入\"}'"
```

**看点**（3 秒内）：
1. UAV-02 的链路质量掉到 20 并变红
2. **不做任何操作**，等 10 秒
3. 出现 **policy 决策**（横幅/时间轴上）
4. 横幅上明确标 **"演习 / SIMULATED"**

**话术**：
> "我没有点任何按钮。系统自己判定的：链路质量低于阈值，触发了降级策略。"
>
> "特别注意这个标记 —— **策略判定和审计是真实的，但执行动作是演习模拟的**，
> 不会真的改飞行计划。我们刻意把它标出来，因为它和真飞是两回事。"

**⚠️ 这里必须主动说"演习"** —— 否则观众看到"已返航"但飞机还在飞，会以为系统坏了。

## 第四幕 · 恢复与时间轴（约 60 秒）

**操作**：清除注入

```powershell
wsl -d Ubuntu -u root -e bash -c "curl -sS -X POST http://127.0.0.1:8765/api/demo/clear -H 'Content-Type: application/json' -d '{\"node_id\":\"UAV-02\"}'"
```

**看点**：链路恢复、时间轴出现蓝色恢复节点、黄色降级节点可点开看 JSON

**话术**：
> "整条链在时间轴上，每个节点都能点开看原始事件。"

## 第五幕 · 审计回放（约 60 秒）

**操作**：打开 Audit · Replay

**看点**：整条链按时间排出来 —— 遥测 → 策略判定 → 行动 → 结果

**话术**：
> "事后可以完整重建发生了什么。这是可审计的关键。"

---

# 五、停止（顺序倒过来）

```powershell
wsl -d Ubuntu -u root -e bash -c "cd /mnt/d/2026UAVSwarm && bash simulation/px4_gazebo/scripts/stop_three_uav.sh"
```

**然后**在终端 2/3/4 各按 `Ctrl+C`。

**确认停干净**：

```powershell
wsl -d Ubuntu -u root -e bash -c "ss -lunp | grep -E '145[4-8][0-9]' || echo '端口全释放'; pgrep -fa 'bin/px4|gz sim' || echo '没有 PX4/Gazebo 残留'"
```

---

# 六、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 主控台 **0/3** | Runtime 用的 Python 没有 pymavlink | 必须 `/usr/bin/python3` |
| 三维白屏 / 刷 `code 404` | 用了 `python3 -m http.server 5179` | 换 `ops/serve_3d_proxy.py` |
| 三维"数据源断开" | Runtime 没起，或 8765 不通 | 先验 `curl 8765/api/health` |
| Gazebo 窗口出不来（weier） | Win10 19041 没有 WSLg | **改用 `--headless`**，看网页三维 |
| `Permission denied` 写 `/root` | 本机默认用户是 `zyq` | 加 `-u root` |
| 三机只有一架起来 | 内存不够 | 关浏览器/编辑器；或改 `.wslconfig` |
| 链路质量一直 89 或 0 | 转发层误归零（已修 #105） | 确认版本是 r3 |

---

# 七、演示前 30 分钟检查清单

- [ ] 四个终端都起来，没有报错
- [ ] `curl 8765/api/health` 正常
- [ ] `curl 5179/api/health` 正常（反代通）
- [ ] 两次 telemetry 的 x/y/z **不同**（位置在动）
- [ ] 主控台 **3/3**
- [ ] 三维里三架都在
- [ ] 注入 → 链路掉 → 出横幅，**全程不用点按钮**
- [ ] 横幅上有"演习"字样
- [ ] 清除注入 → 恢复正常
- [ ] 时间轴有黄色/蓝色节点
- [ ] 审计回放能打开
- [ ] **关掉所有会弹通知的软件**（微信、邮件）

---

# 八、给 weier 的三条差异提醒

1. **`--gui` 改成 `--headless`**（没有 WSLg）
2. **不用加 `-u root`**（import 的镜像默认就是 root）
3. **先改 `.wslconfig`**（`memory=48GB processors=12`），否则三机 + 相机可能 OOM

```ini
# C:\Users\<用户名>\.wslconfig
[wsl2]
memory=48GB
processors=12
swap=8GB
```
改完 `wsl --shutdown` 生效。
