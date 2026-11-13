## 零、组合版本已固定（2026-11-13 补记）

### 结论

**三条 demo 线可以干净合并，合并后全量测试全绿。** 已固化为可复现版本：

| 项 | 值 |
|---|---|
| 分支 | **`integration/demo-20261113`** |
| 提交 | `421aa27`（合并提交） |
| **标签** | **`demo-20261113`**（annotated tag，指向 `174fdc0`） |
| 基线 | `main` `d60f74f` |
| 相对 main 的变化 | **34 files changed, +3340 −322** |

### 三条线的组成

| PR | 分支 | 提交 | 内容 |
|---|---|---|---|
| **#98** | `codex/simulation-demo-readiness` | `914b042` | 三机飞行验证、`area_coverage.py`、起停可靠性 |
| **#99** | `codex/runtime-demo-readiness` | `74750f1` | 链路评分、演习注入（`http/demo.py`）、任务进度（`http/mission_progress.py`）、失败归因 |
| **#100** | `codex/frontend-demo-readiness` | `3d5d5e4` | 主控台 F1~F7（`mission-dashboard.js`）+ LIVE 舞台与双面板修复 |

> **注意**：`3d5d5e4` 比 #100 描述里写的 `ee75534` **更新一个提交**（`expose LIVE stage and prevent twin panel overlap`）。合并时用的是分支最新 HEAD，不是 PR 描述里的提交。

### 实测依据

1. **目录完全不重叠** —— 这是能干净合并的根本原因：
   - #98 → `simulation/`、`scenarios/`、`docs/simulation/`
   - #99 → `src/uav_runtime/`、`docs/fixtures/`
   - #100 → `frontend/swarm-console/`
2. **依次 `merge --no-ff` 零冲突**
3. **合并后全量 `pytest`：936 passed, 12 skipped, 0 failed**（225 秒）

### ⚠️ 明确排除：#97

`codex/runtime-platform-autonomy`（`8d94a80`）**不在本版本内**，原因：

| 指标 | #97 | 三条 demo 线 |
|---|---|---|
| 分叉点 | `6fe7057` | `bb24e38` |
| 落后 main | **23 个提交** | 2 个提交 |
| 自身提交数 | **10 个** | 1~2 个 |
| 内容 | 平台侧持久任务服务、UAV-02 机载 Runtime、本地模型接入、MAVLink 健康修复 | demo 接口与展示 |

**#97 是"飞机能自己执行"的基础**（机载 Runtime / 持久任务 / 模型接入），
而 **#99 不含它**，所以 #99 的降级处置只能"模拟"。

**这直接决定了"方案 A vs B"的性质**：
- 方案 A（模拟 + 标演习）= 现有三条线就能做，零额外合并风险
- 方案 B（真停）**不是改几行代码，而是要合并 #97** —— 落后 23 个提交，风险完全不同

### 怎么用这个版本

```bash
git fetch origin --tags
git checkout demo-20261113
```

**以后所有演示都从这个 tag 起**，不要用浮动分支。

---

# 三线联合验收计划（demo readiness）

**日期**：2026-11-13
**状态**：三份交付全部 Draft，均未合并
**目标**：把三条线固定成一个可复现的组合版本，在 weier 上用**真实 SITL** 走完 11 步演示链

---

## 一、三份交付的现状

| 线 | PR | 提交 | 分支 | 交付内容 | 已验证 | **未验证** |
|---|---|---|---|---|---|---|
| 仿真 | **#98** | `914b042` | （见 PR） | S1~S4 | 本机 Windows：111 定向测试；Cesium 坐标与布局 16 项；静态坐标对齐 | **三机起飞/航点/悬停/返航/降落**、**真实三机起停复验** |
| Runtime | **#99** | `74750f1` | `codex/runtime-demo-readiness` | R1~R5 | 全量 935 passed / 7 skipped；接固定 #98 后演示专项 19 passed | **真实链路评分**、**飞行中的进度增长**、双前端联合显示 |
| 主控台 | **#100** | `ee75534` | （见 PR） | F1~F7 | 114 项前端测试；浏览器 DEMO 三分钟自动播完；隔离 Runtime HTTP 联调 | **LIVE 三机任务进度**、**真实链路变化** |

**共同结论**：三份都在"离线/单点"层面验证过，**没有一份在真实 PX4 + Gazebo + 双前端同时在线的条件下验证过**。

---

## 二、五个必须先拍板的风险（建议在对齐会上一次解决）

> **编号以本节标题为准。** 沟通中曾按不同顺序提过，下表是当前状态，别只看编号。

| # | 风险 | 状态 |
|---|---|---|
| 1 | 内存（WSL 默认 8 GB 上限） | 🚨 待处理（今天就该做） |
| 2 | 降级处置是"模拟执行"，与"三机真能飞"口径不一致 | ⏳ **待三方拍板**（话术见本节末尾） |
| 3 | 主控台地图把「覆盖分布」标为"未知" | ⏳ 待定（可补数据或改话术） |
| 4 | 未提交的脏分支（1332 行） | ✅ **已解决** —— 主控台 `ee75534` 已推送、工作树干净 |
| 5 | 三条线都是 Draft，组合从未验证 | 🚨 待处理（本次验收的全部意义） |

### 风险 1 🚨 内存：仿真侧已经明确报了"内存不足"

> 原文："本机 Windows 可用内存实测 **0.89-2.50 GiB，低于此前三机相机版启动时观察到的内存增量**"

**这是最可能让现场验收直接失败的一项。**

**原因分析（大概率）**
weier 有 **63.6 GB** 物理内存，但 **WSL2 在 Windows 10 19041 上的默认上限是
`min(物理内存 50%, 8 GB)` = **8 GB**。而三机 + Gazebo 相机版渲染需要更多。
仿真负责人看到的 0.89~2.50 GiB 很可能就是 WSL 里剩下的。

**立刻要做（5 分钟，在 weier 上）**

Windows 侧，新建/编辑 `C:\Users\<你的用户名>\.wslconfig`：

```ini
[wsl2]
memory=48GB
processors=12
swap=8GB
```

然后：
```powershell
wsl --shutdown
wsl -d Ubuntu
```

WSL 里确认：
```bash
free -h
nproc
```
**必须看到** `Mem: 47Gi` 左右、`nproc` = 12。

> 如果 `free -h` 里 total 还是 8 GB 左右，说明 `.wslconfig` 没生效
> （文件名必须是 `.wslconfig`，注意前面有个点；改完必须 `wsl --shutdown`）。

**验收标准**：三机 + Gazebo 跑起来后，`free -h` 的 available 仍 > 4 GiB。

---

### 风险 2 🚨 Runtime 的"降级处置"是**模拟执行**，不发飞控指令

> 原文："降级后经 Policy Gate 触发**模拟** HOLD、返航和重分配，**不发送飞控指令**"

**这本身是合理且安全的设计**（演示时不会真让飞机乱动），但必须解决一个问题：

**仿真说"三机真能飞"，Runtime 说"降级处置是模拟的" —— 那演示时观众看到的是什么？**

| 场景 | 飞机实际行为 | 前端显示 |
|---|---|---|
| 注入 `link_degraded=18` | ？ | 显示 HOLD / 返航 / 重分配 |

**三种可能的约定，必须选一个并写进演示话术：**

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **A（推荐）** | 注入后 **模拟处置**（飞机继续按原航点飞），前端明确标 `SIMULATED` | 安全、可复现 | 观众可能问"为什么它没动" |
| **B** | 注入后**真的发 hold-position**，飞机真的停 | 最有说服力 | 需要 R3 从"模拟"改成"真实下发"，风险上升 |
| **C** | 注入后只显示判定，**不做任何执行** | 最保守 | 演示没高潮 |

**建议选 A**，但在横幅和审计里都标`演习/SIMULATED`，并在演示话术里明说：
> "这一步是演习：策略判定和审计是真实的，执行动作被标记为演习，不会真的改飞行计划。"

**要拍板的事**：这个 `SIMULATED` 标记，前端现在有没有？没有就补一个字段。

---

#### 风险 2 的拍板话术（**可直接复制发给三位负责人**）

> 三位负责人，有一个演示口径需要今天定下来，麻烦各自回一句"同意 + 工期"或提出异议。
>
> 背景：仿真线（#98）已经把三机的起飞爬升和水平位移做成可观测的真实数据（航点、悬停、
> 返航、降落待现场验收）；Runtime 线（#99）的 R2/R3 是"演习注入默认关闭，降级后经
> Policy Gate 触发**模拟** HOLD、返航和重分配，**不发送飞控指令**"。这两件事本身都对，
> 但放在同一次演示里会出现一个观众必然会指出的问题：前端横幅写着"UAV-02 已 HOLD"，
> 三维里那架飞机却还在按原航点飞。
>
> 建议统一按 A 方案执行：**保留模拟执行，但在三个地方显式标"演习"** ——
> ① Runtime 在 `policy_decision_event` 和 `action_result` 的审计字段里带一个可机读标记
> （`simulated: true` 或既有等价字段，命名由你们定，只要一处定义、全链一致）；
> ② 主控台横幅与审计详情里显示"演习 / SIMULATED"，不要和真实执行混在一起；
> ③ 演示话术统一成"策略判定与审计是真实的，执行动作被标记为演习，不会改变真实飞行计划"。
> 这样既不引入真实下发的现场风险，也不会让观众产生误解。
>
> 不选"改成真实下发"的理由：R3 这套已通过 935 项回归；改成真实下发要重走安全路径，
> 且演示中一旦真实 hold 触发、飞机停半空，现场不可控。
>
> 需要三位各回一句：
> **仿真线** —— 降级期间不干预飞行（各自按航点继续）这个前提你认可吗；
> **Runtime 线** —— 审计里补 `simulated` 标记需要多久；
> **主控台线** —— 横幅和审计详情显示"演习"需要多久。

---

### 风险 3 ⚠️ 主控台地图把「覆盖分布」标为"未知"

> 原文："当前 Runtime 提供区域边界和覆盖面积汇总，**地图将覆盖分布标为未知**"

**这个做法是对的**（诚实，符合 F7 精神），但演示时观众会问："这块为什么是灰的？"

**两个选择**：
- **补数据**：Runtime 提供覆盖**网格**或**已飞足迹多边形集合**，前端画出来
  （仿真侧 S3 说"重叠足迹只计一次，结果为几何估计" —— 说明足迹数据是有的，只是没暴露）
- **改话术**：明说"区域级汇总已完成，栅格级覆盖分布下一阶段"

**建议**：让 Runtime 把已有的足迹暴露成多边形列表（接口层面很小），
前端能画就画，画不了再降级。**这是演示观感提升性价比很高的一项。**

---

### 风险 4 ⚠️ 有一个未提交的分支，1332 行脏改动

> 原文："已暂停，未提交的改动保留在 `codex/frontend-demo-readiness`"

**必须先处置**，否则：
- 后面谁在 weier 上切分支，可能切到带脏改动的版本
- 演示前查版本会对不上

**处置建议**：
```bash
# 在那边机器上
git -C <repo> branch --show-current        # 确认是 codex/frontend-demo-readiness
git -C <repo> status --short | head -20
```
判定：**内容已包含在 `ee75534` 里 → 丢弃**；**有独有内容 → 单独开 PR**。
**不要留在工作区。**

---

### 风险 5 ⚠️ 三条线都是 Draft，组合未验证过

三位各自的测试都绿，但：
- Runtime 的 fixture 是基于"固定 #98 源码"
- 前端是"隔离 Runtime HTTP"
- 仿真只在静态层面验了坐标

**"各自通过" ≠ "组合通过"。** 这是本次验收的全部意义。

---

## 三、固定三线组合版本（具体做法）

### 3.1 取三条 PR 的 head，合成一个集成分支

```bash
cd /root/uavswarm        # 或你本机的仓库

git fetch origin main
git fetch origin pull/98/head:pr-98
git fetch origin pull/99/head:pr-99
git fetch origin pull/100/head:pr-100

# 从 main 开集成分支
git checkout -b integration/demo-20261113 origin/main

# 依次合入（顺序：协议层优先 → 执行层 → 展示层）
git merge --no-ff pr-99  -m "integration: runtime demo readiness (#99)"
git merge --no-ff pr-98  -m "integration: simulation demo readiness (#98)"
git merge --no-ff pr-100 -m "integration: console demo readiness (#100)"
```

> **顺序理由**：Runtime 定义接口契约 → 仿真提供数据源 → 前端消费。
> 按这个顺序合，冲突最少、语义最清楚。

### 3.2 合并后立刻做的三项检查

```bash
# ① 契约一致：前端要的字段，Runtime 给了吗
python3 -c "import json,glob
for f in glob.glob('docs/contracts/*.json'):
    print(' ', f)"

# ② 全量回归（三条线的测试都要过）
PYTHONPATH="$PWD/src" /usr/bin/python3 -m pytest -q

# ③ 前端自带测试
cd frontend/swarm-console && node --test tests/*.test.js 2>/dev/null | tail -5
```

**全部通过才进入现场验收。** 有失败就停下，定位是哪条线的问题。

### 3.3 打标签（重要）

```bash
git tag -a demo-20261113 -m "demo readiness: #98 + #99 + #100 组合版本"
git log --oneline -5
```

**以后所有演示都从 `demo-20261113` 这个 tag 起**，不再用浮动分支。

---

## 四、weier 现场联合验收（按顺序做，不跳步）

### 4.0 前置检查（不做完别开始）

```bash
# ① 内存（见风险 1）
free -h

# ② 版本正确
cd /root/uavswarm && git describe --tags && git log --oneline -1

# ③ 依赖齐
python3 -c "import importlib.util as u; print('pymavlink', u.find_spec('pymavlink') is not None)"
gz sim --versions
ls -lh /root/PX4-Autopilot/build/px4_sitl_default/bin/px4
```

**必须全绿**：`Mem` total ≥ 40 GiB、tag 是 `demo-20261113`、`pymavlink True`、`gz 8.15.x`、px4 56 MB。

### 4.1 起四件套（4 个终端）

```bash
# 终端 1：三机仿真
cd /root/uavswarm && bash simulation/px4_gazebo/scripts/start_three_uav.sh \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json --gui

# 终端 2：Runtime
cd /root/uavswarm && PYTHONPATH="$PWD/src" /usr/bin/python3 -m uav_runtime.http.server

# 终端 3：主控台
cd /root/uavswarm/frontend/swarm-console && python3 -m http.server 5178 --bind 0.0.0.0

# 终端 4：三维（必须用反代）
cd /root/uavswarm && python3 /mnt/d/weier-offline/serve_3d_proxy.py \
  --dir frontend/swarm-console/simulation-3d/dist
```

### 4.2 逐条验收（11 条，每条都要记录"通过/不通过/现象"）

| # | 验收项 | 怎么验 | 期望 | 归属 |
|---|---|---|---|---|
| **1** | 三机起飞 | 主控台点起飞（或 `cli smoke-takeoff`） | Gazebo 里三架离地，终端出现 `arm`/`takeoff` 日志 | 仿真 |
| **2** | **位置真的在变** | 间隔 3 秒两次 `curl -s .../api/telemetry/latest \| grep local_position` | 两次 `x/y/z` **不同** | 仿真 |
| **3** | 地图有任务区 | 看主控台首屏 | 出现任务区多边形 + 三机进度 | 前端 |
| **4** | 完成度在涨 | 观察 60 秒 | 百分比单调增长（允许平台期） | Runtime+前端 |
| **5** | 链路质量有数 | 看降级大屏 | 80~100 之间波动 | Runtime |
| **6** | 注入降级 | 点注入（或 `curl -X POST .../api/demo/inject`） | 链路质量 3 秒内掉到注入值，变红 | Runtime |
| **7** | **系统自己处置** | **不做任何操作**，等 10 秒 | 出现 policy 决策（规则名可见）+ 横幅 | Runtime |
| **8** | **处置标记为演习** | 看横幅/审计 | 明确标 `SIMULATED` / `演习`（见风险 2） | Runtime+前端 |
| **9** | 时间轴有降级节点 | 看时间轴 | 黄色节点出现，可点开看 JSON | 前端 |
| **10** | 恢复 | 点清除注入 | 链路质量恢复，蓝色节点出现 | Runtime+前端 |
| **11** | 审计可重建 | 打开 Audit·Replay | 整条链按时间排出来 | 前端 |

### 4.3 还要验的三件"容易漏"

| 项 | 怎么验 | 为什么重要 |
|---|---|---|
| **双前端同时在线** | 5178 和 5179 同时开，都看得到三机 | 三位都说"双前端联合显示未验" |
| **三维位置和 Gazebo 对得上** | Gazebo 挪一架，看三维里方向/距离 | S2 只做了静态坐标验证 |
| **停干净** | `stop_three_uav.sh` 后 `ss -lunp` | S4 说"真实三机起停待复验" |

```bash
# 停干净检查
bash simulation/px4_gazebo/scripts/stop_three_uav.sh
ss -lunp | grep -E '1454|1458' || echo "✅ 端口已释放"
pgrep -fa 'bin/px4|gz sim' || echo "✅ 进程已退"
```

---

## 五、责任分工与产出

| 事项 | 谁做 | 产出 |
|---|---|---|
| 风险 1 内存配置 | 现场负责人（你） | `free -h` 截图 showing ≥40 GiB |
| 风险 2 SIMULATED 标记 | Runtime（加字段）+ 前端（显示） | 横幅上可见"演习" |
| 风险 3 覆盖分布 | Runtime 暴露足迹多边形（可选）+ 前端画 | 地图上不再是"未知" |
| 风险 4 脏分支处置 | 前端负责人 | 分支清空或单独 PR |
| 风险 5 组合版本 | 你（或我） | `demo-20261113` tag |
| 11 条验收 | 现场 | 一张打勾表 + 每条的现象记录 |

---

## 六、建议的时间顺序

```
今天      风险 1（内存）+ 风险 4（脏分支）—— 两个都是 5~10 分钟的事
今天      风险 2 拍板（SIMULATED 怎么标）
明天上午   固定组合版本 + 三项合并检查（3.2）
明天下午   11 条现场验收
不通过项   分回各线修，修完重新打 tag
```

**风险 1 和 4 不解决，明天下午的验收会白跑。**

---

## 七、一句话总结

> 三份交付的质量看起来是够的（测试都过、契约都给了）。
> **现在缺的不是代码，是一次"真的同时跑起来"的验证。**
> 而这次验证的两个前置条件 —— **WSL 内存** 和 **组合版本** —— 都不是代码问题，
> 是今天就能搞定的准备动作。
