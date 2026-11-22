# 四模块联调任务书（交给系统集成负责人）

**日期**：2026-11-22
**当前版本**：`main` @ `dce362d`
**你的角色**：把"仿真 + Runtime + 主控台 + 三维"这一整套在本机真正跑通，并确认哪些是真实功能、哪些是演示剧本、哪些还是设计稿
**不要做的事写在最后一节，先看那一节**

---

# 零、现在的状态（都已核实，不用重新查）

## 代码

| 项 | 值 |
|---|---|
| `main` | `dce362d`（5 个新提交已合入） |
| 全量 pytest | **1100 passed, 12 skipped, 0 failed** |
| 前端测试 | 133 项（#108 之后） |
| 未合入的分支 | `codex/auto-calibration-on-start` @ `ebb33aa`（标定自动化，**待仿真负责人 review**） |

## 最近合入的 5 个 PR（全是 11-20）

```
#106 a8bdc7f  frontend  本地模型证据回放（只读）
#107 9cf459e  frontend  本地试推理（只读）
#108 8f0ea93  frontend  澄清 LIVE 视图、精简演习 ← 影响演示观感最大
#109 673b552  algorithm 离线协同基准
#110 dce362d  algorithm 语义预览服务（实验性质，需本地模型）
```

**#106/#107/#108 改的是前端，已合入 main。**
**#109/#110 全在 `algorithm_lab/mission_llm_poc/`，不碰演示链路。**

## 环境（本机，已修好的三个坑）

| 项 | 状态 |
|---|---|
| WSL 发行版 | `Ubuntu`，**默认用户是 `zyq`，不是 root** |
| WSL 虚拟磁盘 | 已从 C 盘搬到 **`D:\wsl\Ubuntu`**（治过 C 盘满） |
| C 盘可用 | 86.8 GB |
| PX4 | `/home/zyq/PX4-Autopilot`，`bin/px4` 56 MB（8 月编的） |
| PX4 参数文件 | `build/px4_sitl_default/etc/parameters.bson` **已补**（原来缺，PX4 会以为首次运行然后退出） |
| `.runtime` | **软链接** → `/home/zyq/uavswarm-runtime`（ext4） |
| Gazebo | 8.14.0 |
| pymavlink | 2.4.49（`zyq` 名下） |
| node/npm | **Windows 侧**（`C:\Program Files\nodejs`），WSL 里没有 |

---

# 一、任务 1：清残留并起仿真（先做这个）

## 为什么必须先做

`.runtime/px4_gazebo/harness_state.json` 是 **11-19 22:25 的残留**，里面的 PX4 进程早已不存在。

## 命令（WSL，默认用户 `zyq`，**不要加 `-u root`**）

```bash
cd /mnt/d/2026UAVSwarm
pgrep -af 'bin/px4|gz sim|uav_runtime' || echo "确认无残留进程"
ss -lunp | grep -E '1454[0-2]|1458[0-2]' || echo "确认端口空闲"
```

**两个都是"确认"输出才继续。**

```bash
cd /mnt/d/2026UAVSwarm && MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA bash simulation/px4_gazebo/scripts/start_three_uav.sh --headless --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json
```

## 验收

```
UAV-01 ready: pid=xxxxx
UAV-02 ready: pid=xxxxx
UAV-03 ready: pid=xxxxx
```
表格 `gazebo_model` 必须是 **`x500_mono_cam_0/1/2`**。

## 三个已知坑（遇到别再排查一遍）

| 现象 | 原因 | 处理 |
|---|---|---|
| `SYS_AUTOCONFIG: 0 -> 1` 后立刻 `Startup script returned with return value: 15` | `etc/parameters.bson` 缺失 | 已修；若复发，从 `rootfs/` 拷回两份 bson |
| PX4 只输出 2 行就僵住，模型永远不出现 | **cwd 在 `/mnt/d`（9p）上会卡死** | `.runtime` 必须是指向 ext4 的软链接；`ls -ld .runtime` 确认 |
| `Unable to find uri[x500]` / `[model://mono_cam]` | `GZ_SIM_RESOURCE_PATH` 没含 PX4 models 目录 | harness 已设；手工跑 PX4 时必须自己设 |

---

# 二、任务 2：起 Runtime，验证数据链路

```bash
cd /mnt/d/2026UAVSwarm && PYTHONPATH=/mnt/d/2026UAVSwarm/src python3 -m uav_runtime.http.server
```

**必须用 `python3`（= 3.10），不要用别的解释器** —— pymavlink 只装在这个解释器下。

## 验收（在另一个终端）

```bash
curl -s http://127.0.0.1:8765/api/health
curl -s http://127.0.0.1:8765/api/vehicles | python3 -m json.tool | grep -E 'node_id|connected'
```

**三台都要 `"connected": true`。**

## 已知坑

| 现象 | 原因 |
|---|---|
| 某台 `connected: false`，`last_error` 里有 `heartbeat_timeout` | **Runtime 起太早**，那台 PX4 还没开始外发。**不会自动重试**，只能重启 Runtime |
| 主控台 0/3 | Runtime 用了没有 pymavlink 的 Python |

---

# 三、任务 3：标定（**目前只能手工，这是已知技术债**）

## 为什么需要

三维视图只在拿到"新鲜"的公共坐标证据后才画载具。那份证据是把 Gazebo 世界坐标和每台 PX4 自己的 EKF 原点对齐的换算表，**有效期 60 秒**。

## 命令（`--duration` 必须 10，不要用 2）

```bash
cd /mnt/d/2026UAVSwarm && python3 simulation/px4_gazebo/scripts/sample_calibration.py --duration 10 --publish-runtime http://127.0.0.1:8765/api
```

**为什么必须 10**：标定门槛是"≥10 个样本且跨度 ≥1 秒"。`--duration 2` 采不满，会报 `calibration_insufficient_samples`（实测踩过）。

## 验收

```bash
curl -s http://127.0.0.1:8765/api/vehicle-snapshot | python3 -c "
import json,sys
for v in json.load(sys.stdin)['vehicles']:
    s=v.get('spatial') or {}
    print(v['id'], s.get('calibration_status'), s.get('axis_alignment'), s.get('map_version'), s.get('public_position_usable'))"
```

**期望三台都是**：`calibrated  ned_aligned  simple_recon_v0_1-map-1  True`

## 长时间显示

```bash
cd /mnt/d/2026UAVSwarm && while true; do python3 simulation/px4_gazebo/scripts/sample_calibration.py --duration 10 --publish-runtime http://127.0.0.1:8765/api > /dev/null 2>&1; sleep 45; done
```

## 这一条的技术债

`codex/auto-calibration-on-start` @ `ebb33aa` 已经把这件事自动化了（起仿真即自带坐标）。**但它要仿真负责人 review 后才能合**。在合入之前，手工跑上面那条。

**你不需要 review 它，你只需要知道：当你看到飞机过 60 秒消失，那不是 bug。**

---

# 四、任务 4：起两个前端

## 主控台（Windows PowerShell）

```powershell
cd D:\2026UAVSwarm
python -m http.server 5178 --directory frontend\swarm-console
```

## 三维（Windows PowerShell）

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d
npm run dev
```

**本地是 `npm run dev`（Vite 自带 `/api` 反代到 8765），不要用 `ops/serve_3d_proxy.py`** —— 那是 weier 没有 node 时的替代品。

## 验收

浏览器开 **`http://localhost:5178/`**（不能用 IP，CORS 白名单写死 localhost/127.0.0.1）
- 左侧点「三维集群态势」
- 场景下拉选 **`simple_recon · 后端任务坐标`**
- **Ctrl+F5 强刷**

---

# 五、任务 5：验证 #108 的三处改动（**这是本次最重要的验证**）

前端负责人在 #108 里做了三件事，你需要逐条确认它们真的生效：

## 5.1 没有任务边界时，也先把载具画出来

**背景**：以前没有任务区域数据时，三维只显示"等待"；#108 改成"只要有校验过的共享坐标，就先画载具位置"。

**怎么验**：
1. 确保标定有效（任务 3）
2. 三维选 `simple_recon · 后端任务坐标`
3. **期望**：参考网格上看到三架 UAV（即使没有任务边界、没有航点）

**如果看不到**：先查 `curl 8765/api/vehicle-snapshot` 的三个 `usable` 是不是 `True`。是的话说明是前端问题，报给前端负责人。

## 5.2 「等待分配」应改成「未收到任务分工」

**怎么验**：主控台任务面板，看三架的分工文案。

**期望**：不再出现「等待分配」（那个说法让人以为后台分配器在排队）。

## 5.3 演习入口应收进「离线演习」

**怎么验**：主控台右上角。

**期望**：总览里不再常驻「Runtime 演示注入未启用」，改成一个「离线演习」入口。

---

# 六、任务 6：验证任务规划页的「模板预览」（**这条最容易翻车，重点看**）

## 背景：旧版是假的，新版才真

| 项 | 旧版（已删） | 新版（#108） |
|---|---|---|
| 「18 条策略通过」 | **写死的假数字** | 已移除 |
| 「42/100 风险」 | **写死的假数字** | 已移除 |
| 「生成请求」 | **发送固定文本，不读输入框** | 读输入框，提交给 Runtime 模板接口 |
| 返回内容 | 假的 | **Runtime 实际返回的步骤/JSON/策略预检/风险级别** |

## 怎么验

1. 主控台进「任务规划」
2. **在左侧输入一句自己的话**（不要用工整的示例，故意用口语，例如"先看看西边那排光伏板，再去机房"）
3. 点「生成请求」
4. **期望**：显示的步骤/JSON **跟着你输入的内容变**，不是你输入什么都返回同一套

**判定要点**：
- 如果换个输入，返回完全一样 → **说明它还是假的**，立刻报前端负责人
- 如果返回里出现你输入内容里的词 → 说明确实读到了输入框

## 必须理解的边界（前端负责人原话）

> 「Runtime 快照到三维已经接通。还缺的是让算法生成带载具分工、航线和场景版本的可校验计划，再把它接入仿真执行。**当前新版接通的是模板预览。**」

**所以"模板预览"≠"任务到执行"**：
- ✅ 通：输入文字 → 提交 → 显示 Runtime 模板接口返回的步骤
- ❌ 没通：任务书 → 算法生成分工/航线 → 仿真真飞 → 首页进度同步

**这条边界你要写进报告，不要让任何人误以为整条链已经贯通。**

---

# 七、任务 7：验证 DEMO 大屏（演习，不是真实数据）

## 它是什么

前端离线脚本生成的剧本，**和 Runtime 完全无关**，即使没有仿真也能播。

## #108 之后的结构

收成**三章，约一分钟**（原来十镜、每镜 18 秒、总长 3 分钟）：
1. 三机分区
2. 链路降级与接续
3. 恢复与结果

地图、指标、事件**同屏**，可以暂停讲，也可以直接选一章。

## 怎么验

主控台切到 DEMO 模式，确认：
- 三章能切换
- 可以暂停
- 地图/指标/事件同屏

## 口径要求（**必须做到**）

> **演示时绝不能把 DEMO 大屏说成实时数据。**
> 舞台大屏（`?mode=stage`）是内置演习，播的是预设脚本。

---

# 八、任务 8：验证 LIVE 大屏

## 它是什么

真实数据，四个视图：任务地图 / 任务状态 / 审计事件 / 三维态势，第四页就是 Cesium。

## #108 之后

- 默认停在选中的页面（不再自动轮播抢话筒）
- 可以手动切换
- 也可以手动开自动轮播

## 怎么验

LIVE 模式下四个视图都能切，且**第 1 页有数据**（在三机在线 + 标定有效的前提下）。

---

# 九、任务 9：算法新代码（**只 review，不接演示**）

## 拉下来的东西

```bash
cd /mnt/d/2026UAVSwarm && git pull --ff-only origin main
```

14 个文件，全在 `algorithm_lab/mission_llm_poc/`：
- `docs/ANCHORING_A_V04_SWARM_GAME_DRAFT.md` — 语义锚定题集（12 题，两个题域）
- `src/uavswarm_llm_lab/preview_server.py` — 语义预览 HTTP 服务
- `src/uavswarm_llm_lab/coordination_bench.py` 等 — 协同基准
- `tests/test_semantic_preview_server.py` 等 — 360 行测试

## 你要做的

```bash
cd /mnt/d/2026UAVSwarm/algorithm_lab/mission_llm_poc && python3 -m pytest -q
```

**只确认测试能过、不修改任何东西。**

## 不要做的事

**不要试图把语义预览接进演示链路。** 原因：
- 它需要一个**本地模型**跑在 `127.0.0.1:18116/v1`（alias `qwen3.5-0.8b-q4-lab`），当前没起
- 代码里写死了 `"not a Runtime endpoint"`，是实验工具
- 算法负责人自己标的状态是「草案，供审题，**尚未冻结、未跑模型、无分数**」

---

# 十、任务 10：把"什么是真的"列成一张表

这是你最重要的交付物。逐项确认并写进报告：

| 功能 | 真实性 | 依据 |
|---|---|---|
| 三机遥测在线（3/3） | **真实** | Runtime 从 MAVLink 收 |
| 链路质量分数 | **真实** | 收包新鲜度算出来的 |
| 三维里飞机的位置 | **真实**，但依赖标定有效性（60 秒） | 标定 = Gazebo 位姿 + PX4 局部位置 |
| 任务地图的区域/覆盖 | **需要任务数据才有**，现在没有 | Runtime 没收到任务边界 |
| 任务规划页返回的步骤 | **真实**（Runtime 模板接口的实际返回） | #108 |
| 任务规划页「18 条策略通过」「42/100」 | **已删除**（原来是写死的假数字） | #108 |
| DEMO 大屏的三机位置/处置 | **剧本**，与 Runtime 无关 | 前端离线脚本 |
| 「演习/SIMULATED」标记 | 有标记就是演习 | 需 `UAV_RUNTIME_DEMO_ENABLED=1` |
| 算法语义锚定 | **离线实验，未接演示** | 算法负责人自述 |

---

# 十一、不要做的事（**先看这一节**）

1. ❌ **不要合 `codex/auto-calibration-on-start`** —— 等仿真负责人 review
2. ❌ **不要改 `src/uav_runtime/`** —— Runtime 负责人的文件
3. ❌ **不要改 `simulation/px4_gazebo/`** —— 仿真负责人的文件
4. ❌ **不要改 `frontend/swarm-console/`** —— 前端负责人的文件
5. ❌ **不要 `pkill` / `killall`** —— harness 靠进程身份校验，手工杀会让状态变孤儿，之后 `stop` 会拒绝发信号（`stale_state`）
6. ❌ **不要对残留状态跑 `stop_three_uav.sh`** —— 它会抛错。直接 `start` 会自己清
7. ❌ **不要把 DEMO 大屏当作实时数据演示**
8. ❌ **不要用 `wsl -u root`** —— 本机默认用户是 `zyq`，`/root` 下没有 PX4 也没有 pymavlink
9. ❌ **不要用 `python3 -m http.server 5179` 起三维** —— 本地用 `npm run dev`
10. ❌ **不要去 weier 上部署** —— 本机联调通过之前不上机

---

# 十二、交付物

## 必交

1. **一张"什么是真的"表**（第十节，逐项填：真实/剧本/设计稿/未接）
2. **每个任务的一行结论**：通过 / 不通过 / 卡在哪
3. **任务 6 的关键证据**：换两次不同输入，贴出两次返回的差异（证明它真的读输入框）
4. **失败项的现场材料**：日志最后 20 行、或截图、或 curl 输出

## 报告里必须写清的一句话

> 完整链路「任务书 → 算法生成分工/航线 → 仿真执行 → 首页进度同步」**是否已贯通**。
> 如果没有，缺的是哪一环。

---

# 十三、一个参考：这台机器的三个已修坑（别再排查一遍）

| 坑 | 现象 | 根因 | 已修成 |
|---|---|---|---|
| 1 | PX4 启动即退出，`return value: 15` | `build/px4_sitl_default/etc/` 缺 `parameters.bson` | 从 `rootfs/` 拷了两份 |
| 2 | PX4 只吐 2 行就僵住，Gazebo 里永远没模型 | **cwd 在 `/mnt/d`（9p）上 IO 卡死** | `.runtime` → 软链接到 ext4 |
| 3 | C 盘只剩 13 GB，找不到大文件 | WSL 的 `ext4.vhdx` 73 GB 在 `AppData\Local\Packages\...`，且删文件不缩容 | `wsl --manage Ubuntu --move D:\wsl\Ubuntu` |

**第 2 条是最隐蔽的**：同一套环境变量，cwd 在 `/tmp` 时 9 秒出模型，在 `/mnt/d` 时 30 秒不动。
