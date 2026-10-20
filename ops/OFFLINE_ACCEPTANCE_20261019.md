# 离线环境验证结果（2026-10-19）

**验证地点**：无网环境，中间笔记本（Windows）
**被测包**：`offline-batch2`（源码 `main` @ `e586a5f`）
**执行人**：现场操作

---

## 结论：**前端两模块 + Runtime 在无网环境全部跑通**

| # | 验证项 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | `01-source.tar.gz` 解压正确 | ✅ | `D:\uavswarm` 下 `src\` `frontend\` `ops\` `config\` 齐全 |
| 2 | **pymavlink 离线安装** | ✅ | `Successfully installed fastcrc-0.5.0 pymavlink-2.4.50`（lxml 已满足） |
| 3 | pymavlink 导入 | ✅ | `python -c "import pymavlink,fastcrc,lxml.etree;print('ok')"` → `ok` |
| 4 | **Runtime 启动** | ✅ | `uav_runtime_http_bridge listening on http://127.0.0.1:8765/api` |
| 5 | **主控台 5178 显示** | ✅ | 现场截图 |
| 6 | **三维 5179 渲染** | ✅ | 现场截图（城市网格 + 载具标牌可见） |
| 7 | 前后端跨域（5178 → 8765） | ✅ | `ALLOWED_ORIGINS` 含 `http://127.0.0.1:5178`，无需额外配置 |

**这一批的目标（"证明浏览器能渲染出界面和三维，并能连上 Runtime"）已达成。**

---

## 补充：Runtime 的能力在无硬件条件下也能被验证（实测）

部署成功只证明"能启动"。**Runtime 的真正价值（策略裁决 / 审计 / 回放）
可以在没有 PX4、没有飞机的情况下用 CLI 验证** —— 以下命令均已实测通过。

> 说明：这一路径的"执行"是 `adapter: "fake"`、`detail: "simulated"`，
> **没有真机动作**。它证明的是**治理链路**，不是飞行能力。

### 1. 列出能力注册表

```bash
PYTHONPATH=src python3 -m uav_runtime.console.cli list-capabilities --pretty
```

返回每个动作的 `risk_level` / `allowed_link_states` / `policy_default` /
`requires_confirmation_by_default` / `supported_adapters`。

### 2. 策略门确实会拒绝（实测对照）

```bash
PYTHONPATH=src python3 -m uav_runtime.console.cli submit-action land \
  --demo-link-state lost --pretty
```

| 场景 | `decision_code` | `status` | 理由码 |
| --- | --- | --- | --- |
| `land` @ healthy | `allow` | `accepted` | — |
| `land` @ degraded | `allow` | `accepted` | — |
| **`land` @ lost** | **`deny`** | **`blocked`** | `REASON_CODE_LINK_LOST_NON_FALLBACK_DENIED` + `REASON_CODE_LINK_LOST_SCOPE_RESTRICTED` |
| `goto` @ healthy | `allow` | `accepted` | — |
| **`goto` @ lost** | **`deny`** | **`blocked`** | 同上 |

**这是"策略门不是装饰"的直接证据** —— 链路丢失时动作被挡下，并给出结构化理由码。

### 3. 审计落盘（每次动作 2 条记录）

```
audit/runtime.audit.jsonl
  1: {"type": "policy_decision_event", "action_type": "takeoff"}
  2: {"type": "action_result",        "status": "accepted"}
```

每条含 `policy_trace_id` / `request_id` / `audit_tags`
（拒绝时是 `["policy","deny","link_lost","fallback_required"]`）。

### 4. 回放

```bash
PYTHONPATH=src python3 -m uav_runtime.console.cli replay-last --pretty
```

### 这一节的意义

**"Runtime 部署成功"和"Runtime 有效果"是两件事**：

* 部署成功 = 进程起来了、HTTP 通了、前端连上了 → **本轮已证明**
* 有效果 = 策略裁决、审计、回放能产生可检查的输出 → **本轮用 CLI 已证明**
* **仍未证明** = 真实载具上的遥测 / 动作 / 完成判据 → **需要连 PX4 或真机**

---


### 环境实测

```
Windows 10 专业版 build 18363
Python        : C:\Users\E470\anaconda3\python.exe (3.13.9)
GPU           : Intel(R) UHD Graphics 620（驱动 2018-02-28，仅核显）
浏览器        : Firefox
Node          : 未安装 —— 不需要（三维用已构建的 dist）
```

> **⚠️ 值得注意**：这台是 Intel 核显 + 2018 年驱动，**三维仍然渲染出来了**。
> 我之前把它列为"最大技术风险点"，实测证明可接受（虽然流畅度未量化）。

---

## 发现一个缺陷：`WinError 10053` traceback（不阻塞，但该修）

### 现象

Runtime 运行期间，只要**关闭或刷新前端页面**，控制台就刷出成对 traceback：

```
Exception occurred during processing of request from ('127.0.0.1', 62649)
...
  File "src\uav_runtime\http\server.py", line 59, in _handle_json_request
    self._send_json(status, payload)
  File "src\uav_runtime\http\server.py", line 83, in _send_json
    self.wfile.write(body)
ConnectionAbortedError: [WinError 10053] 你的主机中的软件中止了一个已建立的连接。

During handling of the above exception, another exception occurred:   ← 关键

  File "src\uav_runtime\http\server.py", line 63, in _handle_json_request
    self._send_json(500, {"error": "internal_error", "detail": type(exc).__name__})
  File "src\uav_runtime\http\server.py", line 81, in _send_json
    self.end_headers()
ConnectionAbortedError: [WinError 10053] ...
```

### 根因（已定位到三行）

```python
# src/uav_runtime/http/server.py:56-63
try:
    status, payload = dispatch(...)
    self._send_json(status, payload)        # 第 59 行：客户端已断开 → 抛 ConnectionAbortedError
except json.JSONDecodeError:
    self._send_json(400, ...)
except Exception as exc:
    self._send_json(500, {"error": "internal_error", ...})   # 第 63 行：**又往死 socket 写 500**
```

**"客户端断开"被当成"服务端内部错误"处理，于是往一个已经断开的连接上再写一次错误响应。**

### 触发条件

前端 `runtime-api.js` 每 2 秒轮询，单次超时 2.5 秒。
**关闭/刷新页面时，浏览器 `AbortController` 会掐断所有在途请求** → 服务端 `wfile.write` 抛 10053。
所以这个 traceback **日常操作就会触发**，不是极端情况。

### 影响

| | |
| --- | --- |
| 服务器 | ✅ 不崩（`ThreadingHTTPServer`，每请求独立线程） |
| **查询请求** | ❌ 该次响应丢失（前端 2 秒后重试，无害） |
| **动作请求** | ⚠️ **见下方第 ③ 条纠正 —— 不能假定"动作未发生"** |
| **日志可读性** | ❌ **严重污染** —— 真正的 500 会被这个噪音淹没 |
| 现场观感 | ⚠️ 容易被误认为系统故障 |

### 最小修复（2 处，共 6 行）

```python
# ① server.py:82-83 —— 写 body 时忽略"对端已断"
        try:
            if body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return          # 客户端走了，没什么可回应的

# ② server.py:62 之前插入 —— 别把"对端已断"当 500
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:
            self._send_json(500, ...)
```

> **`.py` 文件可以用记事本改** —— Python 能正常处理 CRLF。
> （只有 `.sh` 不能，见 `ops/README.md` 的行尾约定。）

**归属**：`src/uav_runtime/` 是 Runtime 负责人的模块，补丁需经其确认后再合入。
**本次未改代码。**

---

## Runtime 负责人的复核意见（2026-10-20）

> 负责人已完成阅读与代码核对，**未改代码、未跑测试**。

### 结论

| 项 | 复核结果 |
| --- | --- |
| 离线界面部署验证 | ✅ **成功** |
| 断连异常归属 | ✅ **属于 Runtime**，**当前仍未修复** |
| 根因判断 | ✅ **正确**：`server.py` 把响应写入失败当成内部错误，又向断开的连接发送 500，产生第二次 traceback |
| 补丁方向 | ⚠️ **对但不完整** —— 见下面三条 |

### ① 补丁必须覆盖完整的响应发送过程

不能只保护 `wfile.write(body)`。**响应头、响应体，以及 `400` / `500` / `OPTIONS` 响应都可能遇到断连。**

所以上面的"改动 1"不够 —— `self.end_headers()`（含 `flush_headers`）同样会抛
`ConnectionAbortedError`（现场 traceback 里就有这一条：
`http\server.py:542 in flush_headers → self.wfile.write(...)`）。

**正确的做法**：把**整个响应发送过程**（`send_response` / `send_header` / `end_headers` / `wfile.write`）包在同一个断连保护里，而不是只护最后一步。

### ② 异常处理必须限定在 HTTP 读写处

**不能**用一个宽泛的 `except` 把执行器内部的连接故障一起吞掉。

原因：`dispatch()` 里会走到 adapter / MAVLink 会话。
那里的 `ConnectionAborted` 类异常**可能是"飞控连接断了"这种真实故障**，
如果被同一层 `except` 静默忽略，**策略与审计就丢掉了关键信号**。

**正确的做法**：
- 只在 **HTTP 层读写 socket** 的位置捕获断连异常
- **执行器 / adapter 抛出的异常必须继续上报**（走 500，并保持 `detail` 可见）

### ③ ⚠️ 「请求丢失、前端重试」只适用于**查询请求**

**这是安全语义问题，必须改口径。**

| 请求类型 | 响应丢失时的正确语义 |
| --- | --- |
| **查询**（GET `/api/health`、`/api/vehicle-snapshot` 等） | 响应丢失 = 没拿到数据，**前端重试即可**，无副作用 |
| **动作**（POST `/api/actions/takeoff`、`land`、`goto`、`return-home`） | **响应丢失 ≠ 动作未发生。动作可能已经执行了。** |

**对动作请求的正确处理**：
1. **不得**把"没收到响应"当成"动作没有发生"，**更不得据此重发**
2. 应通过**原请求标识**（`request_id`）**查询**该动作的真实结果
3. 或者使用**幂等重试**（同一 `request_id` 重复提交，由幂等检查拦掉第二次执行）
4. 只有确认该 `request_id` 未被执行，才允许重新发起

**这条对飞行安全是硬要求** —— "以为没飞，其实已经飞了"是最危险的一类误判。

> 本报告原文"请求丢失（前端 2 秒后重试）"的表述**仅适用于查询请求**，
> 对动作请求是错的，已按此纠正。

### 归属与状态

* 缺陷**仍在**，未修复（本轮只做阅读和代码核对）
* 修复应同时满足上面三条，**不能只按 ① 改**
* 本仓库**未提交任何 Runtime 代码改动**


---

## 尚未验证（下一轮）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| **真机链路** | ❌ | 只验过 SITL；真机走数传/串口，地址与 `sysid`/`compid` 需重配 |
| **仿真后端（PX4 + Gazebo）** | ❌ | 需 Linux + 独显。**我方代码在仓库里**（`simulation/px4_gazebo/`，18 文件 684 KB）；**PX4 与 Gazebo 是第三方，需另装** |
| **`goto` 到达语义** | ⚠️ | 已知未通过（到过 2.9 m 又漂到 37 m），见 `ACCEPTANCE_UAV02_FLIGHT_20261012.md` |
| **站点符合性** | ❌ | 无 `validated` 生产者，站点证据链未闭环 |
| **三维流畅度** | ⚠️ | 能渲染，但未量化帧率（Intel UHD 620 + 2018 驱动） |
| **改前端代码后重建** | ❌ | 需解开 `03-node_modules` + `05-node`，未实测 |
| **Runtime 动作在真机上的端到端** | ❌ | 需先解决本报告记录的 10053 缺陷（含动作语义口径） |

---

## 仿真：哪些是仓库里的代码，哪些要另外下载

**结论：编排/标定/验收/证据链的代码全在仓库里；PX4 与 Gazebo 是第三方，必须在有网机器上装。**

### 仓库内（`simulation/px4_gazebo/`，18 个文件 / 684 KB）

```
harness.py               仿真编排入口（起停、健康、场景）
health.py                健康检查
calibration.py           标定采样
ground_reference.py      地面参考（#88 的核心成果）
evidence.py              证据链
gazebo_evidence.py       Gazebo 侧证据
runtime_evidence.py      Runtime 侧证据
patrol.py                巡逻
config/three_uav_sitl.json            默认版
config/three_uav_mono_cam_sitl.json   相机版（三维视图需要）
scripts/start_three_uav.sh · stop_three_uav.sh
scripts/health_three_uav.py · patrol_three_uav.py
scripts/sample_calibration.py · validate_three_uav.py · verify_three_uav_cameras.py
```

**世界文件也在仓库里**：`scenarios/simple_recon_v0_1/worlds/simple_recon_v0_1.sdf`

### 仓库外（第三方，必须另装）

| 组件 | 来源 | 实测基线 |
| --- | --- | --- |
| **PX4-Autopilot** | `git clone --recursive` + 编译 | `171f0f38cf` (2026-06-25)，3.3 GB，编译产物 SITL 二进制 57.9 MB |
| **Gazebo** | apt（OSRF 仓库） | `gz sim 8.14.0` |
| PX4 工具链 | apt（`Tools/setup/ubuntu.sh`） | gcc-arm-none-eabi / cmake / ninja 等 |

**离线搭建路线见 `ops/MIGRATION_OFFLINE_20261014.md` 第七节**
（推荐路线 A：目标机先联网装一次；路线 B：Docker 镜像搬迁）。

---


## 关键经验（写下来防复发）

1. **`pymavlink` 有依赖**：`fastcrc` + `lxml`。第一版包用 `--no-deps` 漏了 `fastcrc`，
   现场报 `Could not find a version that satisfies the requirement fastcrc`。已修。
2. **必须区分 shell**：cmd.exe 没有 `python3` / `&` / `$env:` / `ls`。
   现场前几次失败全部源于此（`python3` 不存在、`$env:PYTHONPATH` 语法错、`ls` 不存在）。
3. **`01-source` 不含 `dist/`**：三维构建产物在 `02` 里，必须解到 `simulation-3d` 下，
   否则 5179 是 404。
4. **`set PYTHONPATH=%CD%\src` 是两条命令**：漏了 `set` 就是 `ModuleNotFoundError`。
5. **`--find-links` 是相对当前目录**：已在 `wheelhouse` 里时要用 `.`，否则报 `Location ignored`。
6. **Intel 核显也能渲染三维**：2018 年驱动的 UHD 620 实测可用，风险低于预估。

---

## 下一步建议

| 优先级 | 事项 | 谁 |
| --- | --- | --- |
| **1** | 把 `WinError 10053` 的 6 行补丁报给 Runtime 负责人 | 集成侧 |
| **2** | 在 **Linux + 独显台式机** 上重复一次前端验证（架构不同、字体渲染不同） | 现场 |
| **3** | 决定仿真走哪条路（该机能否先联网一次 / Docker） | 你 |
| **4** | 真机链路：确定承载方式（数传/串口/UDP）与实际地址 | Runtime + 你 |
