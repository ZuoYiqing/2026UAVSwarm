# 《2026UAVSwarm_本对话研发历史与关键决策归档》

**性质**：原始研究资料（供大型总报告取材），不是最终正文。
**范围**：仅归档**本对话实际发生**的研究、讨论、设计决策与工程开发，不复述仓库全部代码历史。
**编制时间**：2026-10-26
**证据基线**：`main` @ `d3f0268`

---

## 0. 阅读须知：标注体系与可信度分级

本文严格区分五类信息，**任何一条都带标注**：

| 标注 | 含义 |
| --- | --- |
| **【用户决定】** | 用户明确提出或确认的决策 |
| **【用户原话】** | 直接引用，不改写 |
| **【助手建议·未确认】** | 助手提出但用户未确认 / 未采纳 |
| **【已实现】** | 代码或文档已落库，有 commit 可查 |
| **【已实测】** | 有执行输出、截屏或实测数据佐证 |
| **【未实现】** | 仅讨论、设计或计划 |
| **【待核】** | 无法从现有证据确定，需人工核实 |

**来源可信度**：

| 等级 | 含义 |
| --- | --- |
| ⭐⭐⭐ | 实测输出 / git 记录 / 用户明确确认 |
| ⭐⭐ | 二手转述（他人报告），未复核 |
| ⭐ | 推测或回忆，标注【待核】 |

**⚠️ 特别提醒（一个哈希陷阱，供后续核对者参考）**：
本项目 4 个 tag 中，后 3 个是 **annotated tag**，`git for-each-ref %(objectname)` 得到的是**标签对象**，
与 `git rev-parse <tag>^{commit}` 得到的**提交哈希不同**：

| tag | 标签对象 | **实际 commit** | commit 日期 |
| --- | --- | --- | --- |
| `v0.1-contract-skeleton-pass` | f52c4ff（轻量标签，同 commit） | **f52c4ff** | 2026-03-16 |
| `v0.1-four-module-integrated-pass` | fabdf4d | **bfa75e8** | 2026-10-09 |
| `v0.1.1-rooftop-landing-corrected` | ee0c4ed | **8717c25** | 2026-10-10 |
| `v0.1.2-rooftop-and-return-home-verified` | 2463a76 | **ea4bf62** | 2026-10-12 |

`README.md` 中记录的是 commit 哈希（正确）。若用 `for-each-ref` 复核会得出不同值，**不是 README 写错**。

---

## 1. 时间线

### 1.1 可确定日期（git 实证，⭐⭐⭐）

| 日期 | 事件 | 证据 |
| --- | --- | --- |
| **2026-03-16** | 契约冻结里程碑 `v0.1-contract-skeleton-pass` | tag → f52c4ff |
| **2026-10-05** | `ops/ops.sh`（22 KB，最早的运维入口） | 文件时间戳 |
| **2026-10-09** | 四模块打通里程碑 `v0.1-four-module-integrated-pass` | tag → bfa75e8 |
| **2026-10-09** | 返航→降落交接文档、启动手册 | `ops/HANDOFF_return_home_then_land.md`、`ops/MANUAL_STARTUP.md` |
| **2026-10-10** | 屋顶着陆修正 `v0.1.1-rooftop-landing-corrected` | tag → 8717c25 |
| **2026-10-10** | `system_status.py`（一条命令六项证据体检） | 提交 8717c25 标题 |
| **2026-10-10** | 着陆点三方讨论记录、PR#88 集成侧复核 | `ops/LANDING_SITE_THREE_WAY_DISCUSSION.md`、`ops/REVIEW_PR88_integration_side.md` |
| **2026-10-10** | 致 Runtime 的"解耦地面参考"消息 | `ops/MSG_to_runtime_decouple_ground_reference.md` |
| **2026-10-11** | #91/#92/#88 合并就绪评估 | `ops/MERGE_READINESS_91_92_88.md` |
| **2026-10-12** | 屋顶+返航双验证里程碑 `v0.1.2-...` | tag → ea4bf62 |
| **2026-10-12** | UAV-02 实飞验收原始记录 | `ops/ACCEPTANCE_UAV02_FLIGHT_20261012.md` |
| **2026-10-12** | B-0/8/30 秒预检验收 | `ops/ACCEPTANCE_B_0_8_30_RESULT.md` |
| **2026-10-16 11:14** | 离线迁移方案文档（第一版） | `ops/MIGRATION_OFFLINE_20261014.md` |
| **2026-10-16 22:36** | 勘察脚本加入"能力评级"（§11） | 提交 357c051 |
| **2026-10-18 11:25** | 新增 `recon-vehicle.sh`；Windows 脚本加评级 | 提交 d89a9ec |
| **2026-10-18 22:22** | **README 全量重写**（纠正"MVP Skeleton"过期描述） | 提交 e586a5f |
| **2026-10-19 23:27** | 按手绘稿重绘分层堆叠架构图 | 提交 b1c7fe2 |
| **2026-10-19**（日期来自文件名） | 离线环境验收记录（中间笔记本） | `ops/OFFLINE_ACCEPTANCE_20261019.md` |
| **2026-10-20 10:07** | 该验收记录入库 | 提交 1b18aab |
| **2026-10-20 10:50** | 记录 Runtime 负责人复核意见 + 无硬件演示 | 提交 6fe7057 |
| **2026-10-21 15:34 / 15:43** | UGV 跑 `recon-offline-env.sh` / `recon-vehicle.sh` | `UGV.txt` 内嵌时间 |
| **2026-10-21 23:59** | lab403（zhangliang）跑 `recon-offline-env.sh` | `zhangliang.txt` 内嵌时间 |
| **2026-10-22 15:26** | 修 `recon-windows.ps1` 三处缺陷 | 提交 0e51c01 |
| **2026-10-23 09:13** | 给厂家的技术确认清单 | 提交 92e8085 |
| **2026-10-23 12:07** | UGV 装 Runtime 指南（含厂家答复） | 提交 dcc64c0 |
| **2026-10-23 17:23** | UGV 环境详情汇总文档 | 提交 94fccb6 |
| **2026-10-23 21:27** | 可直接粘贴的厂家微信消息 | 提交 12e301a |
| **2026-10-26 16:53** | 修正包名 `tqr`→`iqr` | 提交 d3f0268 |

### 1.2 无法确定日期（标【待核】）

| 事项 | 状态 |
| --- | --- |
| 本对话最初的几轮（四模块联调、真机控制尝试）具体日期 | **【待核】** 对话未留时间戳 |
| `weier.txt` 的采集时间 | **【待核 / 矛盾】** 报告内嵌 `2026-11-16 16:37`，但该报告暴露的 Store-stub bug 已于 2026-10-22 修复；且 11-16 晚于本归档编制日。**可能是目标机时钟不准，或报告来自另一次采集** |
| PR #88 / #91 / #92 的实际合并日期 | **【待核】** 已知合并**顺序**（#92 → #88），具体日期未在本对话确认 |
| 中间笔记本（Win10 1909）的 recon 采集日期 | **【待核】** 早于本归档，具体日期未记录 |
| 第三批离线包（便携 Python 等）是否已制作 | **【未实现】** 仅提议 |

### 1.3 阶段划分（按事件性质，不严格按日期）

```
阶段 A  四模块集成与真机控制探索
阶段 B  语义缺陷发现与修正（屋顶着陆 / 返航到达）—— 本项目最重要的技术转折
阶段 C  着陆点信任与三方讨论、L2 复核记录、澄清通道
阶段 D  合并就绪与工作区对齐（#92 → #88）
阶段 E  离线/断网迁移准备（三批离线包）
阶段 F  架构图重绘与 README 现状纠正
阶段 G  现场环境勘察（三份 recon）与脚本缺陷修正
阶段 H  UGV 真实接口确认（厂家）与 Runtime 上车的可行性分析
阶段 I  本归档
```

---

## 2. 最初目标（对话起点）

### 2.1 用户最初诉求【用户决定】

四条被用户明确表达或反复强调的诉求，按出现顺序：

1. **把四模块集成起来并在本地跑通**：PX4/Gazebo 仿真 + Runtime + 前端（主控台/三维）。
2. **真机（真无人机）控制** —— 从仿真走到真实无人机。
3. **让助手"不要擅自接管"** —— 用户多次纠正助手越界行为（下详 §9.1）。
4. 后期扩展为：**把整套系统搬进无网/断网的无人车现场环境**。

### 2.2 当时的架构构想【已实现，有代码】

```
控制台 / Agent  →  Runtime  →  Policy Gate  →  每机长期 MAVLink session  →  PX4 飞控
                    └→ 审计 JSONL  →  回放
```

**关键设计意图**（早期即确立，后被反复验证为正确）：

| 原则 | 内容 |
| --- | --- |
| P1 | **LLM/Agent 不直接输出飞控协议帧**，只产生结构化 `ActionRequest` |
| P2 | **控制面与执行面分离**：policy 判"能否执行"，adapter 做"如何执行" |
| P3 | **`unified_policy_gate` 是唯一裁决入口**，输出标准化 `PolicyDecisionEnvelope` |
| P4 | **canonical `protocol_json` 为契约主入口**，legacy alias 仅迁移兼容 |
| P5 | **`AdapterGateway` 统一**：幂等检查、命令构造、结果归一化 |
| P6 | **审计 + 回放**：关键决策写 JSONL，可复盘 |

### 2.3 起点时仓库的真实状态 vs 文档自述（**第一个重要认知落差**）

| | 仓库实际 | 旧 README 自述 |
| --- | --- | --- |
| README 标题 | — | `UAV Runtime (MVP Skeleton)` |
| MAVLink 后端 | **真实**：`px4_sitl_backend.py` 973 行、`mavlink_backend_session.py` 2067 行、`px4_telemetry.py` 454 行，均 `import pymavlink` | "MavlinkAdapter 提供**未接入状态 stub**，尚未接真实 SITL/PX4" |
| 技能 | 6 个动作端点已实现且实飞调用过 | "takeoff/land/goto 等**占位技能**" |
| 包数 | 17 个子包 | 只列 6 个 |
| 阶段 | `v0.1.2-rooftop-and-return-home-verified` | "MVP skeleton / contract-freeze early stage" |

> **这条落差的后果**：会让人严重低估完成度，也会让人误判"哪些能力可以依赖"。**直接触发了 §3 的思想变化 M1。**

---

## 3. 重要思想变化（关键认识转折）

### M1　「文档自述严重滞后于实际实现」【用户决定 → 已实现】

* **触发**：【用户原话】"仓库当前的 README 仍然以'MVP Skeleton'、Fake Adapter 等早期状态为主要描述。它未必准确反映现在所有模块的实际完成情况，你改一下"
* **认识**：**项目的自我认知（README）与工程现实脱节**。不是代码落后，是描述落后。
* **动作**：README 全量重写（128 行删 / 224 行增），并按"每一条标注证据来源"的写法组织。
* **衍生要求**：**必须先区分"跑通过"与"没验过"**，否则文档仍是误导。

### M2　⭐「报成功但与事实不符」是本项目最核心的一类缺陷【用户 + 三方共识 → 已实现并实飞验证】

* **认识转折**：早期关注点是"动作能不能执行"；后期转为 **"动作完成后，系统宣称的结论是否与物理事实一致"**。
* **两处具体缺陷**：
  1. **屋顶着陆误报**：飞机落在屋顶，系统却按"已落地"报成功 → 修正为必须满足 `landed + disarmed + scene ground error ≤ 0.3 m + ≥3 样本 + ≥0.5 s`
  2. **返航到达误报**：仅凭"距离在缩小"就判"已到达" → 修正为必须有 `arrived_at_home` + 容差内样本数
* **为什么必须改架构**：**"进度"不等于"到达"**。原判据（`min_progress_m 5.0`）在正常返航中**必然会通过**，因此**原判据无法证伪**——这是判据设计的根本缺陷，不是阈值调参问题。
* **验证方式**：设计了一个"旧判据也会通过"的实验（起点距 home **6.751 m**，`distance_reduction_m 6.547`），从而证明新判据不是靠"距离缩小"而是靠 `arrival_samples 10` 落在 0.75 m 容差内。【已实测】

### M3　⭐静态几何证据**不能**挂 TTL，必须按版本绑定【已实现】

* **教训来源**：曾把地面/站点几何挂在 **5 秒** health TTL 上 → 导致 `/api/preflight` 只在 5 秒窗口内可用（`valid_for_ms≈4913`）。
* **修正原则**：
  * **静态几何**：按 **`world_sha256` + `map_version`** 绑定，**不随时间失效**
  * **"当前是否允许"**：才用 TTL（标定 ≈60 s，`valid_for_ms≈59885`）
* **一句话**：**"地图是什么"不该过期；"现在能不能动"才该过期。**

### M4　ROS 不在控制链路上（来自 Runtime 负责人）【外部输入 → 已接受】

* **原设想**：真实无人机侧可能经 ROS 接入。
* **Runtime 负责人明确**：控制链路是 `Agent → Runtime → Policy Gate → 每机长期 MAVLink session → PX4`，
  **ROS 不在其中**；ROS 仅作为未来机载感知的候选。
* **推论**：**adapter 层是后端无关的** —— 换成 ROS 后端是"新增一个同形状后端"，不是重写；Runtime 核心（Policy / 动作生命周期 / 审计 / HTTP）与后端无关。
* **⭐ 这条推论在阶段 H 直接救了工期**（见 M9）。

### M5　前端"实时交互"≠"直接用返回的 JSON 画界面"【用户提问触发】

* **用户疑问**："前端不是实时跟 runtime 交互的吗"（针对 `console-model.js` 37 KB 的作用）
* **实测澄清**：前端确实实时交互，但是**轮询**（`setInterval` **2000 ms** 同步状态、**5000 ms** 同步事件），不是推送。
* **为什么必须有 `console-model.js` 这一层**：
  1. **一次刷新要合并多个接口**，且字段结构不同（关键例：`/api/vehicle-snapshot` 的 `telemetry` 只有 6 个键，**没有位置/高度**；`/api/telemetry/latest` 才有完整 `local_position`）
  2. 原始数据不能直接显示（派生"能不能点这个按钮"、动作状态归一化、过期判定）
  3. 还需**反方向构造请求**（`buildRuntimeRequest`）并与三维 iframe 通信（`createVehicleSnapshotMessage`）
* **附带结论（对总报告有长期价值）**：`console-model.js` **不含一行 DOM 代码**，因此若前端换技术栈，该层可基本原样复用。

### M6　无硬件也能验证 Runtime 的"价值"，但要分清价值与能力【已实测】

* **认识**：部署成功（进程起来、HTTP 通）**不等于**系统有效果。
* **发现**：Runtime 的**治理链路**可用 CLI 在**零硬件**条件下验证，且策略门**真的会拒绝**（详见 §5.6、§6.6）。
* **同时划清边界**：该路径 `adapter: "fake"`、`detail: "simulated"`，**没有真机动作**；它证明治理链路，不证明飞行能力。

### M7　"全是脚本"会剥夺人的独立工作能力【用户原话，重要】

* **【用户原话】**："你也告诉我命令吧，全是脚本以后我没法一个人工作了"
* **认识**：交付物如果只有脚本，**现场排障能力归零**（人不知道脚本里做了什么，无法改、无法定位）。
* **行动**：此后所有交付改为 **"命令为主 + 脚本为辅"**：先给可手敲的命令并解释每一段做什么，脚本仅作便利封装且**附上其内部命令**。

### M8　`node_modules` 与 Python 包**平台相关**，离线包必须按平台分装【已实测】

* **实测证据**：本项目 `node_modules` 仅含 `@rollup/rollup-win32-x64-*`、`@esbuild/win32-x64` → **Linux 上不可用**。
* **推论**：**在 Windows 上构建一次，`dist/` 是平台无关的静态产物**，可拷到任何机器 serve。这是"离线只需 Python + 浏览器，不需要 Node"的依据。

### M9　⭐UGV 不是"能跑 MAVLink 的地面版无人机"【厂家答复推翻原假设】

* **原假设**：真机走**数传 / 串口 / UDP 的 MAVLink**，只需配地址与核验 `sysid/compid`。
* **实测推翻**：UGV 的 `can0` 活跃（500 kbps，抓到 `241/253/254/251/252/221/311` 帧，`0x241` 末字节递增）→ 一度判断"车控走 CAN，Runtime 接不上"。
* **厂家最终澄清**：**"底盘驱动把 CAN 封装了，直接发 topic 就行"**，控制接口是 **ROS `/cmd_vel`**。
* **结果**：**不需要碰 CAN 协议**，但**需要新增 ROS 适配层**，且动作语义要重新定义（见 §4.5）。

### M10　"帮助文档写错一处哈希/名字，会浪费对方一整轮工作"【自查发现】

* **实例**：助手从屏幕照片把 `iqr_robot_bringup` 误读为 `tqr_robot_bringup`，并把这条写进 4 份文档、还把"核实 iqr/tqr"当成开放问题交给用户。
* **【用户确认】**："是 iqr，你识别的问题，截图里面也是 iqr"
* **修正**：4 份文档 14 处全部改正（提交 d3f0268），仅保留一处"已排除的疑问"说明曾误读。
* **教训**：**从照片 OCR 得到的技术标识符，必须标注为"待核实"，不能当作事实写进对外文档。**

---

## 4. 关键技术决策

### 4.1 已确立（【用户决定】或三方共识，且有代码/文档支撑）

| # | 决策 | 状态 | 依据 |
| --- | --- | --- | --- |
| D1 | 控制链路**不含 ROS**，走 MAVLink | 【已实现】 | Runtime 负责人陈述；现有 16 个 adapter 文件 |
| D2 | **adapter 层后端无关**，ROS 只是"另一种同形状后端" | 【已实现（作为设计原则）】 | 同上；`adapters/base.py` 抽象 |
| D3 | 静态几何证据**按版本绑定**，不设 TTL | 【已实现】 | `state_store.py:663 ground_landing_context()` 读 `_ground_reference_binding`，只校验 `_source_fresh(calibration)` |
| D4 | 落地完成判据：`landed + disarmed + scene ground err ≤0.3 m + ≥3 样本 + ≥0.5 s` | 【已实现 + 已实测】 | 实测 `vertical_error_m 0.009510`、`on_scene_ground true`、5 样本/550 ms |
| D5 | 缺证据时 **fail-closed**（返回 `ground_reference_unavailable`，`completion_state unknown`），但**如实记录物理事实** | 【已实现 + 已实测】 | 同一次验收里 `physical_landed_disarmed true` 而 `completion_reached false` |
| D6 | 返航到达判据：**必须** `arrived_at_home` + 容差内样本，**不得**用"距离缩小"代替 | 【已实现 + 已实测】 | `arrival_samples 10`、0.75 m 容差；对照实验见 M2 |
| D7 | HOME / RTL 目标必须交叉核验 | 【已实现 + 已实测】 | `home_evidence.verification = global_local_xy_crosscheck`（误差 **9.4 mm**）、`rtl_type 0`、`rally_points 0` |
| D8 | 前端为**纯静态**，目标机只需 Python + 浏览器，**不需要 Node** | 【已实现 + 已实测】 | `package.json: dev = python -m http.server 5178`；`dist/index.html` 用 `./assets/` 相对路径 |
| D9 | 审计文件**不该进 git**（会无限增长、把他人历史带给新部署） | **【助手建议·未确认】** | 实测 `audit/runtime.audit.jsonl` 被跟踪，752 行 / 788 KB，`.gitignore` 未含；中间笔记本因此看到他人历史 |
| D10 | `.sh` 必须 LF（仓库加 `.gitattributes`：`*.sh text eol=lf`，**不做全库 renormalize**） | 【已实现】 | 提交 1113617；两次实测踩坑 |
| D11 | 交付以**命令**为主、脚本为辅 | 【用户决定】 | §3 M7 用户原话 |
| D12 | 不擅自修改 Runtime / 前端 / 仿真业务代码 | 【用户决定】 | 用户多次明确；助手多次请示后才改为"只记录、不改" |

### 4.2 被放弃 / 搁置 / 替代的方案

| 方案 | 结局 | 原因 |
| --- | --- | --- |
| 把静态几何挂在 health TTL 上 | **放弃** | 导致 preflight 只有 5 秒窗口（M3） |
| 用"距离缩小"作为返航到达判据 | **放弃** | 该判据在正常返航中必然通过，**无法证伪**（M2） |
| 用垂直起飞验证 `return_home` | **放弃** | 垂直起飞水平位移为零，会让返航测试**空洞通过** |
| 直接写 CAN adapter 控制 UGV | **放弃（暂无必要）** | 厂家确认驱动已封装 CAN，走 `/cmd_vel` |
| 在 Runtime 内 `import rospy` | **不可行** | Runtime 需 Python ≥3.10，ROS Noetic 的 rospy 是 3.8（**硬冲突**） |
| 在离线 Linux 上从零 `apt` 装 PX4+Gazebo | **不推荐（搁置）** | apt 依赖树过大；改推"先联网装一次"或"Docker 镜像搬迁" |
| 给 UGV 打 aarch64 便携 Python 包 | **取消** | 用户告知 UGV 能联网 → 可直接 `deadsnakes` 装 |
| 用 `--no-deps` 下 Python 轮子 | **放弃（已犯并修正）** | 漏了 `pymavlink` 的依赖 `fastcrc`，现场安装失败 |

### 4.3 Runtime 10053 缺陷：三条修复约束（来自 Runtime 负责人复核）【外部输入，已记录】

负责人复核结论：**根因判断正确，缺陷归属 Runtime，当前未修复**；补丁方向对**但不完整**，给出三条约束：

1. **必须覆盖完整响应发送过程** —— 不能只保护 `wfile.write(body)`；响应头、响应体、以及 400/500/OPTIONS 都可能遇到断连（现场 traceback 里 `flush_headers` 就抛了同一个异常）。
2. **异常处理必须限定在 HTTP 读写处** —— 不能用宽泛 `except` 吞掉执行器内部连接故障；`dispatch()` 会走到 adapter/MAVLink 会话，那里的连接异常**可能是"飞控连接断了"这种真实故障**，静默忽略会丢失策略与审计的关键信号；**真正的服务端错误必须保留**。
3. ⚠️ **「请求丢失、前端重试」只适用于查询请求** ——
   * **查询**：响应丢失 = 没拿到数据，重试无副作用
   * **动作**：**响应丢失 ≠ 动作未发生**，动作可能已执行；**不得据此重发**，应通过**原 `request_id` 查询**或**幂等重试**
   * 原表述是对动作请求的**错误口径**，已按此纠正

**状态**：本条为【外部输入】+【未实现（未修复）】。本次对话**未提交任何 Runtime 代码改动**。

### 4.4 现场环境事实对部署决策的影响

| 事实 | 决策影响 |
| --- | --- |
| **无一台 Linux 机器有 Python ≥3.10**（UGV 3.8.10/3.9.5；lab403 3.8.10 且无 pip；weier 无 Python） | Runtime 目前只能跑在**中间笔记本**（3.13.9）；其余需装新解释器 |
| weier 有 **RTX 3080 / 64 GB**（WMI + nvidia-smi 双源一致） | 离线环境**唯一**可作仿真主机的机器；但它是 Windows 且无 WSL/Python |
| lab403 为 **GT 730**、无独显 | 【用户确认】"几乎可以说是没有" → **不作仿真主机**，定位为前端显示 + Runtime + 存储 |
| UGV 根分区在 eMMC 仅剩 **24 GB**，而 **477 GB NVMe 未挂载** | 建议日志/数据放 NVMe；但**必须先查里面有无数据** |
| UGV `eth2` 无 IPv4 且重启需重配 | 需固定 IP 或用热点 |

### 4.5 ⚠️ 尚待定义：地面车动作集合（【未实现】，阻塞项）

即使有了 `/cmd_vel`，**动作语义对不上**：

| Runtime 动作 | 无人机含义 | 地面车（Scout 2.0）怎么办 |
| --- | --- | --- |
| `takeoff` | 起飞 | **无意义**（或映射为解锁/驻车释放） |
| `land` | 降落 | **无意义**（或映射为驻车/急停） |
| `goto` | 飞到坐标 | 需**闭环导航**（或交 `move_base`） |
| `hold_position` | 悬停 | ✅ `cmd_vel` 全零 |
| `return_home` | RTL 回起飞点 | 需自记起点 + 闭环 |
| `reduce_speed` | 降速 | ✅ **语义天然匹配** |
| `maintain_heading` | 保持航向 | ✅ **语义天然匹配** |

**结论**：这是**设计问题**，需与 Runtime 负责人共同定义，**不是写个 adapter 就完**。

---

## 5. 工程开发过程

### 5.1 本次对话期间产生的提交（完整列表，⭐⭐⭐）

| # | commit | 日期 | 类型 | 内容 |
| --- | --- | --- | --- | --- |
| 1 | `357c051` | 2026-10-16 | feat | `recon-offline-env.sh` 增加能力评级与建议用途（§11） |
| 2 | `d89a9ec` | 2026-10-18 | feat | 新增 `recon-vehicle.sh`；`recon-windows.ps1` 加评级 |
| 3 | `e586a5f` | 2026-10-18 | docs | **README 全量重写**（+224 / −128） |
| 4 | `b1c7fe2` | 2026-10-19 | docs | 按手绘稿重绘分层架构（svg + png + md） |
| 5 | `1b18aab` | 2026-10-20 | ops | 离线环境验收记录入库 |
| 6 | `6fe7057` | 2026-10-20 | ops | 记录 Runtime 负责人复核 + 无硬件 Runtime 演示 |
| 7 | `0e51c01` | 2026-10-22 | fix | `recon-windows.ps1` 三处缺陷 |
| 8 | `92e8085` | 2026-10-23 | ops | 给厂家的技术确认清单 |
| 9 | `dcc64c0` | 2026-10-23 | ops | 厂家答复记录 + UGV 装 Runtime 指南 |
| 10 | `94fccb6` | 2026-10-23 | ops | UGV 环境详情汇总 |
| 11 | `12e301a` | 2026-10-23 | ops | 可直接粘贴的厂家微信消息 |
| 12 | `d3f0268` | 2026-10-26 | fix | 包名 `tqr` → `iqr`（4 文档 14 处） |

> 注：`12e301a` 的 commit 日期为 2026-10-23 21:27，但文档文件名标注 20261022（厂家答复当日），二者差异为**文件命名日 vs 提交日**，非矛盾。

### 5.2 主要新增/修改文件

| 文件 | 大小 | 性质 |
| --- | --- | --- |
| `README.md` | 14,215 B / 289 行 | **完全重写**（原 193 行 / 7,416 B，含"MVP Skeleton"过期描述） |
| `ops/architecture-stack.svg` | 9,551 B | 新增（纯文本矢量源，可改） |
| `ops/architecture-stack.png` | 188,542 B | 新增（Edge headless 渲染） |
| `docs/architecture_stack_layered.md` | 5,086 B | 新增（Mermaid + 逐层对照 + 待确认清单） |
| `ops/OFFLINE_ACCEPTANCE_20261019.md` | 13,932 B | 新增（验收记录 + 缺陷分析 + 负责人复核 + 无硬件演示） |
| `ops/UGV_ENVIRONMENT_20261022.md` | 16,562 B / 419 行 | 新增（UGV 环境**唯一声明来源**） |
| `ops/UGV_RUNTIME_INSTALL_GUIDE_20261022.md` | 8,848 B | 新增（手敲命令 + 卡点归属） |
| `ops/VENDOR_QUESTIONS_UGV_20261022.md` | 4,532 B | 新增（给厂家的确认清单） |
| `ops/VENDOR_MESSAGE_UGV_20261022.md` | 3,689 B | 新增（微信可粘贴版，含极简版） |
| `ops/recon-windows.ps1` | 17,918 B | **修 3 处缺陷** |
| `ops/recon-offline-env.sh` | 11,399 B | 加 §11 能力评级 |
| `ops/recon-vehicle.sh` | 7,829 B | **新增**（10 节：磁盘/NVMe、Python、ROS、工作空间、CAN、网络、串口、现有资产、远程/显示） |

### 5.3 关键脚本的设计要点

**`ops/system_status.py`（2026-10-10 引入，早于本对话但被反复引用）**
* 一条命令查**六项独立证据**：进程 / 仿真时钟推进 / 三台遥测 / Runtime / 标定 / manifest 是否相机版
* **为什么不数进程**：本项目两次被"进程数正常"证伪 —— ① Gazebo 掉了但 PX4 还在；② 起的是默认版而非相机版
* 退出码 0/1/2

**`ops/recon-offline-env.sh`（11 节）**
* 第 2 节 Python、第 5 节磁盘、第 6 节 WSL、**第 11 节能力评级**（供拍照带回）
* 含 **WSL 守卫**：在 WSL 里跑会拒绝下结论，并提示改用 `recon-windows.ps1`（因 WSL 会误判自身 RAM/浏览器）

**`ops/recon-windows.ps1`（15,746 → 17,918 B）**
* 刻意**全 ASCII**（中文 Windows 下 PowerShell 5 按 GBK 读取 UTF-8 脚本会乱码并破坏 `-f` 格式化）
* `wsl -l -v` 输出为 UTF-16，需 `cmd /c` + 去 `\0`

### 5.4 离线交付包（Batch 1 / Batch 2）

**Batch 1**：`D:\offline-batch1.tar.gz` — **10.90 MB / 451 文件**
```
recon/{recon-offline-env.sh, recon-vehicle.sh, recon-windows.ps1}
frontend/swarm-console/{index.html, app.js(113 KB), console-model.js(37 KB),
                        runtime-api.js, styles.css, package.json}
frontend/swarm-console/simulation-3d/src/    ← 16 文件 0.15 MB
frontend/swarm-console/simulation-3d/dist/   ← 422 文件 18.7 MB
00-START-HERE.md
```
**关键发现**：`app.js:612` 硬依赖 `simulation-3d/src/vehicle-contract.js`（`import("./simulation-3d/src/vehicle-contract.js")`），
因此**不能只拷主控台的几个文件**；同时必须排除 `simulation-3d/node_modules`（237.7 MB / 10,033 文件）。
`dist/index.html` 使用 `./assets/` **相对路径** → 可从任意目录 serve。【已实测】

**Batch 2（方案 C）**：`D:\offline-batch2\` — **186.56 MB / 5 卷**
```
00-START-HERE.md                          13.6 KB
01-source.tar.gz                          10.94 MB   全量 git 跟踪源码（518 项）
02-frontend-3d-dist.tar.gz                10.78 MB   构建好的三维（422 项）
03-frontend-3d-node_modules-WIN.tar.gz    54.15 MB   仅 Windows（esbuild/rollup win32 二进制）
04-wheelhouse.tar.gz                      74.70 MB   27 个轮子（6 平台 × pymavlink/fastcrc/lxml）
05-node-v24.22.0-win-x64.zip              35.99 MB   便携 Node
helpers/{0-STEP-BY-STEP.txt, 1..4-*.bat, show-audit.py}
```

**明确排除**（均有理由）：`.runtime/`（1,587 MB，仿真 ULog 产物）、`.git/`（40.6 MB）、
算法模型权重（~3.8 GB，且与 arm64 不通用）。

### 5.5 测试基线【已实测】

```
python -m pytest -q   →   917 passed, 6 skipped, 0 failed   (102.91 s)
```
（2026-10-19 实测，本机 WSL Ubuntu 22.04 / Python 3.10.12）

### 5.6 无硬件 Runtime 演示（【已实测】，开发机 WSL）

| 命令 | 结果 |
| --- | --- |
| `list-capabilities` | 返回 16 个动作的能力注册表（`risk_level`、`allowed_link_states`、`policy_default`、`supported_adapters` 等） |
| `submit-action takeoff`（默认 stub） | `decision_code: allow`、`adapter: "fake"`、`code: "exec_ok"` |
| `submit-action land --demo-link-state lost` | **`decision_code: deny`**、**`status: blocked`**、**`adapter: ""`**、`primary_reason_code: REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED`、`secondary: REASON_CODE_LINK_LOST_SCOPE_RESTRICTED` |
| `submit-action goto --demo-link-state lost` | 同上（`deny` / `blocked`） |
| 审计落盘 | 每次动作产生 2 行：`policy_decision_event` + `action_result`；拒绝时 `audit_tags: ["policy","deny","link_lost","fallback_required"]` |
| `replay-last` | 可回放 |

**⭐ 关键证据**：被拒绝时 `adapter` 字段为**空字符串** —— 证明命令**一步都没走到执行层**。若策略门是摆设，此处应出现 `"mavlink"`。

**真 PX4 实飞路径（历史记录，10-09）记录 6 条事件**：
`action_request` → `policy_decision_event` → `adapter_execution_started` → `adapter_execution_result` → `http_land` → `action_result`
→ **真机路径的审计密度显著高于 fake 路径**。

### 5.7 中间笔记本（离线现场）实机验证【已实测，用户截屏为证】

| 验证项 | 结果 |
| --- | --- |
| `01-source` 解压正确 | ✅ `D:\uavswarm` 下 `src\` `frontend\` `ops\` `config\` 齐全 |
| pymavlink 离线安装 | ✅ `Successfully installed fastcrc-0.5.0 lxml-6.1.3 pymavlink-2.4.50` |
| pymavlink 导入 | ✅ `python -c "import pymavlink,fastcrc,lxml.etree"` → `ok` |
| Runtime 启动 | ✅ `uav_runtime_http_bridge listening on http://127.0.0.1:8765/api` |
| 主控台 5178 显示 | ✅ |
| **三维 5179 渲染** | ✅ **在 Intel UHD 620 + 2018-02-28 驱动的纯核显机器上渲染成功** |
| 5178→8765 跨域 | ✅ `ALLOWED_ORIGINS` 已含 `http://127.0.0.1:5178` |
| 策略门拒绝（在中间笔记本复现） | ✅ `deny` / `blocked` / `adapter: ""` |

> **一个重要的预期修正**：此前把"三维渲染"列为**最大技术风险点**（担心核显驱动太旧），
> **实测证明可接受**（流畅度未量化）。

---

## 6. 技术问题与修正

### 6.1 WinError 10053 traceback（Runtime 缺陷，未修复）

**现象**：Runtime 运行期间关闭/刷新前端，控制台刷出成对 traceback：

```
File "...\http\server.py", line 59, in _handle_json_request
    self._send_json(status, payload)
File "...\http\server.py", line 83, in _send_json
    self.wfile.write(body)
ConnectionAbortedError: [WinError 10053] 你的主机中的软件中止了一个已建立的连接。

During handling of the above exception, another exception occurred:

File "...\http\server.py", line 63, in _handle_json_request
    self._send_json(500, {"error": "internal_error", ...})
File "...\http\server.py", line 81, in _send_json
    self.end_headers()
ConnectionAbortedError: [WinError 10053]
```

**根因（已定位到三行）**：`except Exception` 把"客户端断开"当成"服务端内部错误"，
于是**往一个已断开的连接上再写一次 500**，产生二次失败。

```python
try:
    status, payload = dispatch(...)
    self._send_json(status, payload)          # 第 59 行：客户端已断开 → 抛 10053
except json.JSONDecodeError:
    self._send_json(400, ...)
except Exception as exc:
    self._send_json(500, {"error": "internal_error", ...})   # 第 63 行：再往死 socket 写
```

**触发条件（很日常）**：前端每 2 s 轮询、单次超时 **2.5 s**（`health: () => request("/health", { timeoutMs: 2500 })`），
关闭/刷新页面时浏览器 `AbortController` 掐断在途请求。

**影响**：服务器**不崩**（`ThreadingHTTPServer`）；查询请求丢失后可重试；
但**日志污染严重，真正的 500 会被淹没**。

**当前状态**：**未修复**。归属 `src/uav_runtime/`（Runtime 负责人）。
负责人已给出三条修复约束（§4.3）。本仓库**未提交任何 Runtime 代码改动**。

### 6.2 `recon-windows.ps1` 三处缺陷（**由真实报告暴露，已修**）

| # | 缺陷 | 现场表现 |
| --- | --- | --- |
| 1 | **Microsoft Store 的假 `python.exe` 被当成真 Python 调用** | weier 报告里整段错误文本被写进输出：`Python was not found but can be installed from the Microsoft Store... 所在位置 D:\zyq\recon-windows.ps1:39` |
| 2 | **能力评级对 "serve the frontends" 判错** | 一台**没有任何解释器**的机器上打出 `[YES] serve the frontends -- python -m http.server works` |
| 3 | **浏览器检测漏判** | 三个浏览器全 NOT FOUND（Win10 通常自带 Edge） |

**修法**：
1. 路径命中 `\WindowsApps\` 时标为 `STUB ... NOT a real python` 并**不再调用**；版本探测改走 `cmd /c "... --version 2>nul"`，避免失败解释器往报告灌 stderr
2. 判据改为要求真实解释器（`$pyMajor -ge 3`），并**区分两个门槛**：能起前端（3.8 即可）vs 能跑 Runtime（需 ≥3.10）
3. 补 per-user 安装路径、`ProgramFiles(x86)` 分支，加注册表 `App Paths` 与 `WindowsApps` 兜底

**验证**：PowerShell 解析器语法 OK；文件 17,918 B、纯 LF、无 BOM、**非 ASCII 字节 0**；本机实跑正确识别 3 个真 Python 与 msedge/chrome。

### 6.3 `pymavlink` 依赖漏包（**已犯并修正**）

* **错误做法**：用 `pip download --no-deps` 只下 `pymavlink` 本体
* **现场报错**：`ERROR: Could not find a version that satisfies the requirement fastcrc`
* **根因**：`pymavlink → fastcrc`（CRC 计算，必需）、`→ lxml`（日志解析）
* **隐蔽性**：`lxml` 未报错是因为目标机 anaconda 里**已有** `lxml 5.3.0`，侥幸掩盖了一半问题
* **修正**：改 `--only-binary=:all:`（不带 `--no-deps`），生成 6 平台 × 3 包 = **27 个轮子**
* **验证**：新建干净 venv，`pip install --no-index --find-links=wheelhouse` 成功，`pymavlink/fastcrc/lxml.etree` 全部导入 OK，`MAVLink_home_position_message.fieldnames[:6]` 返回 `['latitude','longitude','altitude','x','y','z']`

### 6.4 `--find-links` 相对路径陷阱（现场踩坑）

```cmd
:: ❌ 已 cd 进 wheelhouse，还写 --find-links=wheelhouse → 找 wheelhouse\wheelhouse → "Location ignored"
:: ✅ 已在该目录内：--find-links=.
:: ✅ 在上一级：    --find-links=wheelhouse
```

### 6.5 cmd.exe vs PowerShell vs Bash 语法混用（现场连续踩坑）

| 用户敲的 | 错误 | 正确（cmd） |
| --- | --- | --- |
| `python3 -m http.server` | `'python3' 不是内部或外部命令` | `python` |
| `... &` | cmd 无后台运算符 | 新开窗口 |
| `$env:PYTHONPATH = "$PWD\src"` | `文件名、目录名或卷标语法不正确` | `set PYTHONPATH=%CD%\src` |
| `ls` | `'ls' 不是内部或外部命令` | `dir` |
| 漏 `set` 那步 | `ModuleNotFoundError: No module named 'uav_runtime'` | 两条必须按序 |

**改进**：所有交付文档改为**每条命令分 cmd / Bash 两版**，并在开头放"确认你在哪个 shell"对照表；
另做 4 个 `.bat` 便利封装（纯 ASCII + CRLF，含前置条件检查）。

### 6.6 工具与文件编码类问题（多次踩坑，已形成规避规则）

| 问题 | 根因 | 规则 |
| --- | --- | --- |
| `.sh` 报 `set: pipefail: invalid option name` | 工作区 `.sh` 为 CRLF | 仓库加 `.gitattributes`；`tr -d '\r'` |
| PowerShell 脚本里中文变乱码 / `-f` 格式化崩溃 | **PowerShell 5 在中文 Windows 下按 GBK 读取 UTF-8 的 `.ps1`** | **`.ps1` 必须纯 ASCII**；中文写入用 write 工具 |
| `[System.Text.Encoding]::UTF8.GetBytes(<中文>)` 抛 `Cannot find an overload` | 同上，CJK 字面量被当 GBK 解码 | 避免在 `.ps1` 内嵌中文 |
| 用 `ASCIIEncoding` 转 CRLF 导致**中文被整体丢弃** | 编码不匹配 | 转行尾必须**显式 UTF-8 解码 → 改行尾 → UTF-8 编码** |
| `git commit -m "<多行中文>"` 失败 | PowerShell 解析 | 写消息到文件，用 `git commit -F` |
| 提交信息里的 `$(rospack ...)` 被吞 | PowerShell 命令替换 | 同上，用 `-F` 文件 |
| `$PID` / `$home` 只读 | PowerShell 自动变量 | 改名（`$procId` 等） |
| `.NET` 方法用 `ReadAllBytes('相对路径')` 失败 | **`[System.IO.File]` 用进程工作目录，不是 PowerShell 的 `cd`** | 一律用绝对路径 |
| `Get-ChildItem -Include` 无 `-Recurse` 时失效 | PowerShell 语义 | 用 `-Filter` 或加 `-Recurse` |
| `pgrep -cf "bin/px4"` 计数虚高 | 自匹配自身命令行 | 用 `ss` / `Get-NetTCPConnection` |
| `for-each-ref %(objectname)` ≠ tag 的 commit | annotated tag 有独立对象 | 用 `git rev-parse <tag>^{commit}` |

### 6.7 早期已撤回的错误结论（诚实记录）

| 曾经的错误说法 | 实际情况 | 处理 |
| --- | --- | --- |
| `HOME_POSITION.local_x/y/z` | 真实字段是 `x/y/z` | 已在文档中撤回 |
| "HOME == spawn" | **该结论无效** —— 相对间距无法排除共同偏移 | 已撤回；改用 `global_local_xy_crosscheck` 交叉核验（9.4 mm） |
| RTF 0.18 归因于性能不足 | 实际是**缺少 `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA`**（0.175 → 0.84~0.94） | 已纠正，并写入 README 与 runbook |
| `iqr_robot_bringup` 读作 `tqr_robot_bringup` | **是 `iqr`**（用户确认） | 提交 d3f0268 修正 4 份文档 |

### 6.8 未诊断的遗留问题

| 问题 | 状态 |
| --- | --- |
| `goto` 到达异常：`min_error_m 2.911` → `last_error_m 36.971` | **原因未定**【未实现】**不阻塞**（但系统诚实报了 `timed_out`） |
| 三维视图在低端显卡上的**流畅度** | 未量化（只知"能显示"） |
| weier 报告时间的矛盾（2026-11-16） | 【待核】 |

---

## 7. 科研成果

### 7.1 必须如实说明的前提

**本对话范围内没有形成、也没有讨论过任何论文投稿、专利申请或正式科研成果登记。**
本节只记录**具备科研价值的技术结论与可提炼的课题**，并严格区分"已实证"与"构想"。

### 7.2 已取得实证支撑的技术结论（可作为论文/专利素材）【已实测】

| # | 结论 | 支撑证据 |
| --- | --- | --- |
| R1 | **"完成判据必须可证伪"** —— 用"进度"代替"到达"的判据在正常工况下必然通过，因此无法区分成功与失败 | 返航对照实验：旧判据（`min_progress_m 5.0`）在 `distance_reduction_m 6.547` 时必然通过；新判据靠 `arrival_samples 10` 才成立 |
| R2 | **静态环境证据应按版本绑定而非时间过期**；只有"当前是否允许"才该 TTL | 5 s TTL 使 preflight 只有 5 s 窗口；改为 `world_sha256 + map_version` 后解除 |
| R3 | **缺证据时必须 fail-closed，但同时如实记录物理事实**（"落了地"与"完成了任务"必须分开陈述） | `ground_reference_unavailable` + `completion_state unknown` 同时 `physical_landed_disarmed true` |
| R4 | **执行层不可见性是治理有效性的直接证据** —— 用"适配器是否被调用"区分"策略拒绝"与"执行失败" | 拒绝时 `adapter: ""`；允许时 `adapter: "fake"/"mavlink"` |
| R5 | **审计密度反映执行路径深度** —— fake 路径 2 条事件，真 PX4 路径 6 条事件 | 历史审计记录对照 |
| R6 | **地面/空中载体的动作语义不可直接迁移**：`takeoff/land` 对地面车无意义，`hold/reduce_speed/maintain_heading` 天然匹配 | 能力注册表与 `/cmd_vel` 语义对照 |
| R7 | **平台相关性会隐性阻碍离线迁移**：`node_modules` 含平台二进制，`dist/` 平台无关 | `@rollup/rollup-win32-x64-*`、`@esbuild/win32-x64` 实测 |

### 7.3 可提炼的科学问题（【助手建议·未确认】）

| # | 问题 |
| --- | --- |
| Q1 | **执行完成性的可证伪判据设计**：如何在仅有部分可观测证据时，给出"完成/未完成/无法判定"三态输出，且保证判据本身可被反例推翻 |
| Q2 | **证据时效的分离理论**：把"环境静态描述"与"操作许可"分成两个独立的失效模型，其正确性条件是什么 |
| Q3 | **异构载体的动作语义映射**：空中/地面/水面在"位移—姿态—驻留"维度上的最小充分动作集 |
| Q4 | **无人系统控制面的可追溯性度量**：以审计事件覆盖度、拒绝可解释率、适配器可见性为指标 |
| Q5 | **断网环境下的可验证部署**：如何在没有包管理与网络的环境里，保证"装上去的东西 = 验证过的东西"（哈希绑定、平台矩阵、依赖闭包） |

### 7.4 现有能力清单（供报告"成果"章引用，均有代码或实测）

* **17 个子包 / 13,554 行 Python** Runtime，**零第三方核心依赖**（`dependencies = []`）
* **16 个 adapter 文件**，其中真实后端：`px4_sitl_backend.py`(973)、`mavlink_backend_session.py`(2067)、`px4_telemetry.py`(454)
* **27 个 HTTP 路由**（含 6 个动作端点：`takeoff` / `smoke-takeoff` / `land` / `goto` / `hold-position` / `return-home`）
* **能力注册表 16 个动作**，含 `risk_level` / `allowed_link_states` / `policy_default` / `requires_confirmation_by_default`
* **917 passed / 6 skipped** 测试基线
* 4 个版本里程碑 tag
* 三机 SITL（含相机版 manifest）+ 十个运维脚本 + 一个六项证据体检器

---

## 8. 未完成事项

### 8.1 仅为讨论 / 设计（【未实现】）

| 项 | 说明 |
| --- | --- |
| **地面车动作集合** | 需与 Runtime 负责人共同定义（§4.5） |
| **ROS `/cmd_vel` 适配层** | 三个方案（A 中继节点 / B rosbridge / C subprocess），**推荐 A**，均未实现 |
| **便携 Python 三平台包** | 曾提议，后因 UGV 能联网而**部分取消**；lab403/weier 仍需 |
| **审计文件移出 git** | 【助手建议·未确认】 |
| **`--skip-can` 开关** | 曾提议给 `recon-vehicle.sh` 加，未确认 |
| **速度类动作映射** | `reduce_speed` / `maintain_heading` 已在能力注册表，但**未映射到任何真实 adapter**（`supported_adapters: []`） |

### 8.2 已实现但**未验证**

| 项 | 状态 |
| --- | --- |
| `03-frontend-3d-node_modules-WIN.tar.gz` 能否成功重建前端 | **未实测**（`npm run build` 路径未跑过） |
| `05-node` 便携 Node 在目标机可用性 | **未实测**（仅验证 zip 结构完整、`node.exe` 89.5 MB 存在） |
| lab403 / weier 上的 Runtime 或前端 | **未实测**（环境尚未具备 Python ≥3.10） |
| 三维视图在低端显卡的帧率 | **未量化** |
| 审计文件被 git 跟踪的后果（多机历史混杂） | **已观察到现象**，未做修复验证 |

### 8.3 已有实测证据（可直接引用）

* 中间笔记本：pymavlink 安装、Runtime 启动、5178 显示、**5179 渲染**、跨域可用、策略门拒绝 —— **全部有截屏或控制台输出**
* 开发机：917 passed / 6 skipped；无硬件 CLI 演示的六类输出；`fastcrc` 补包后的干净 venv 安装
* UAV-02 实飞：落地判据（`vertical_error_m 0.009510`）、返航到达（`initial_distance_m 6.751` / `arrival_samples 10`）、HOME 交叉核验（9.4 mm）、三机隔离（01/03 `armed=false`）
* 三份现场 recon 报告（UGV / lab403-windows / weier）
* UGV CAN 帧实测（`candump -T 3000`，`241/253/254/251/252/221/311`）

### 8.4 阻塞项（依赖外部）

| 阻塞 | 依赖谁 |
| --- | --- |
| **「自动模式」怎么切换** | 厂家（**不问就是 `/cmd_vel` 发了车不动**） |
| 丢指令/异常退出时底盘停车还是保持、有无急停 | 厂家（**安全问题**） |
| launch 文件名差异（`bringup.launch` vs `outdoor_bringup.launch`） | 厂家；也可自查 `rospack find` |
| MQTT broker 地址 | 厂家 |
| `swarm_ros` 用途 | 厂家 |
| NVMe 内是否有数据 | 现场（需 `sudo`） |
| weier 是否可装 WSL2 | 现场（需管理员权限） |
| WIN 10053 修复 | Runtime 负责人 |

---

## 9. 值得保存的原始内容

### 9.1 用户对助手越界的纠正（【用户原话】，重要工作方式依据）

| 原话 | 含义 |
| --- | --- |
| "先不飞，看看他们三个的回复" | 助手不得抢跑执行 |
| "你别改代码，先停系统，生成给runtime的prompt" | 改代码前必须先停系统并生成交接物 |
| "不做A，先让 Runtime/仿真把 B 做掉，然后停系统，生成给runtime的prompt" | 明确排除某方案，指定顺序 |
| "我现在不需要你改了，因为时间有限" | 时间约束优先于完备性 |
| "后台任务先都关了" | 资源控制 |
| "这个可以删除吗"（PX4 日志）→ 后同意"先把旧的删了" | 助手必须先问再删 |
| "你也告诉我命令吧，全是脚本以后我没法一个人工作了" | **交付形态要求：命令优先** |
| "是iqr，你识别的问题" | 纠正助手视觉误读 |
| "UGV必须装runtime" | 明确需求，不接受"装不上"的迂回 |

### 9.2 用户明确确认的事实与环境声明

* 中间笔记本**没有网络**，只作为存储 + 试装点
* 中间笔记本：Windows 10 专业版 build 18363（1909），Python 3.13.9（anaconda），**无 Node**，**无 WSL**，**只有 Firefox**，Intel UHD 620（驱动 2018-02-28，1024 MB）
* **weier 有 GPU**（用户确认；与 WMI + nvidia-smi 双源一致 → RTX 3080 10240 MiB，compute 8.6）
* **lab403 "几乎可以说是没有"独立显卡**（用户确认）
* **UGV 能联网**【已实测 `curl -sI http://pypi.org` → `HTTP/1.1 301 Moved Permanently`】
* **UGV 能开无线热点**
* **lab403 还有 Windows 系统**
* **weier 不能联网**
* **UGV 控制需要先设为"自动模式"**（厂家）
* 厂房/场景：车是 Scout 2.0；`outdoor_start.sh` 串起 bringup / localisation / MPC formation

### 9.3 厂家答复（2026-10-22，【用户转述，原文照录】）

> 底盘型号是Scout 2.0
>
> 启动roslaunch iqr_robot_bringup bringup.launch就会启动所有传感器和底盘
>
> 直接发cmd_vel就可以控制车，cmd_vel是官方的格式，每个字段都有解释
>
> 控制车需要要控制设置为自动模式
>
> 底盘驱动把can封装了，直接发topic就行

### 9.4 Runtime 负责人复核意见（要点照录）

> "这份验收证明了离线依赖安装、Runtime 启动、主控台与三维渲染、跨域访问可用；真机通信和 PX4/Gazebo 飞行链路仍待另行验收。"
>
> "WinError 10053 的根因判断正确……建议的补丁方向对，但应覆盖完整的响应发送过程：响应头、响应体，以及 400/500/OPTIONS 响应都可能遇到断连。异常处理还应限定在 HTTP 读写处，避免把执行器内部的连接故障一起忽略；真正的服务端错误仍需保留。"
>
> "另外，报告中'请求丢失、前端重试'的表述要限定为查询请求：动作请求即使没收到响应，也可能已经执行，应通过原请求标识查询或幂等重试，不能当成动作未发生。"
>
> "本轮只做了阅读和代码核对，没有改代码或运行测试。"

### 9.5 助手早期的架构原则陈述（已成文，供对照）

* "LLM/Agent 不直接输出飞控协议帧"
* "控制面与执行面分离"
* "`unified_policy_gate` 是唯一裁决入口"
* "canonical `protocol_json` 是契约主入口"
* "`AdapterGateway` 负责：请求转执行意图、幂等检查、命令构造、adapter 调用、结果归一化"
* "审计与回放：关键决策事件写本地 JSONL；`replay_last` 读取最近事件供复盘"
* "**Runtime 是控制面。没有载具，它就是个'能正确拒绝一切'的 HTTP 服务。**"
* "**部署成功只证明'能启动'；有效果需要策略裁决、审计、回放能产生可检查的输出。**"

### 9.6 手绘架构图与重绘

* **来源**：【用户提供】手机拍摄手绘稿（2026-10-19 23:22，vivo X Fold6）
* **助手读取结果**：三层 fan-out 树，每层一条横向总线，**最左子节点继续下延**，虚线框表示"还有更多"
* **明确标注的三处不猜**：
  1. 第 2 层文字"轨迹"还是"机载"（二者结论相反：机载 → 需新增机载 Runtime；轨迹 → 属规划层，分层不变）
  2. 第 0 层小虚线框（云端/指挥所/多集群）
  3. 每层"另一实例"是冗余还是并行多实例
* **助手给出的关键判别**：**手稿画的是两层 Runtime，而当前实现只有一层**（`mavlink_backend_session.py` 2067 行，单进程管三架机）→ 该图应读作**目标形态**，不是现状
* **产物**：`ops/architecture-stack.svg`（矢量源）+ `.png`（Edge headless 渲染）+ `docs/architecture_stack_layered.md`（Mermaid + 逐层对照）

### 9.7 现场 recon 报告的原始关键数据（供交叉核对）

**UGV（`nvidia`，Jetson AGX Orin）**
```
Ubuntu 20.04.5 / kernel 5.10.104-tegra / aarch64 / glibc 2.31 / L4T R35.3.1
python3 3.8.10 ; /usr/bin/python3.9 = 3.9.5 ; ensurepip 缺失 ; pip3 可用
无 nvidia-smi ; nvcc release 11.4 (V11.4.315) ; /usr/local/cuda-11.4
ROS noetic 282 包 ; ROS_MASTER_URI=http://localhost:11311 ; 无节点在跑
/ = mmcblk0p1 54G 已用28G 剩24G
nvme0n1 477G ; nvme0n1p1 477G ext4 **未挂载**
can0 UP 500000 bitrate ERROR-ACTIVE ; candump: 241/253/254/251/252/221/311
eth2 UP (64:62:66:00:77:20) 无 IPv4 ; 无默认路由
SSH 22 LISTEN ; DISPLAY=:0 ; firefox 110.0 ; NoMachine(nxnode/nxrunner)
用户组无 dialout ; 串口 ttyTHS0/1/3/4 存在
/home/nvidia/outdoor_start.sh ; /home/nvidia/catkin_ws/src/swarm_ros
/opt/ros/noetic 下 gazebo_ros / gazebo_plugins / gazebo_msgs 等已装
```

**weier（`DESKTOP-LOTFUFQ`，LENOVO 30E4A3XHCW）**
```
Windows 10 专业版 build 19041 ; i7-11700K 16核 ; 63.6 GB RAM
NVIDIA GeForce RTX 3080 (nvidia-smi: 531.29 / 10240 MiB / compute 8.6) + Intel UHD 750
python: 仅 Microsoft Store 别名（无真解释器）; node/npm/WSL 均无
C: 476.3G(307.7 free) / D: 1860.8G(478.2 free) / E: 1865.2G(474.4 free)
git/ssh/scp/curl/tar 可用（D:\VRNET\msys）; 192.168.0.6/24 ; 插着 29 GB U 盘
报告内嵌时间 2026-11-16 16:37  【待核】
```

**lab403（`lab403-System-Product-Name`）**
```
Ubuntu 20.04.1 LTS / kernel 5.15.0-139 / x86_64 / glibc 2.31
python3 3.8.10 唯一 ; **pip3 缺失** ; ensurepip 缺失 ; venv 有
NVIDIA GT 730 (GK208B) ; 无 nvidia-smi ; 无 glxinfo
/ = sda5 95G 已用15G 剩76G ; sda 1.8T (sda1 1000G ntfs, sda2 763G ntfs)
nvme0n1 931.5G 全 NTFS (p1 579M, p2 201G, p3 730G)
enp5s0 / enp6s0 全 DOWN ; **无默认路由**
firefox 136.0 ; git ❌ curl ❌ pip3 ❌ node ❌ ; ssh/scp/rsync/tar/make/gcc ✅
RAM 31 GB ; 无 ROS
```

### 9.8 交付包结构（可复现的离线清单）

```
Batch 1（10.90 MB / 451 文件）
  recon/{recon-offline-env.sh, recon-vehicle.sh, recon-windows.ps1}
  frontend/swarm-console/{index.html, app.js, console-model.js, runtime-api.js, styles.css, package.json}
  frontend/swarm-console/simulation-3d/src/   （16 文件 / 0.15 MB，app.js 硬依赖其中 vehicle-contract.js）
  frontend/swarm-console/simulation-3d/dist/  （422 文件 / 18.7 MB，gitignored，必须单独携带）
  00-START-HERE.md

Batch 2（186.56 MB / 5 卷 + helpers）
  00-START-HERE.md                          13.6 KB
  01-source.tar.gz                          10.94 MB / 518 项
  02-frontend-3d-dist.tar.gz                10.78 MB / 422 项
  03-frontend-3d-node_modules-WIN.tar.gz    54.15 MB / 10,170 项（仅 Windows）
  04-wheelhouse.tar.gz                      74.70 MB / 27 轮子
  05-node-v24.22.0-win-x64.zip              35.99 MB / 2,459 项
  helpers/{0-STEP-BY-STEP.txt, 1-start-console-5178.bat, 2-start-3d-5179.bat,
           3-start-runtime-8765.bat, 4-install-pymavlink.bat, show-audit.py}
```

**排除项与理由**：`.runtime/`（1,587 MB，ULog 飞行日志，现场不需要）、
`.git/`（40.6 MB，离线机无 git）、算法模型权重（~3.8 GB，且平台不通用）。

### 9.9 本项目实测的环境常量（供总报告引用）

| 常量 | 值 | 条件 |
| --- | --- | --- |
| RTF（三机相机版） | **0.84 ~ 0.94** | RTX 4050 + `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` |
| RTF（缺该变量） | **0.175** | 同一机器，未设变量 |
| RTF 健康门槛 | **0.20** | `system_status.py` 判据 |
| 标定 TTL | **≈60 s**（`valid_for_ms≈59885`） | — |
| health TTL | **≈5 s**（`valid_for_ms≈4913`） | 曾误用于静态几何（M3） |
| 落地判据容差 | **≤0.3 m**，≥3 样本，≥0.5 s | 实测 0.009510 m / 5 样本 / 550 ms |
| 返航到达容差 | **0.75 m** | `arrival_samples 10` |
| HOME 交叉核验误差 | **9.4 mm** | `global_local_xy_crosscheck` |
| 端口 | PX4 14580-82；Runtime 14540-42（**单点独占**）；HTTP 8765；主控台 5178；三维 5179 | — |
| 前端轮询 | **2000 ms**（状态）/ **5000 ms**（事件）/ health 超时 **2500 ms** | — |

---

## 10. 归档结论

### 10.1 本对话在项目史中的位置

本对话**没有开启新方向**，而是完成了三件性质不同的事：

1. **纠偏**：把项目自我认知（README、架构描述）拉回到与代码一致的水平（M1、M10）
2. **从"能飞"转向"报的结论是否可信"**：语义缺陷的发现与实飞验证（M2），并沉淀出可复用的判据设计原则（R1–R5）
3. **从"开发环境"走向"断网现场"**：离线迁移、现场勘察、异构载体接入（M7、M8、M9）

### 10.2 最有长期价值的三条

| # | 内容 |
| --- | --- |
| **1** | **完成判据必须可证伪**。用"进度"代替"到达"的判据在正常工况下必然通过，因此它对失败是盲的（R1） |
| **2** | **静态环境证据与操作许可必须分离**：前者按版本绑定、后者按时间过期（R2） |
| **3** | **执行层可见性是治理可验证性的前提**。`adapter: ""` 这一条字段，比任何文字承诺都更能证明"策略门真的拦住了"（R4） |

### 10.3 归档自身的局限（诚实声明）

* 阶段 A（四模块联调、真机控制探索）的**具体日期与细节依赖对话早期的压缩上下文**，本文只保留可确证的部分，日期一律【待核】
* `weier.txt` 的采集时间与内容存在**内部矛盾**（见 §1.2），未解决
* 三份 recon 报告均为**单次快照**，不代表环境当前状态
* 本归档**不含**对话之外的开发历史（如 2026-03 至 2026-10-09 之间的实现过程），那部分需另行取材

---

**归档结束**　编制于 2026-10-26　基线 `main` @ `d3f0268`
