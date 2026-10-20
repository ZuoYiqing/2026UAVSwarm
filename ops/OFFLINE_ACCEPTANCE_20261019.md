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
| 那一次请求 | ❌ 丢失（前端 2 秒后重试） |
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

## 尚未验证（下一轮）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| **真机链路** | ❌ | 只验过 SITL；真机走数传/串口，地址与 `sysid`/`compid` 需重配 |
| **`goto` 到达语义** | ⚠️ | 已知未通过（到过 2.9 m 又漂到 37 m），见 `ACCEPTANCE_UAV02_FLIGHT_20261012.md` |
| **站点符合性** | ❌ | 无 `validated` 生产者，站点证据链未闭环 |
| **仿真（PX4 + Gazebo）** | ❌ | 需 Linux + 独显；离线搭建走 `MIGRATION_OFFLINE_20261014.md` 第七节 |
| **三维流畅度** | ⚠️ | 能渲染，但未量化帧率（Intel UHD 620 + 2018 驱动） |
| **改前端代码后重建** | ❌ | 需解开 `03-node_modules` + `05-node`，未实测 |

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
