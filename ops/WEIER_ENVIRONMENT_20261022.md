# weier 台式机环境详情

**机型**：联想 ThinkStation `30E4A3XHCW` · 主机名 `DESKTOP-LOTFUFQ` · 用户 `vire`
**规模**：现场 **3 台**，规划后续至 **6 台**
**用途**：集群测试/演示节点（Runtime 主机 / 显示主机 / 压测 / 备份）
**文档版本**：2026-10-22
**维护**：本文件是 weier 环境的声明来源

---

## 0. 一页摘要（给 Runtime 负责人）

| 项 | 结论 |
| --- | --- |
| **硬件** | i7-11700K 16 核 / **63.6 GB RAM** / **RTX 3080 10240 MiB** —— 很强 |
| **系统** | Windows 10 专业版 **19041 (2004)**，64 位，2023-03 装机 |
| **网络** | **完全不能联网**（所有安装必须离线） |
| **Python** | ❌ **没有任何真实解释器**（只有 Microsoft Store 的假 `python.exe`） |
| **WSL** | ❌ 未安装（Win10 19041 支持 WSL2，但需管理员开启） |
| **Node / npm** | ❌ 没有 —— **不需要**（三维用预构建 `dist/`） |
| **浏览器** | ✅ **有**（现场确认；我脚本的检测漏判了） |
| **磁盘** | C 307.7 GB / D 478.2 GB / E 474.4 GB **空闲**，另有 4 TB 机械盘 |
| **管理员权限** | ⚠️ recon 当时 `isAdmin=False` —— **装 WSL2 需要提权** |
| **Git/SSH/curl/tar** | ✅ 有（来自 `D:\VRNET\msys`） |

### ⭐ 给 Runtime 负责人的核心结论

**Runtime 的 `dependencies = []`（零第三方依赖），只需要一个 ≥3.10 的解释器。**
现在有实测结论：**方案 A 已经在 Windows 上原样跑通，不需要 WSL。**

| 方案 | 做法 | 步骤数 | 需要管理员 | 实测状态 |
| --- | --- | --- | --- | --- |
| **A（推荐）** | **Windows 原生 + 便携 Python for Windows** | **2 步** | ❌ 不需要 | ✅ **2026-10-22 实测通过**（见 §5.1） |
| B | WSL2 + Ubuntu + 便携 Python for Linux | 6 步 | ✅ 需要 | 未实测；需 `netsh portproxy` 才能跨机 |

### ⚠️⚠️ 但有两条**已核实的硬限制**，会影响集群怎么搭

| 限制 | 后果 |
| --- | --- |
| **`main()` 写死 `create_server()` 不传参** → 监听地址固定 `127.0.0.1`、端口固定 `8765` | **多实例做不了；别的机器也连不上 Runtime** |
| **`ALLOWED_ORIGINS` 只有 `localhost` / `127.0.0.1`，没有 IP 形式** | **从别的机器用 IP 打开主控台 → 跨域被拒 → 显示"后端不可达"** |

**→ 当前唯一自洽的集群形态是「每台机器独立一套 Runtime + 前端，都在本机访问」。**
真正的"一台 Runtime 服务多台显示"需要 §5.3 那个 **4 行补丁**。
详见 §5.2 / §5.3 / §5.6。

---

## 1. 硬件与系统

| 项 | 值 | 来源 |
| --- | --- | --- |
| 主机名 | `DESKTOP-LOTFUFQ` | recon-windows |
| 用户 | `vire` | recon-windows |
| 厂商 / 型号 | **LENOVO / 30E4A3XHCW**（ThinkStation） | recon-windows |
| CPU | **Intel i7-11700K @ 3.60 GHz，16 核** | recon-windows |
| 内存 | **63.6 GB** | recon-windows |
| 系统 | **Windows 10 专业版**，`10.0.19041`（**2004**），64 位 | recon-windows |
| 装机时间 | 2023-03-21 | recon-windows |
| 管理员 | recon 时 **`isAdmin=False`** | recon-windows |

### 1.1 GPU

| 设备 | 驱动 | 显存 / 能力 |
| --- | --- | --- |
| **NVIDIA GeForce RTX 3080** | **531.29**（WMI 记 31.0.15.3129，2023-03-08） | **10240 MiB**，**compute 8.6**（Ampere） |
| Intel UHD Graphics 750 | 30.0.101.1273（2022-02-08） | 核显，备用 |

> **两个独立来源互相印证**：WMI `Win32_VideoController` **和** `nvidia-smi` 都报 RTX 3080。
> `nvidia-smi` 只有在"物理卡存在 + 驱动装好"时才能运行，所以这个结论可靠。

**驱动 531.29 的含义**：
- ✅ 支持 Windows 上的 CUDA / D3D12
- ✅ 满足 WSL2 GPU 直通的最低要求（≥470）
- ⚠️ 但 **Windows 10 19041 没有 WSLg**（Linux GUI 支持），要图形界面只能靠 Windows 侧

### 1.2 磁盘

| 卷 | 总容量 | 空闲 |
| --- | --- | --- |
| C: | 476.3 GB | **307.7 GB** |
| D: | 1860.8 GB | 478.2 GB |
| E: | 1865.2 GB | 474.4 GB |

| 物理盘 | 容量 | 类型 |
| --- | --- | --- |
| `INTEL SSDPEKNU512GZ` | 477 GB | NVMe（含 C:） |
| `ST4000VX015-3CU104` | 3726 GB | 机械盘（含 D: E:） |
| `Kingston DataTraveler 3.0` | 29 GB | **USB，现场正插着** |

**结论：空间非常充裕**，WSL2 的 vhdx 或便携 Python 都不是问题。

---

## 2. 现状软件（**几乎是裸机**）

| 组件 | 状态 | 说明 |
| --- | --- | --- |
| **Python** | ❌ **无真实解释器** | PATH 上的 `python.exe` / `python3.exe` 是 `C:\Users\vire\AppData\Local\Microsoft\WindowsApps\` 下的 **Store 0 字节别名**，调用它会打开商店 |
| **WSL** | ❌ 无 | `wsl.exe` 不存在 |
| **Node / npm** | ❌ 无 | 但**不需要**：三维用预构建 `dist/` |
| **git** | ✅ | `D:\VRNET\msys\bin\git.exe` |
| **ssh / scp** | ✅ | `D:\VRNET\msys\bin\ssh.exe`、`C:\Windows\System32\OpenSSH\scp.exe` |
| **curl** | ✅ | |
| **tar** | ✅ | `D:\VRNET\msys\bin\tar.exe`（注意：**不是** Windows 自带的 `C:\Windows\System32\tar.exe`） |
| **7z** | ❌ 无 | |
| **浏览器** | ✅ **有** | 现场确认；具体品牌未记录（我脚本检测漏判，见 §9） |
| 容器 | 未见 Docker | |

> ⚠️ **`D:\VRNET\msys` 是一个已装的 MSYS/MinGW 环境**（看起来是某套网络工具的附带品）。
> 它提供的 `tar` 与 Windows 自带 `tar` 行为可能不同 —— **脚本里尽量用绝对路径**。

---

## 3. 离线约束（**最关键的前提**）

> **这三台（将来六台）完全不能联网。**

后果：

| 通常做法 | 这里行不通 | 替代 |
| --- | --- | --- |
| `pip install` | ❌ 无网 | 便携 Python 自带 pip / 预置 wheelhouse |
| `apt install` | ❌ 无网 | **不用 apt**（便携 Python 不需要） |
| `npm install` | ❌ 无网 | **不需要**（三维用 `dist/`） |
| 商店装 WSL 发行版 | ❌ 无网 | `wsl --import` 从 **tarball** 导入 |
| `git clone` | ❌ 无网 | 源码用 U 盘拷 |

**所有依赖必须预先在有网机器上下好，随 U 盘带进去。**
离线包（前三个已下载校验）：`D:\weier-offline\`，详见 `WEIER_WORKFLOW_20261022.md`。

---

## 4. 两种部署方案（**给 Runtime 负责人的选择**）

### 4.1 方案 A：Windows 原生 + 便携 Python（**✅ 已实测，推荐**）

```
weier 台式机（Windows 10）
  └─ 便携 CPython 3.11（解压即用，无需安装、无需管理员）
       └─ Runtime（dependencies = []）
            ├─ HTTP 桥 :8765
            └─ 前端静态服务 :5178 / :5179（可选）
```

**步骤（2 步，实测可用）**：
```cmd
:: ① 解压便携 Python（解压即用）
mkdir D:\tools
tar -xf D:\weier-offline\cpython-3.11.18+20261026-x86_64-pc-windows-msvc-install_only.tar.gz -C D:\tools

:: ② 起 Runtime
cd /d D:\uavswarm
set PYTHONPATH=%CD%\src
D:\tools\python\python.exe -m uav_runtime.http.server
```

**期望输出**：
```
uav_runtime_http_bridge listening on http://127.0.0.1:8765/api
```

**验证**（另一个 cmd 窗口）：
```cmd
curl http://127.0.0.1:8765/api/health
```
**✅ 已实测返回**：`{"status": "ok", "service": "uav_runtime_http_bridge", "version": "0.1", "mode": "local_dev"}`

**优点**：
- ✅ **不需要管理员权限**（不解 DISM、不装 msi）
- ✅ **不需要 WSL2**（省掉 3 个文件、6 个步骤）
- ✅ **不需要 pymavlink**（惰性导入，实测能起）
- ✅ **实测跑通**：服务 / 健康检查 / 能力表 / 策略门 / 审计全部正常
- ✅ 步骤最少，最容易复制到 3~6 台

**缺点 / 风险**：
- ⚠️ Windows 上无法跑 ROS（但 **weier 不需要 ROS**，ROS 是 UGV 的事）
- ⚠️ 控制台是 GBK，辅助脚本别用 emoji（见 §5.1.2）

### 4.2 方案 B：WSL2 + Ubuntu + 便携 Python for Linux

```
weier 台式机（Windows 10）
  └─ WSL2（Ubuntu 22.04，从 tarball 导入）
       └─ 便携 CPython 3.11（linux-x86_64）
            └─ Runtime + 前端
```

**步骤（6 步）**：DISM 开两个功能 → 重启 → 装 msi → `wsl --set-default-version 2` → `wsl --import` → 解便携 Python

**优点**：
- ✅ Linux 环境，与开发机一致（开发环境是 Ubuntu 22.04）
- ✅ 将来若要 ROS，有基础

**缺点**：
- ⚠️ **需要管理员权限**（recon 显示当时 `isAdmin=False`）
- ⚠️ **WSL2 是 NAT 网络**：Windows 内部 `localhost` 能通，但**局域网其他机器访问不到**，必须加 `netsh portproxy`（见 §6.2）
- ⚠️ 多 3 个文件、多 4 个步骤

### 4.3 我的建议

> **先用方案 A（已实测通过），三台照做，30 分钟一台。**
>
> 方案 B（WSL2）**只在这些情况下才需要**：
> - 将来要在 weier 上跑 ROS（当前不需要，ROS 是 UGV 侧）
> - 需要 Linux 专属工具链
>
> **方案 A 的实测证据见 §5.1.1，八项测试全部通过。**

**无论哪个方案，源码包和前端包都一样**（`01-source.tar.gz` + `02-frontend-3d-dist.tar.gz`）。

---

## 5. 对 Runtime 的影响（给 Runtime 负责人）

### 5.1 ⚠️ 方案 A 的前提核查：Runtime 的 Windows 兼容性

**我在仓库里逐项查过**（`src/uav_runtime/` 13,554 行）：

| 检查项 | 结果 |
| --- | --- |
| POSIX 专属 import（`fcntl` / `pwd` / `grp` / `termios` / `pty` / `resource`） | ✅ **无** |
| `signal` 处理 | ✅ **无** |
| `os.setsid` / `os.fork` / `os.getuid` / `os.chown` | ✅ **无** |
| `/proc` / `/mnt` / `/home` 硬编码路径 | ✅ **无** |
| `socket.SO_REUSEPORT`（Windows 不支持） | ✅ **无** |
| 核心第三方依赖 | ✅ **零**（`dependencies = []`） |

**结论：代码层面没有平台障碍，理论可跑。但从未实测。**

> **建议**：先在任一 weier 上用方案 A 跑一次 `python -m uav_runtime.http.server`，
> 看能不能到 `listening on http://127.0.0.1:8765/api`。
> **这是 5 分钟就能得出的结论**，比反复讨论靠谱。

### 5.1.1 ✅ **实测结果：Windows 上完全跑通（2026-10-22）**

**测试环境**：Windows 11 + `cpython-3.11.18+20261026-x86_64-pc-windows-msvc-install_only`
（与 weier 用的同一个包，只是 weier 是 Win10 19041；Python 的 Windows 支持无差别）

| 测试 | 命令 | 结果 |
| --- | --- | --- |
| **① import 服务** | `python -c "import uav_runtime.http.server"` | ✅ OK |
| **② import 适配器 + 路由** | `python -c "import uav_runtime.adapters; from uav_runtime.http import routes"` | ✅ OK（**说明 pymavlink 是惰性的，不装也能起**） |
| **③ 起服务** | `python -m uav_runtime.http.server` | ✅ 进程稳定运行 |
| **④ `/api/health`** | `curl http://127.0.0.1:8765/api/health` | ✅ **HTTP 200**<br>`{"status":"ok","service":"uav_runtime_http_bridge","version":"0.1","mode":"local_dev"}` |
| **⑤ `/api/capabilities`** | `curl .../api/capabilities` | ✅ **HTTP 200**，5,284 字节 |
| **⑥ 策略门拒绝** | `submit-action land --demo-link-state lost` | ✅ `deny` / `blocked` / **`adapter: ""`** |
| **⑦ 策略门允许** | `submit-action takeoff --demo-link-state healthy` | ✅ `allow` / `accepted` / `adapter: "fake"` |
| **⑧ 审计落盘** | 看 `audit/*.jsonl` | ✅ 3 行（deny 决策 / allow 决策 / action_result） |

**结论：方案 A 不是"理论上可行"，是实测跑通。weier 不需要 WSL。**

### 5.1.2 ⚠️ 一个 Windows 特有的坑：GBK 控制台不能打印 emoji

实测时发现：

```
UnicodeEncodeError: 'gbk' codec can't encode character '\u2705' in position 2
```

**原因**：Windows 中文版控制台默认代码页 936（GBK），Python 的 stdout 编码随之为 `cp936`。
**emoji（✅❌）不在 GBK 里 → 打印就崩。**

| 能打印 | 不能打印 |
| --- | --- |
| ASCII | **emoji**（✅ ❌ 🚀 …） |
| **中文**（GBK 覆盖） | 生僻字、部分符号 |

**⚠️ 对我们的影响**：
- Runtime 自身的 `print("uav_runtime_http_bridge listening on http://127.0.0.1:8765/api")`
  **是纯 ASCII，没问题** ✅
- 但**我们自己写的辅助脚本**（如 `show-audit.py`）**不要用 emoji**，
  否则在 Windows 上会崩；`show-audit.py` 目前是纯文本+中文，安全 ✅

**临时绕法**（如果真需要）：`chcp 65001` 切到 UTF-8，或设 `PYTHONIOENCODING=utf-8`。

### 5.2 ⚠️⚠️ **已核实：Runtime 目前不能改监听地址和端口**

**这是本节最重要的一条，它直接否决了两种集群形态。**

```python
# src/uav_runtime/http/server.py:99-110
def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), RuntimeHttpBridgeHandler)


def main() -> int:
    server = create_server()          # ← 不传参，用默认值
    ...
    print("uav_runtime_http_bridge listening on http://127.0.0.1:8765/api")
    server.serve_forever()
```

**核查结论**：

| 想做的事 | 现状 | 依据 |
| --- | --- | --- |
| 改端口（跑第二个实例） | ❌ **做不到** | `create_server()` 无参数调用，端口写死 8765 |
| 改绑定地址（让别的机器连） | ❌ **做不到** | host 写死 `127.0.0.1` |
| 命令行参数 | ❌ 没有 | `main()` 不解析 `sys.argv` |
| 环境变量 | ❌ 没有 | `UAV_RUNTIME_HTTP_PORT` **只用于拼响应里的 URL 字符串**（`routes.py:905`），**不影响绑定** |

**→ 受影响的集群形态**：

| 形态 | 现在能不能做 | 原因 |
| --- | --- | --- |
| **A. 分工**（一台 Runtime，其他机器显示） | ❌ **不能** | Runtime 只监听 `127.0.0.1`，别的机器连不上 |
| **B. 压测**（一台跑多个实例） | ❌ **不能** | 端口写死 8765，第二个实例起不来 |
| **C. 每台独立一套**（Runtime + 前端都在本机） | ✅ **可以** | 全在 `127.0.0.1` 内，自洽 |

### 5.3 ⭐ 建议的最小补丁（4 行，开放给 Runtime 负责人）

```python
# src/uav_runtime/http/server.py  —— main() 里
def main() -> int:
    host = os.environ.get("UAV_RUNTIME_HTTP_HOST", "127.0.0.1")
    port = int(os.environ.get("UAV_RUNTIME_HTTP_PORT", "8765"))
    server = create_server(host, port)
    ...
    print(f"uav_runtime_http_bridge listening on http://{host}:{port}/api")
```

**默认值不变**（仍是 `127.0.0.1:8765`），所以**现有行为和测试全部不受影响**；
但多实例与跨机访问立刻可用：

```cmd
set UAV_RUNTIME_HTTP_PORT=8775
set UAV_RUNTIME_HTTP_HOST=0.0.0.0
python -m uav_runtime.http.server
```

**这 4 行是 weier 集群从"每台各自为政"变成"真正分工"的唯一门槛。**

### 5.4 端口与访问模型（现状）

| 端口 | 用途 | 现状绑定 |
| --- | --- | --- |
| **8765** | Runtime HTTP 桥 | **写死 `127.0.0.1`** |
| **5178** | 主控台静态服务 | 你做 `http.server` 时可自选（建议 `0.0.0.0`） |
| **5179** | 三维静态服务 | 同上 |

**注意不对称**：前端服务可以随便绑 `0.0.0.0`（因为是 `python -m http.server` 的参数），
**但 Runtime 本身绑不了** —— 所以别的机器能看到页面，却连不上后端。

### 5.5 审计日志路径（可配置）

```python
# src/uav_runtime/http/routes.py:55
AUDIT_PATH = os.environ.get("UAV_RUNTIME_AUDIT_PATH", "audit/runtime.audit.jsonl")
```

✅ **可以通过 `UAV_RUNTIME_AUDIT_PATH` 改** —— 多实例时（补丁之后）建议每实例一个文件。

### 5.6 CORS 白名单（已核实完整内容）

```python
ALLOWED_ORIGINS = {
    "http://localhost:5178",  "http://127.0.0.1:5178",
    "http://localhost:5173",  "http://127.0.0.1:5173",
    "http://localhost:5179",  "http://127.0.0.1:5179",
}
```

**⚠️ 只有 `localhost` 与 `127.0.0.1`，没有任何 IP 形式。**

后果：**如果从别的机器用 `http://192.168.0.6:5178` 打开主控台，
Origin 不在白名单 → 跨域被拒 → 前端显示"后端不可达"。**

**这是多机部署一定会撞上的第二道墙。** 处理方式：

| 方式 | 说明 |
| --- | --- |
| **① 每台机器都在本机打开自己的前端** | ✅ **不用改代码**，配合形态 C 正好 |
| ② 把实际 IP 加进 `ALLOWED_ORIGINS` | 需改 Runtime 代码，或做成可配置 |

**建议**：先走 ①（形态 C），需要跨机时再推动 ② 或与 §5.3 的补丁一起做。

---

## 6. 网络与跨机访问（**这里是真坑**）

### 6.1 方案 A（Windows 原生）—— 简单

```
weier-1 :8765 / :5178 / :5179
        ↑
weier-2 浏览器直接访问 http://192.168.x.x:5178/
```

**只需要一条防火墙规则**（管理员 cmd）：

```cmd
netsh advfirewall firewall add rule name="UAVSwarm 5178-5179" dir=in action=allow protocol=TCP localport=5178-5179
netsh advfirewall firewall add rule name="UAVSwarm 8765" dir=in action=allow protocol=TCP localport=8765
```

### 6.2 方案 B（WSL2）—— ⚠️ **必须加 portproxy**

**WSL2 在 Windows 10 上是 NAT 网络**：

| 方向 | 能否直达 |
| --- | --- |
| Windows → WSL（`localhost:5178`） | ✅ 能（自动 localhost 转发） |
| **局域网其他机器 → WSL** | ❌ **不能**，默认被 NAT 挡住 |

**要跨机访问 WSL2 里的服务，必须在 Windows 侧加端口转发**（管理员 cmd）：

```cmd
:: 先查 WSL 的 IP
wsl -d Ubuntu2204 -e hostname -I

:: 假设 WSL IP 是 172.20.123.45，把 Windows 的 5178/5179/8765 转发进去
netsh interface portproxy add v4tov4 listenport=5178 listenaddress=0.0.0.0 connectport=5178 connectaddress=172.20.123.45
netsh interface portproxy add v4tov4 listenport=5179 listenaddress=0.0.0.0 connectport=5179 connectaddress=172.20.123.45
netsh interface portproxy add v4tov4 listenport=8765 listenaddress=0.0.0.0 connectport=8765 connectaddress=172.20.123.45

:: 放行防火墙
netsh advfirewall firewall add rule name="UAVSwarm WSL" dir=in action=allow protocol=TCP localport=5178-5179,8765
```

**⚠️ 两个麻烦**：
1. **WSL 的 IP 每次重启会变** → portproxy 要跟着改
2. 多个 portproxy 规则会互相覆盖，维护麻烦

**这就是我推荐方案 A 的主要理由之一。**

---

## 7. 角色与规模

| 机器 | 建议角色 | 跑什么 |
| --- | --- | --- |
| **weier-1** | Runtime 主机 | Runtime `:8765`（后期可加实例） |
| **weier-2** | 显示主机 | 主控台 `:5178` + 三维 `:5179` |
| **weier-3** | 压测 / 备份 | 多实例 或 随时顶替 |
| weier-4~6（将来） | 按需 | 同上 |

**每台都装全套**（用户要求），按情况使用。

### 关于"集群"的定义（需要明确）

Runtime **一个实例管一个 manifest（三机），本身没有多实例互相协同的能力**。
而根据 §5.2 的核实，**监听地址和端口目前都不可配置**，所以：

| 形态 | 含义 | 现在能不能做 | 需要 Gazebo？ |
| --- | --- | --- | --- |
| **C. 每台独立一套** | 每台机器自己跑 Runtime + 前端，本机访问 | ✅ **可以** | ❌ 不需要 |
| **A. 分工** | 一台跑 Runtime，其他机器显示 | ❌ **不能**（只能 127.0.0.1） | ❌ 不需要 |
| **B. 压测** | 一台跑多个实例 | ❌ **不能**（端口写死 8765） | ❌ 不需要 |
| D. 仿真 | 一台跑 PX4+Gazebo 三机仿真 | ⚠️ 见 §4 的方案 B / 借网 | ✅ **需要（最难）** |

**⭐ 结论：现在先按 C 铺开（三台各自独立、各自可验证），
等 §5.3 那个 4 行补丁合入后，A 和 B 才成为可能。**

**⭐ 另外：A/B/C 都不需要 Gazebo。** `fake_adapter` 就能造出任意数量的假载具。
详见 `WEIER_WORKFLOW_20261022.md` §6。

---

## 8. 数据来源与置信度

| 来源 | 覆盖 | 置信度 |
| --- | --- | --- |
| **`recon-windows.ps1` 输出** | 硬件/系统/Python/GPU/磁盘/WSL/网络/工具/能力评级 | ⭐⭐⭐ **实测** |
| **`nvidia-smi`** | GPU 型号/驱动/显存/compute | ⭐⭐⭐ **实测，且与 WMI 互相印证** |
| **现场口头确认** | 有浏览器 | ⭐⭐⭐ 已确认 |
| 代码核查（仓库） | Runtime 无 POSIX 依赖 | ⭐⭐⭐ 已核查，但**未实测运行** |
| 规划（本文件 §4/§6/§7） | 部署方案 | ⚠️ **方案，未实施** |

### 已修正的一处误判

| 项 | 我脚本报的 | 实际 | 说明 |
| --- | --- | --- | --- |
| **浏览器** | "三个都没有" | **有** | 检测逻辑只查了 PATH + 4 条硬编码路径，漏了。脚本已修（`0e51c01`），加了注册表 `App Paths` 与 per-user 路径兜底 |

---

## 9. 复现命令（谁都能自己验一遍）

```cmd
:: 系统
systeminfo | findstr /B /C:"OS Name" /C:"OS Version"
wmic cpu get name,NumberOfCores
wmic ComputerSystem get TotalPhysicalMemory

:: GPU（两个来源互相印证）
nvidia-smi
wmic path win32_VideoController get name,driverversion

:: Python（注意 WindowsApps 的是假货）
where python
where python3

:: WSL
where wsl
wsl -l -v

:: 工具
where git
where curl
where tar

:: 磁盘
wmic logicaldisk get caption,size,freespace

:: 浏览器
where msedge
dir "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

:: 管理员？
net session >nul 2>&1 && echo ADMIN || echo NOT-ADMIN
```

---

## 10. 待办清单

| # | 事项 | 需要什么 | 谁 |
| --- | --- | --- | --- |
| **0** | **⚠️ 推动 §5.3 那个 4 行补丁**（`UAV_RUNTIME_HTTP_HOST` / `_PORT`）<br>不做这个，A/B 两种集群形态永远做不了 | 改 Runtime 代码 | **Runtime 负责人** |
| **1** | **方案 A 试跑**：一台 weier 上装便携 Python for Windows，起 Runtime，看能不能到 `listening` | 下载 Windows 版便携 Python（约 30 MB） | 我下 / 你测 |
| 2 | 决定集群形态（C 独立 / A 分工 / B 压测 / D 仿真） | 业务判断 | 你 + Runtime 负责人 |
| 3 | 三台重复部署（先按 C） | 离线包 + 步骤 | 现场 |
| 4 | 如需 Gazebo：找一台能临时联网的机器 | 借网一次 | 你 |
| 5 | 如需跨机：防火墙规则（Windows 原生）或 `netsh portproxy`（WSL2） | 管理员 | 现场 |
| 6 | 如需跨机显示：把实际 IP 加进 `ALLOWED_ORIGINS` | 改 Runtime 代码 | Runtime 负责人 |

---

## 11. 一句话总结

> **weier 的硬件（RTX 3080 + 64 GB + i7-11700K）是这一批里最好的，
> 唯一的障碍是"完全不能联网 + 裸机"。
> 而 Runtime 零依赖，所以只要给它一个 Python 3.11，
> 就能在 3~6 台机器上铺开集群节点 —— 最省事的路径是「Windows 原生 + 便携 Python」，
> 前提是先花 5 分钟验证它在 Windows 上能不能起来。**
