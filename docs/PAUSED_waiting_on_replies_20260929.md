# 等待回复：当前暂停点与恢复入口

**状态**：⏸ **暂停中**——等系统集成负责人与算法负责人回复后继续
**日期**：2026-09-29
**暂停时 Runtime 提交**：`989a62e`（已全部推送，工作区干净，无进程在跑）

本文件的作用：把"在等什么、回复后做什么、哪些不用等"写成一份不依赖对话上下文的记录，
免得恢复时重新梳理。

---

## 一、在等两份回复

### 回复 1 —— 系统集成负责人

**文件**：`docs/OPEN_vehicle_capability_semantics_ownership.md`
**性质**：**定责请求**（不是数据请求）

要裁定的四个问题：

| | 问题 | 我方建议 |
| --- | --- | --- |
| Q1 | 四类能力数据（真机续航/速度、仿真值、载荷、允许与否）各自归谁？ | 从文件现状推测分属机型/采购、仿真、载荷、Policy 四方，**但我方无权确定** |
| Q2 | 仿真值与真机值什么关系？不一致以谁为准？ | 至少要求**显式标注来源** |
| Q3 | "保证/有条件/禁止"三态语义由谁定义？ | 建议沿用动作注册表已有的 `not_implemented` / `not_supported` 区分 |
| **Q4** | **过渡期是否允许算法侧基于显式假设推进？** | **允许，但要求显式标注假设；禁止写入完成证据；涉及安全的判断不得仅基于假设** |

**Q4 是最急的一条**——不定，算法侧无法对任何含感知的任务做判断。

### 回复 2 —— 算法负责人

**文件**：`docs/algorithm_side_next_steps_20260929.md`
**性质**：任务说明 + 数据交接

要求他们交付三件：

1. **从 `objective` 生成 `tasks[]` 的最小可运行实现**（他们文档第 1 节的核心诉求）
2. **一份面向 `simple_recon_v0_1` 的可执行提案**（`scene_id` 对齐、只含 TAKEOFF/GOTO/LAND）
3. **对多机协同时序接口三个问题的答复**（该接口目前完全不存在）

我方在文档里已回答他们提出的四个问题（§6）。

---

## 二、回复到达后的动作

### 若算法侧交回提案

```bash
# 1) 用真实转换器过一遍（拒绝时会指出具体 task/action/waypoint）
python D:/2026UAVSwarm-worktrees/_ops/run-converter-flight.py --context <他们的提案>
```

> `run-converter-flight.py` **默认只转换与校验，不提交**。
> 真飞必须显式加 `--execute`。（这条安全默认是一次教训换来的：
> 早先版本提交是无条件的，`--dry-run` 只跳过了提示语，结果飞机真的飞了。）

**在我方确认"可以真飞"之前，只做转换与校验，不提交。**

### 若集成负责人对 Q4 给出裁定

按裁定更新 `docs/OPEN_vehicle_capability_semantics_ownership.md` 与
`docs/algorithm_side_next_steps_20260929.md` 的对应段落，并把结论同步给算法侧。

### 若 Q1/Q2/Q3 有结论

能力语义如需要接入执行链路，参照已实现的场景身份校验
（`src/uav_runtime/http/routes.py` 的 `_check_plan_scene_identity`）——
同样是"执行前核对、不一致则拒绝整份计划"的位置与方式。

---

## 三、**不需要等回复就能做的**（若想继续推进）

| 项 | 说明 | 风险 |
| --- | --- | --- |
| **修三维视图默认场景** | 已诊断完，**改法 A 只要两行**（默认从 `city` 改为 `recon`）。**这是当前最影响可用性的问题**——不修则界面上看不到飞机 | 低，但不碰对齐判据 |
| **阶段 3.2 撞墙测试** | 验证物理世界真的有碰撞体（飞机撞楼被挡） | 需人在场 |
| 转换器接 CLI/HTTP | 算法侧目前可直接 import，不算卡住 | 低 |
| 阶段 1.4 带 GUI 目视核对 | 受渲染性能限制（集显 + Mesa 翻译层） | 低 |

### 关于三维视图默认场景（唯一待决策的代码改动）

**问题**：`index.html` 的 `<select id="scene-select">` 无 `selected` 属性，
`city`（青岚市）是第一个选项 → 浏览器默认选它。而 Runtime 报的是
`simple_recon_v0_1` → 每次对齐失败 → 载具被丢弃。

```
sceneId   : "city"
connection: "stale"
alignment : [{ id: "UAV-01", aligned: false, reason: "scene_id 不匹配", position: null }]
```

**方案 A（推荐）**：默认改为 `recon`。`main.js:245` 的 `activeSceneId = "city"`
与 `index.html` 的选项默认值各改一处。

**附加建议**（无论选哪个方案）：当 Runtime 场景与当前视图不匹配时**显示明确提示**，
而不是像现在这样静默丢弃、只表现为 "3 STALE"——**静默丢弃正是这个问题难以发现的原因。**

**这一步涉及"场景是否可信"的展示逻辑，与"不放宽对齐判据"是同一敏感区域，故未擅自改动。**

---

## 四、当前系统状态（暂停时）

| | 状态 |
| --- | --- |
| 进程 | **全部已停**（PX4 0 / Gazebo 0 / Runtime 0，端口 5178、5179、8765 全空闲） |
| 仓库 | `main` = `989a62e`，**0 未推送**，工作区干净（仅审计日志与算法侧 `INTELLIGENCE_HANDOFF/` 未跟踪） |
| 测试基线 | Python **560 passed, 6 skipped**；三维视图 **68**；控制台 **34**；集成 **6** |
| 三台飞机 | 上次运行时全部在地面、未解锁 |

### 手动重启顺序（**顺序不能错**）

```bash
# ① 仿真 + Runtime（会自动等 harness 状态文件出现）
bash /mnt/d/2026UAVSwarm-worktrees/_ops/ops.sh start

# ② 标定 —— 必须在 ① 成功之后
bash /mnt/d/2026UAVSwarm-worktrees/_ops/ops.sh calib-once   # 先试一次
bash /mnt/d/2026UAVSwarm-worktrees/_ops/ops.sh calib-loop   # 确认能成再开循环
```

```powershell
# ③④ 前端（Windows，两个窗口）
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d ; npm run dev
cd D:\2026UAVSwarm ; python -m http.server 5178 --directory frontend\swarm-console
```

**Edge 需 `Ctrl+Shift+R` 强刷**（无版本号的 `app.js` / `styles.css` 会被长缓存）。

### 已知会误导人的现象

| 现象 | 真相 |
| --- | --- |
| 标定报 `calibration_process_missing` | **仿真没起**，不是 Runtime 的问题。该错误来自 `calibration.py:65`：按 `node_id` 在 `.runtime/px4_gazebo/harness_state.json` 里找不到记录，而该文件由仿真启动时写出、停止时消失 |
| `ops.sh start` 报"仅 2/3 连接" | **会自动重启 Runtime 重试**，通常随后 3/3。不要手动干预 |
| 界面上看不到飞机 | 除标定过期外，还可能是**三维视图默认场景不匹配**（见第三节） |

---

## 五、本次会话的完整提交清单（`524cdf8` → `989a62e`，14 个）

### 前端
- `b2f0882` 修 iframe 每次 render 被重建；双向选择同步
- `b44f46c` **修我方引入的布局回归**（`ensureShell` 破坏 CSS 网格）；选择同步改为可自动测
- `ca57eda` 去掉 `<header>` 套 `<header>` 的冗余嵌套；新增真实系统健康检查

### 仿真
- `cbcf565` 城市街区导入 Gazebo（12 栋楼，含碰撞体）
- `bb110fe` 修地面只有 ±50 m 导致楼悬在虚空；降低 GUI 渲染负担
- `ddeb581` 记录两个 WSL 渲染坑（GUI 卡顿根因、孤儿窗口）

### Runtime / 契约 / 工具
- `b12d037` **实现 `scene_id` / `map_version` 校验**
- `4f17927` 契约文档更新
- `3e8d841` **proposal → plan 转换器**
- `2742b87` **跨语言闭环测试**（JS 转换器 → Python 契约）
- `fcd4310` 端到端真飞验证记录
- `91baafc` 城市导入与场景对齐待办
- `60d6e68` 给算法侧的任务说明与数据交接
- `989a62e` 载具能力语义定责

### 已验证的关键结果

- **闭环真飞**：转换器 3 步 → Runtime `completed` → UAV-01 落在 `N=59.2 E=12.0`
  （目标 60/12，**误差 0.8 m**）
- **场景校验**：`scene_id_mismatch`，`step_outcomes: []`（**未执行任何一步**）
- **城市导入**：`gz model --list` 含 `city-block-4-3`
- **选择同步**：双向 + 不成环，3 条自动化用例通过

---

## 六、附：我方在这轮工作中犯的错（记录以免重犯）

| 错误 | 教训 |
| --- | --- |
| `--dry-run` 没阻止执行 → **飞机真飞了** | 会让飞机起飞的动作，"演练"必须是默认、"真飞"必须显式 |
| `ensureShell()` 破坏 CSS 网格 → **用户截图报告整页错位** | 改共享渲染路径后必须在真实浏览器里看一眼，不能只跑单测 |
| `ensureShell()` 读 `dataset` → 打挂 12 个既有单测 | 用 `git stash` 对比基线才确认是自己引入的 |
| 判定"跨域下选择同步测不了"并留下 fixme | **判断错了**，`frameLocator` / `page.frame()` 可以读子框架 |
| 手写测试夹具缺契约字段（先缺 `source` 再缺 `frame`） | 夹具应从真实系统抓取，不要手写 |
| **用 PowerShell 改源文件三次搞坏编码/BOM** | 改源文件用编辑工具，不要用 `Set-Content` |

---

## 七、相关文档索引

| 用途 | 位置 |
| --- | --- |
| 给算法侧的任务说明 | `docs/algorithm_side_next_steps_20260929.md` |
| 能力语义定责（等回复） | `docs/OPEN_vehicle_capability_semantics_ownership.md` |
| 执行契约 | `docs/algorithm_runtime_execution_contract_v0_1.md` |
| 城市世界现状与待办 | `docs/TODO_city_world_import.md` |
| 运行手册（**在仓库外，不受版本管理**） | `D:\2026UAVSwarm-worktrees\_ops\MANUAL_STARTUP.md` |
| 三维视图两个渲染坑 | `docs/simulation/PX4_GAZEBO_3UAV_RUNBOOK_ZH-CN.md` |
