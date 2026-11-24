# 给 Runtime 负责人的工作确认与待办清单

**发起**：集成侧
**时间**：2026-11-04
**背景**：离线环境部署已推进到「Runtime 在 Windows 与 Jetson 两个平台都跑起来了」，
现在要把缺口一次说清，并请你确认哪些已经在你的工作区实现了。

---

## 〇、先说一句：这份清单可能有一部分你已经做完了

我们知道**各位负责人这段时间都在自己的工作区里开发，只是还没合并**。
所以下面列的"缺口"，有一部分很可能**已经在你那里实现了**。

**请你按这个方式回复**：

| 状态 | 含义 |
| --- | --- |
| **已实现·已合并** | 在 `main` 上，告诉我 commit 或文件名 |
| **已实现·未合并** | 在你工作区/分支里，告诉我分支名 + 大概完成度 |
| **在做** | 有方案了，还没写完；说一下打算怎么做 |
| **未做** | 还没碰 |
| **不打算做 / 有不同意见** | 说明理由，我们可以调整 |

**判断依据请以你的代码为准，不要以这份清单为准。** 我这边只能看 `main`。

---

## 一、请你先做的事：说明上次合并之后你做了什么

**这一条优先于下面的所有内容。**

我们需要知道：

1. **上次合并（`PR #92` → `PR #88` 之后）到现在，你做了哪些工作？**
   - 已合并进 `main` 的
   - 还在你工作区、没合并的
2. **有没有涉及下面第三节那几个方向的改动？**
3. **有没有正在改、暂时不能被打断的部分？**（避免我们期待的东西和你正在做的冲突）

**为什么先问这个**：我们这边在离线环境里实测，拿到的结论都是基于 `main` 的。
如果你工作区里已经解决了其中几项，那我们就不用重复投入，直接等你合并。

---

## 二、我们这边已经验证到的状态（供你对照）

### 2.1 Runtime 本体：两个平台都跑通了

| 平台 | 结果 |
| --- | --- |
| **Windows 11 + 便携 CPython 3.11.18** | ✅ `/api/health` 200、`/api/capabilities` 200、策略门 deny/allow 正确、审计落盘 3 行 |
| **Jetson AGX Orin (Ubuntu 20.04 aarch64) + 便携 CPython 3.11.18** | ✅ 启动成功 `listening on http://127.0.0.1:8765/api` |
| Ubuntu 22.04（中间笔记本） | ✅ 之前已验收 |

**过程里踩到的、可能与代码有关的点**（供你参考，不一定要改）：

| 现象 | 原因 |
| --- | --- |
| `dataclass() got an unexpected keyword argument 'slots'` | 用 Python 3.8 跑。`slots` 是 3.10+。**这条其实是 `requires-python >= 3.10` 在正确生效**，只是报错信息不直观 |
| `adapters` 与 `http.routes` 在**没装 pymavlink** 时也能 import | pymavlink 是惰性导入。**这是好事**：Runtime 在无 MAVLink 环境可启动 |
| Windows 控制台（GBK）打印 emoji 抛 `UnicodeEncodeError` | 不是 Runtime 的问题；但 `print` 里如果有非 GBK 字符会崩 |

### 2.2 治理链路：无载具也能出结果（已实测）

| 能力 | 实测结果 |
| --- | --- |
| 策略门裁决 | `land --demo-link-state lost` → `decision_code=deny` / `status=blocked` / **`adapter=""`** |
| 策略门放行 | `takeoff --demo-link-state healthy` → `allow` / `accepted` / `adapter="fake"` |
| 审计 | `audit/runtime.audit.jsonl` 每次动作 2 条（拒绝时 1 条） |
| 任务规划 | `plan-mission --mission-type inspection_snapshot --dry-run` → **4 步计划**，每步带 `policy_precheck`（allow）+ `required_capability` |
| 能力注册表 | 16 个动作，含 `risk_level` / `allowed_link_states` / `fallback_allowed` |
| 回放 | `replay-last` 正常 |

### 2.3 前端

| 模块 | 状态 |
| --- | --- |
| 主控台 5178 | ✅ 两个平台都能完整渲染（Windows / Jetson 均有截图） |
| 三维 5179 | ✅ 能渲染；⚠️ 但有浏览器版本门槛：Cesium 用了 `Array.prototype.toSorted`，**需要 Edge/Chrome 110+ 或 Firefox 115+**。老浏览器崩在 `CesiumWidget` 构造处，报错文案误提 WebGL |
| 三维 DEMO 模式 | ✅ 内置 5 架载具动画（MR-01/MR-02/FW-01/VTOL-01/**UGV-01**），120 秒，含 mode/agentStatus/intent |

### 2.4 无人车（UGV）环境：已摸清

**厂家确认**：Scout 2.0；控制走 **ROS `/cmd_vel`（`geometry_msgs/Twist`）**；
CAN 已被底盘驱动封装，**不需要碰 CAN**；控制前提是**遥控器第二个拨杆拨到最上（自动模式）**。

**现场实测的 ROS 接口**：

```
/cmd_vel          geometry_msgs/Twist    订阅者: /scout_base_node     ← 控制通道
/scout_status     速度/模式/故障/电压/电机状态                        ← 反馈通道
/scan             激光雷达（pointcloud_to_laserscan）
/camera/color/image_raw , /camera/depth/points    Orbbec Femto Bolt RGBD
/imu/data , /imu/data0        HWT9053 (RS485, 115200)
/pan_tilt_cmd_deg , /pan_tilt_status            云台
/odom , /robot_pose_ekf/odom_combined , /tf     定位
/BMS_status , /scout_light_control
```

**⚠️ 车端 ROS 是 Noetic = Python 3.8，而 Runtime 要求 Python ≥ 3.10。**
所以 Runtime 里**不可能** `import rospy`。这是硬冲突，见第四节 A。

---

## 三、缺口清单（请你逐条确认状态）

### 缺口 1：ROS 支持 —— 一行都没有

**证据**（在 `main` 上 grep `src/`）：

```
rospy            0
roscpp           0
cmd_vel          0
Twist            0
geometry_msgs    0
roslibpy         0
rosbridge        0
sensor_msgs      0
/scan            0
```

**后果**：Runtime 现在**无法控制这台无人车**，也**读不到它的传感器**。
适配层只有 MAVLink（`px4_sitl_backend` / `mavlink_backend_session` 等 16 个文件）+ `fake` + `payload`（桩）。

**需要**：一个能对 `/cmd_vel` 发指令、并能读 `/scout_status` 的后端。
具体走哪条路见第四节 A。

**状态**：☐ 已实现·已合并　☐ 已实现·未合并　☐ 在做　☐ 未做　☐ 有不同意见

---

### 缺口 2：载荷只有桩，而车上有真传感器

**证据**：`src/uav_runtime/adapters/payload_adapter.py` 开头自述：

```python
"""Payload/device adapter skeleton for non-destructive onboard devices.

The adapter is intentionally hardware-free.  It validates placeholder action
metadata and returns contract-compatible raw results for future camera, gimbal,
speaker, light, sensor, and health-monitor integrations.
"""
...
# Keep this adapter deterministic and hardware-free so tests never require cameras/gimbals/speakers.
```

**后果**：`camera_capture` / `gimbal_set_angle` / `sensor_read` / `light_set_state` 这些动作
**返回的是 `payload://unsupported` 之类的假引用，不是真数据**。
验收时如果有人问"相机拍到了什么"，答案是"没有，那是桩"。

**而车上有真东西**：Orbbec Femto Bolt（RGBD+IMU）、激光雷达、HWT9053 IMU、云台、BMS。
ROS 侧全都在发（`/scan`、`/camera/color/image_raw`、`/pan_tilt_status`、`/BMS_status`）。

**需要**：把载荷动作接到真实数据源（至少"能取到一帧图像/一帧点云/一个云台角度，并作为证据返回"）。

**状态**：☐ 已实现·已合并　☐ 已实现·未合并　☐ 在做　☐ 未做　☐ 有不同意见

---

### 缺口 3：监听地址与端口写死 → 多实例、跨机都做不了

**证据**：

```python
# src/uav_runtime/http/server.py:99-110
def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), RuntimeHttpBridgeHandler)

def main() -> int:
    server = create_server()      # ← 不传参，用默认值
    ...
    print("uav_runtime_http_bridge listening on http://127.0.0.1:8765/api")
```

`main()` 不解析 `sys.argv`；`UAV_RUNTIME_HTTP_PORT` 只用于拼响应里的 URL 字符串
（`routes.py:905`），**不影响绑定**。

**后果**（这是我们 weier 集群方案被卡住的直接原因）：

| 想做的 | 现在 |
| --- | --- |
| 一台机器跑多个 Runtime 实例 | ❌ 端口写死 8765 |
| 一台 Runtime 服务多台显示机 | ❌ 只监听 127.0.0.1 |
| 跨机访问 Runtime | ❌ 同上 |

另外 `ALLOWED_ORIGINS` 只有 `localhost` / `127.0.0.1`（含 5173/5178/5179），
**没有 IP 形式** → 从别的机器用 `http://192.168.x.x:5178` 打开主控台会跨域被拒，
前端显示"后端不可达"。

**建议的最小补丁（4 行，默认值不变，不影响现有行为与测试）**：

```python
def main() -> int:
    host = os.environ.get("UAV_RUNTIME_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("UAV_RUNTIME_HTTP_PORT", "8765"))
    server = create_server(host, port)
    ...
    print(f"uav_runtime_http_bridge listening on http://{host}:{port}/api")
```

**这一条对我们最急** —— 3~6 台 weier 要组成集群，没有它就只能"每台各自为政"。

**状态**：☐ 已实现·已合并　☐ 已实现·未合并　☐ 在做　☐ 未做　☐ 有不同意见

---

### 缺口 4：多实例/多机协同能力

Runtime 一个实例管一个 manifest（三机）。**实例之间没有协同机制**：
没有共享状态、没有任务分配、没有跨实例审计汇总。

**后果**：3~6 台 weier 各自跑一个 Runtime 时，它们**互相不知道对方存在**。
"集群"目前只能是"多套独立的单机系统"。

**需要**：明确 Runtime 是否要承担跨实例协同；如果要，是中心式（一台调度、其余执行）
还是分布式（共享状态）。**这个问题可能需要和算法侧一起定。**

**状态**：☐ 已实现·已合并　☐ 已实现·未合并　☐ 在做　☐ 未做　☐ 有不同意见

---

### 缺口 5：没有智能模块（不做自然语言、不调模型）

**证据**：`src/uav_runtime/agent/planner.py` 开头自述：

```python
"""Intent Router + Template Agent Planner v0.1.

This module is intentionally plan-only.  It converts an explicitly supplied
``mission_type`` into a deterministic Mission Plan IR, validates every step
against the Action / Capability Registry, and performs a Policy Gate precheck.
It does not parse free-form natural language, call an LLM, execute runtime
actions, or send MAVLink / adapter commands.
"""
```

而且 `MISSION_TEMPLATES` 只有 5 种固定任务：

```
simple_takeoff_land , inspection_snapshot , status_only , safe_stop , fallback_hold
```

代码里也留了 TODO：

```
# TODO: a future LLM Intent Parser may propose mission_type/params, but it must still
# pass this router, capability validation, policy precheck, operator confirmation,
# Runtime authorization.
```

**后果**：
- "给它一句话任务，它自己理解并规划" → ❌ 做不到
- "它用自然语言回答我" → ❌ 做不到
- "给结构化 mission_type，生成确定计划并过策略门" → ✅ 能做到（已实测）

**需要**：确认智能层放在哪里 —— Runtime 内，还是外部服务（我们 `algorithm_lab/mission_llm_poc/`
有一个离线实验，但目前**没接进 Runtime**）。

**状态**：☐ 已实现·已合并　☐ 已实现·未合并　☐ 在做　☐ 未做　☐ 有不同意见

---

### 缺口 6：算法模块没有接进 Runtime

`algorithm_lab/` 里的东西（`mission_llm_poc`、`world_model_lab`、`landing_assessment_lab`）
是**离线实验/评估**，**不在控制链路里**。Runtime 现在没有任何调用算法的入口。

**后果**：验收时"算法"和"系统"是两套东西，没有连起来。
而 UGV 上那块 Jetson 有 CUDA 11.4 + TensorRT 8.5.2.2 + cuDNN 8.6.0，
**算力是有的，缺的是接口约定**。

**需要**：定义"算法 → Runtime"的接口（输入什么证据、输出什么结论、如何进入策略裁决），
以及它在 Runtime 里落在哪一层（observation？skill？独立服务？）。

**状态**：☐ 已实现·已合并　☐ 已实现·未合并　☐ 在做　☐ 未做　☐ 有不同意见

---

### 缺口 7：`WinError 10053` 断连异常仍未修

你上一轮已经确认过根因和三条纠正（覆盖完整响应发送过程 / 限定在 HTTP 读写处 /
"请求丢失重试"只适用于查询请求）。**目前仍未修**。

**现状影响**：离线环境里关掉前端页面就刷一片 traceback，把真正的 500 淹没掉。

**状态**：☐ 已实现·已合并　☐ 已实现·未合并　☐ 在做　☐ 未做　☐ 有不同意见

---

## 四、两个需要你拍板的设计问题

### A. ROS 怎么接？（三条路，我倾向 A1）

| 方案 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| **A1（我倾向）** | **车端写一个 MAVLink 垫片**：用 pymavlink（py3.8，车上已有）把 MAVLink 速度指令转成 `/cmd_vel`，同时把 `/scout_status`、`/odom`、`/BMS_status` 回填成 MAVLink 遥测 | **Runtime 零改动** —— 它以为在连一个 MAVLink 载具；绕开 3.8/3.10 冲突 | 要把地面车语义映射到现有 UAV 动作集；垫片要自己写 |
| A2 | Runtime 新增 ROS 后端 + 一个 py3.8 中继（socket/MQTT） | 语义可以自定义（`drive_velocity` 等） | 要改 Runtime，且多一层进程与协议 |
| A3 | `rosbridge_server` + `roslibpy`（纯 Python，3.11 可用）走 WebSocket | 标准做法，不改 Runtime 核心 | 要在 3.8 侧装 rosbridge；多一层 JSON；延迟略高 |

**如果你的工作区里已经在做其中某一条，请告诉我，我们就不重复。**

### B. 地面车的动作集怎么定？

现有动作是按无人机设计的：`takeoff` / `land` / `goto` / `hold_position` / `return_home` /
`reduce_speed` / `maintain_heading` / `hover` / `land_safe`。

对地面车：

| 动作 | 地面车含义 |
| --- | --- |
| `takeoff` / `land` | **无意义** |
| `hold_position` | ✅ 直接映射：`cmd_vel` 全零 |
| `reduce_speed` / `maintain_heading` | ✅ 语义天然匹配 |
| `goto` | 需要闭环导航（或交给 `move_base`） |
| `return_home` | 需自己记起点 + 闭环 |

**两个选项**：
- **B1**：不改代码，**用能力注册表裁剪** —— 新增一个 `ugv` 后端档案，把 `takeoff`/`land` 标为
  `supported_adapters: []`（现有字段已支持），策略门自然拒绝
- **B2**：新增地面车专属动作（`drive_velocity`、`drive_to`、`stop`）

**我倾向 B1 先做**（零代码改动、可立即验证），B2 作为后续扩展。

---

## 五、时间压力与优先级

我们现在的时间比较紧，验收场景可能**只能把车架空看轮子转**，不能自由跑。
所以请你按这个优先级给出意见：

| 优先 | 事项 | 为什么急 |
| --- | --- | --- |
| **P0** | 缺口 3（host/port 可配置）+ `ALLOWED_ORIGINS` 支持 IP | **卡住 3~6 台 weier 的集群方案**；改动只有几行 |
| **P0** | 缺口 7（10053） | 稳定性 + 日志可读，已确认根因 |
| **P1** | 缺口 1（ROS 接入，走 A1 最小子集：能发 `/cmd_vel` + 读 `/scout_status`） | **没有它，Runtime 完全碰不到这台真车** |
| **P2** | 缺口 2（载荷真数据） | 验收若问"相机/雷达数据"会用到 |
| **P3** | 缺口 5（智能层） | 需要先定架构归属 |
| **P4** | 缺口 4、6（多实例协同、算法接入） | 需要和算法侧一起定 |

---

## 六、希望你的回复包含

1. **上次合并之后你做了什么**（已合并 / 未合并，各是什么）
2. **第三节 7 个缺口逐条状态**（用〇节那张表的五个选项）
3. **第四节 A、B 两个设计问题的意见**（尤其 A1 是否可行 —— 你怎么看"Runtime 零改动"这个思路）
4. **P0 两项能不能很快给出来**（时间估计即可，不用承诺日期）
5. **有没有你正在改、我们不能碰的部分**（避免冲突）

---

## 附：我们这边可以立刻配合的

- 需要 UGV 侧任何 ROS 数据（`rostopic info`、消息定义、频率、样本），我们现场去抓
- 需要我们在离线上做任何验证（Windows / Jetson / weier 三平台都可以）
- 需要 `wsl --export` 的仿真环境镜像，我们可以准备

**你先回〇节和第一节就行，其余可以慢慢来。**
