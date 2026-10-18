# UAV Runtime · 2026UAVSwarm

无人机/无人系统任务执行运行时。覆盖 **PX4 SITL + Gazebo 仿真、Runtime、主控台、三维视图** 四模块，
已在真实 Gazebo/PX4 上做过三机实飞验收。

> **本文档描述的是仓库当前实际状态，不是早期规划。**
> 早期版本（`v0.1-contract-skeleton-pass`）曾以 "MVP Skeleton / Fake Adapter" 为主，
> 那些描述**已经过期**。当前的事实见下文，每一条都标注了证据来源。

---

## 1. 项目现在是什么

一个**能开环飞真机/仿真机**的任务执行运行时，主链路：

```
控制台 / Agent  →  Runtime  →  Policy Gate  →  每机长期 MAVLink session  →  PX4 飞控
                    │
                    └→ 审计 JSONL  →  回放
```

**已经做到**（不是骨架，是跑通的）：

| 模块 | 状态 | 证据 |
| --- | --- | --- |
| **Runtime（`src/uav_runtime`）** | ✅ 17 个子包 | `protocol` `policy` `runtime` `adapters` `http` `skills` `agent` `services` `observation` 等 |
| **真实 MAVLink 后端** | ✅ **不是 stub** | `px4_sitl_backend.py` 973 行、`mavlink_backend_session.py` 2067 行、`px4_telemetry.py` 454 行，均 `import pymavlink` |
| **HTTP API** | ✅ 27 个路由 | 含 6 个动作端点（见 §3） |
| **PX4 + Gazebo 三机仿真** | ✅ 相机版可跑 | `simulation/px4_gazebo/`，RTF 实测 **0.84~0.94** |
| **主控台** | ✅ 纯静态 | `frontend/swarm-console/`（`app.js` 113 KB），端口 5178 |
| **三维视图** | ✅ 可离线 | `frontend/swarm-console/simulation-3d/`（Vite + Cesium + Three.js），端口 5179 |
| **算法离线基线** | ⚠️ 部分 | `algorithm_lab/`（代码在库，**模型权重不在 git**） |
| **自动化测试** | ✅ **917 passed / 6 skipped** | `python -m pytest -q` |

**当前版本里程碑**：

```
v0.1-contract-skeleton-pass            f52c4ff    契约冻结（骨架阶段）
v0.1-four-module-integrated-pass       bfa75e8    四模块首次打通
v0.1.1-rooftop-landing-corrected       8717c25    屋顶着陆误报修复
v0.1.2-rooftop-and-return-home-verified ea4bf62    两处语义修复经实飞验收
```

---

## 2. 已验证到什么程度（**这部分最容易被旧 README 误导**）

### 2.1 实飞验收过的（UAV-02，真 Gazebo/PX4，UAV-01/03 全程隔离）

| 验证项 | 结果 | 关键证据 |
| --- | --- | --- |
| **落地完成判据** | ✅ 通过 | `ground_check.vertical_error_m = 0.0095`、`on_scene_ground = true`、5 样本 / 550 ms |
| **缺证据时 fail-closed** | ✅ 通过 | 标定过期时返回 `ground_reference_unavailable` + `completion_state = unknown`，但如实记录 `physical_landed_disarmed = true` |
| **返航到达判据** | ✅ 通过 | 起点距 home **6.751 m**、`distance_reduction_m = 6.547`、`min_progress_m = 5.0`（旧判据也会通过），但判据是 `arrived_at_home` + `arrival_samples = 10` 落在 0.75 m 容差内 |
| **HOME / RTL 核验** | ✅ 通过 | `home_evidence.verification = global_local_xy_crosscheck`（误差 9.4 mm）、`rtl_type.param_value = 0`、`rally_points.count = 0` |
| **三机隔离** | ✅ 通过 | UAV-01/03 全程 `armed = false` |

**完整原始证据**：
`ops/ACCEPTANCE_UAV02_FLIGHT_20261012.md`、`ops/ACCEPTANCE_B_0_8_30_RESULT.md`

### 2.2 未验证的（**别当成已完成**）

| 项 | 现状 | 影响 |
| --- | --- | --- |
| **真机链路** | ❌ 只验过 SITL。真机走**数传电台 / 串口 / UDP**，地址与 `sysid`/`compid` 都需重配与核验 | 部署到真机前必须单独一轮验收 |
| **`goto` 到达语义** | ⚠️ 未通过且**原因未定**：实测到过目标 2.9 m 后又漂到 37 m（最后差的主要是垂直方向） | 但它**诚实报了 `timed_out`**，没有谎报到达 |
| **指定站点的站点符合性** | ❌ **没有 `validated` 生产者**，站点证据链未闭环 | 目前只能证明"落在场景地面"，**不能**证明"落在指定 pad" |
| **载荷（相机/云台）真实证据** | ❌ `payload_adapter.py` 是**无硬件桩** | 它的输出**不是**真采集，不能当作相机/角度/音频/灯光证据 |
| **视觉模型在线推理** | ❌ 未实测 | 本机内存不足时按保护规则停止；Orin 板端时延/内存/功耗未测 |
| **ROS 接入** | ❌ 不在控制链路里 | 当前接飞控**不依赖 ROS**；ROS 只作为未来机载感知的候选 |

---

## 3. HTTP API（27 个路由）

**动作端点（POST）**：

```
/api/actions/takeoff          /api/actions/smoke-takeoff
/api/actions/land             /api/actions/goto
/api/actions/hold-position    /api/actions/return-home
```

**语义要点**（踩过坑，写在这里免得误解）：

* **响应即最终结果**：POST 返回里 `status` / `result` / `completion_evidence` 已是判定结果，**不是"已受理"**。
* **"命令被接受" ≠ "动作完成"**：`MAV_RESULT_ACCEPTED` 只说明飞控收下了命令。
* **`land` 是"在当前正下方降落"**，不是"飞到某处再落"。要回起飞点请用 `return-home`。
* **`return-home` 发的是 RTL**，语义是"回 PX4 自己的 home"，因此会核验 `HOME_POSITION` 与 RTL 目标配置。

**只读端点**：

```
/api/health              /api/vehicle-snapshot      /api/telemetry/latest
/api/simulation/status   /api/preflight?node_id=…   /api/actions/recent
/api/policy/decisions    /api/coordinates/calibration  /api/vehicles
/api/skills              /api/capabilities          /api/replay
/api/snapshot            /api/events                /api/backend/check
/api/agent/status        /api/planner/plan-mission  /api/plans/execute
/api/simulation/evidence /api/actions/lifecycle
```

---

## 4. 核心设计原则（仍然成立）

1. **LLM / Agent 不直接输出飞控协议帧**
   上层只产生结构化请求（`ActionRequest`），具体命令由 adapter 层映射。

2. **控制面与执行面分离**
   policy 判"能否执行"；adapter 做"如何执行"的下沉映射。

3. **`unified_policy_gate` 是唯一裁决入口**
   执行前统一进入该 gate，输出标准化 `PolicyDecisionEnvelope`。

4. **canonical `protocol_json` 是契约主入口**
   `action_type` / `requested_scope` / `priority_hint` 等；legacy alias 仅迁移兼容。

5. **`AdapterGateway` 负责**：请求转执行意图、幂等检查、命令构造、adapter 调用、结果归一化。

6. **审计与回放**：关键决策事件写本地 JSONL；`replay_last` 读取最近事件供复盘。

---

## 5. 架构与目录

```
src/uav_runtime/
    protocol/     枚举、schema dataclass、编解码与校验
    policy/       policy context/profile/decision 与 unified_policy_gate
    runtime/      orchestrator、事件总线、任务队列、审计写入、回放
    adapters/     ← 真实执行层，见下
    http/         8765 HTTP 桥（routes / preflight / state_store / schemas）
    skills/       动作技能注册与执行
    agent/        任务规划与计划生命周期
    services/     canonical / api / io / observation / scenario / sim / utils

    adapters 明细（16 个文件）：
      px4_sitl_backend.py          973 行   真实 PX4 SITL 动作后端（pymavlink）
      mavlink_backend_session.py  2067 行   长期会话 / 遥测 / 动作生命周期
      px4_telemetry.py             454 行   MAVLink 遥测采集
      px4_runtime_adapter.py        95 行   把 backend 包成 Runtime 接口
      gateway.py                   136 行   AdapterGateway
      fake_adapter.py               45 行   ⚠️ 测试用假适配器（非生产路径）
      sitl_backend_stub.py         103 行   ⚠️ 桩
      mavlink_adapter.py           132 行   ⚠️ 桩（默认返回 exec_unavailable）

simulation/px4_gazebo/     三机 SITL 编排、健康、标定、巡逻、验收
    config/three_uav_sitl.json          默认版
    config/three_uav_mono_cam_sitl.json 相机版（三维视图需要）
    scripts/  start/stop_three_uav.sh、health_three_uav.py、
              sample_calibration.py、patrol_three_uav.py、verify_three_uav_cameras.py

frontend/swarm-console/            主控台（静态，5178）
frontend/swarm-console/simulation-3d/  三维视图（Vite+Cesium+Three，5179）

ops/          运维入口：system_status.py、restore-system.sh、验收脚本、迁移文档
docs/         63 篇设计/契约/验收文档
tests/        917 passed / 6 skipped
```

---

## 6. 快速开始

### 环境

* **Python ≥ 3.10**（`pyproject.toml: requires-python = ">=3.10"`）
  ⚠️ **Ubuntu 20.04 自带 3.8，不够** —— 需要另装解释器。
* 仿真需要 **NVIDIA GPU**。实测：相机版三机在 RTX 4050 上 RTF 0.84~0.94；
  **不设 `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` 会掉到 0.175**（低于 0.20 门槛，健康判 `not_ready`）。
* 已验证环境：Ubuntu 22.04 (WSL2)，x86_64。

### 安装与测试

```bash
pip install -e .[dev]      # 核心无三方依赖；dev 含 pytest / jsonschema
pip install -e .[sitl]     # 接 PX4 需要 pymavlink
pytest -q                  # 期望 917 passed, 6 skipped
```

### 一条命令看系统到底能不能用

```bash
python3 ops/system_status.py          # 六项独立证据，退出码 0/1/2
```

它查**进程 / 仿真时钟推进 / 三台遥测 / Runtime / 标定 / manifest 是否相机版**六项，
而不是数进程 —— 因为"进程数正常"在本项目被证伪过两次（Gazebo 掉了但 PX4 还在；
起的是默认版而非相机版）。

### 起仿真 + Runtime + 前端

```bash
# 1) 仿真（相机版，必须带 GPU 适配器变量）
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA \
  python3 simulation/px4_gazebo/harness.py start --headless \
    --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json

# 2) Runtime（从同一个仓库根起，否则读不到仿真状态）
PYTHONPATH="$PWD/src" setsid nohup python3 -u -m uav_runtime.http.server \
  > /tmp/rt.log 2>&1 < /dev/null &

# 3) 主控台 / 三维
python3 -m http.server 5178 --bind 127.0.0.1 --directory frontend/swarm-console &
cd frontend/swarm-console/simulation-3d && npm ci && npm run dev &
```

### 一个动作（示例）

```bash
# 起飞前先看预检（只读，无飞行副作用）
curl -s "http://127.0.0.1:8765/api/preflight?node_id=UAV-02"

# 起飞
curl -s -X POST http://127.0.0.1:8765/api/actions/takeoff \
  -H 'Content-Type: application/json' -d '{"node_id":"UAV-02","altitude_m":5}'

# 返航（回 home，然后 PX4 可能自己降落）
curl -s -X POST http://127.0.0.1:8765/api/actions/return-home \
  -H 'Content-Type: application/json' -d '{"node_id":"UAV-02"}'
```

**`GET /api/preflight` 的 `execution_authorized` 恒为 `false`** —— 它是只读预检
（`flight_command_sent: false`），**不能当飞行许可**。

### CLI（策略/审计链路验证，与 HTTP 桥并行存在）

```bash
python -m uav_runtime.console.cli submit-action takeoff
python -m uav_runtime.console.cli show-status
python -m uav_runtime.console.cli show-audit
python -m uav_runtime.console.cli replay-last
```

---

## 7. 关键约定（踩过坑才写下来的）

| 项 | 约定 | 为什么 |
| --- | --- | --- |
| **端口** | PX4 占 `14580-14582`；Runtime 占 `14540-14542`（**单点独占，不能共享**）；Runtime HTTP `8765`；主控台 `5178`；三维 `5179` | 两个进程抢同一 UDP 端口会静默丢包 |
| **坐标系** | `vehicle_local_ned`（各机自己起飞点为原点）与 `scene_ned`（场景固定原点）**不同**；站点/多机比较必须用 `scene_ned` | 混用会导致"看起来算对了但位置全错" |
| **标定 TTL** | **60 秒**。动作用前必须重新发布 | 过期后 goto/land 的坐标判定会被直接拒绝（`coordinate_calibration_unavailable`） |
| **静态几何** | 站点/地面几何**按版本绑定**（`world_sha256` + `map_version`），**不随时间失效** | 曾把它挂在 5 秒 health TTL 上，导致 preflight 只在 5 秒窗口内可用 |
| **相机版 manifest** | 三维视图需要 `three_uav_mono_cam_sitl.json` | 默认版没有相机模型，模型名也不同 |
| **行尾** | `.sh` 必须 LF（仓库已有 `.gitattributes`） | CRLF 会让 `set -euo pipefail` 变成 `set: pipefail: invalid option name`，**仿真完全起不来而症状会误导** |

---

## 8. 诚实的边界

**适合**：
* 作为控制面-执行面分层架构的开发基线；
* 作为协议字段与策略裁决契约的对齐基准；
* 作为 PX4 SITL 联调与四模块集成的验证底座；
* 作为向真机迁移的起点（已验证两处关键语义）。

**不适合**（明确不承诺）：
* ❌ **直接用于生产飞行任务**；
* ❌ 作为完整飞控替代品；
* ❌ **承诺陌生地形的安全落点判断** —— 目前只能证明"落在已标定的场景地面上"；
* ❌ 把"载荷桩的输出"当作真实相机/云台证据；
* ❌ 把"成功落了地"写成"在指定站点完成任务"（站点证据链未闭环）。

---

## 9. 文档索引

| 想知道什么 | 看哪里 |
| --- | --- |
| 代码结构与阅读顺序 | `docs/codebase_guide.md`、`docs/project_summary.md` |
| 动作完成判据 | `docs/px4_command_completion_criteria.md`、`docs/runtime_control_execution_contract_v1.md` |
| HTTP 桥与实时状态 | `docs/runtime_http_bridge_v0_1.md`、`docs/runtime_realtime_state_api_v0_1.md` |
| 策略裁决 | `docs/policy_gate_v0_2_summary.md`、`docs/policy_profile_v0_2_summary.md` |
| 仿真与环境 | `docs/px4_sitl_setup_and_readiness_runbook.md`、`docs/simulation/` |
| 三机实飞验收证据 | `ops/ACCEPTANCE_UAV02_FLIGHT_20261012.md` |
| 离线/无网迁移 | `ops/MIGRATION_OFFLINE_20261014.md` |
| 运维（启动/健康/恢复） | `ops/README.md`、`ops/MANUAL_STARTUP.md` |
| 发布与版本 | `docs/release/` |
| 现场环境勘察脚本 | `ops/recon-offline-env.sh`、`ops/recon-windows.ps1`、`ops/recon-vehicle.sh` |

---

## 10. 当前阶段一句话

> **四模块已打通，两处"报成功但与事实不符"的语义缺陷已修并经实飞验证；
> 真机链路、站点证据链、在线落点感知仍未完成 —— 所以它是"可验证的集成底座"，
> 不是"可直接上生产任务的系统"。**
