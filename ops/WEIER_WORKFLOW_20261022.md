# weier 台式机使用流程（Windows + WSL2 + Runtime + 集群）

**适用机型**：联想 `30E4A3XHCW`（现场 3 台，规划最多 6 台）
**目标**：在**完全不能联网**的条件下，把这些机器变成集群测试/演示节点
**文档版本**：2026-10-22

---

## 0. 先明确这台机器的真实条件

| 项 | 值 | 对方案的影响 |
| --- | --- | --- |
| CPU / RAM | i7-11700K 16 核 / **63.6 GB** | ✅ 跑多实例都不紧张 |
| **GPU** | **RTX 3080 10240 MiB**，驱动 **531.29**，compute 8.6 | ✅ 浏览器三维毫无压力；WSL 里也支持 CUDA/D3D12 直通 |
| 系统 | Windows 10 专业版 **19041 (2004)** | ⚠️ 支持 WSL2，但**没有 WSLg**（无 Linux GUI），只能 headless |
| **网络** | **完全不能联网** | ⚠️ **一切都是离线安装** |
| Python | **没有**（只有 Microsoft Store 的假 python） | 需自带解释器 |
| WSL | **没有** | 需离线装 WSL2 |
| Node | 没有 | **不需要**（三维用预构建 `dist/`） |
| 磁盘 | C 307.7 GB / D 478.2 GB / E 474.4 GB 空闲 | ✅ 非常充裕 |
| 工具 | git / ssh / scp / curl / tar（来自 `D:\VRNET\msys`） | ✅ 够用 |
| 浏览器 | **待确认**（我脚本报"没有"，但 Win10 通常自带 Edge） | ⚠️ 必须先确认 |

**结论：这台硬件极好，唯一的问题全是"离线"造成的。所以第一步不是装，是准备离线包。**

---

## 1. 角色分工（3 台怎么用）

**先说清一件事：`Runtime` 目前一个实例管一个 manifest（三机），
它本身没有"多实例互相协同"的能力。** 所以"集群"有三种形态，选一种：

| 形态 | 谁干什么 | 需要什么 | 推荐度 |
| --- | --- | --- | --- |
| **A. 分工形态** | 一台跑 Runtime，一台跑前端显示，一台做备份/压测 | 只需 Runtime + 前端 | ⭐⭐⭐ **先做这个** |
| **B. 压测形态** | 每台跑 1~3 个 Runtime 实例，各管一批假载具 | 只需 Runtime + fake adapter | ⭐⭐ 验证规模 |
| **C. 仿真形态** | 一台跑 PX4+Gazebo 三机仿真，其余显示/分析 | **需要 Gazebo（最难）** | ⭐ 最后做 |

### 建议的起步安排（形态 A）

| 机器 | 角色 | 跑什么 |
| --- | --- | --- |
| **weier-1** | **Runtime 主机** | Runtime `:8765`（后期再加实例） |
| **weier-2** | **显示主机** | 主控台 `5178` + 三维 `5179`（3080 渲染） |
| **weier-3** | **备用 / 压测** | 同上，或跑第二个 Runtime 实例 |

**好处**：三台机器各自独立可验证，一台出问题不影响结论；**而且完全不需要 Gazebo。**

> ⚠️ **重要判断**：如果你说的"集群"是指**多机协同逻辑、策略、任务分配、界面规模**，
> 那 **不需要 Gazebo** —— Runtime 的 `fake_adapter` 就能造出任意数量的假载具。
> Gazebo 只在需要**真实飞行物理/相机画面**时才必须。
>
> **这一点决定了 weier 能不能"马上开始"和"要等很久"。**

---

## 2. 阶段 A：在有网机器上准备离线包（**必须做一次**）

⚠️ **weier 完全不能联网，所以这些必须在别的地方下好，用 U 盘/移动硬盘拷进去。**

### 2.1 必装清单（约 400 MB）

| 文件 | 从哪拿 | 大小 | 用途 |
| --- | --- | --- | --- |
| **`wsl_update_x64.msi`** | 微软官网搜 "WSL2 kernel update" | ~15 MB | WSL2 内核 |
| **Ubuntu 22.04 rootfs tarball** | `cloud-images.ubuntu.com` 的 WSL rootfs | ~300 MB | WSL 发行版（不走商店） |
| **便携 Python 3.11（linux-x86_64）** | `python-build-standalone` 的 `install_only` 包 | ~30 MB | WSL 里的解释器（**不需要 apt**） |
| **`01-source.tar.gz`** | 我们仓库 | 11 MB | 源码 |
| **`02-frontend-3d-dist.tar.gz`** | 我们仓库 | 11 MB | 三维构建产物 |
| **`04-wheelhouse.tar.gz`** | 我们仓库 | 75 MB | pymavlink（**当前阶段可不带**，见 4.3） |

**⚠️ 不需要**：Node / npm（三维用预构建 dist）、git（离线无网）、pip（便携 Python 自带）。

### 2.2 如果要 Gazebo（阶段 C，先别下）

| 文件 | 大小 | 难度 |
| --- | --- | --- |
| PX4-Autopilot 源码（含子模块） | **3.3 GB** | 中 |
| Gazebo Harmonic + **全部 apt 依赖** | 几 GB | ❌ **极高** |

**建议：阶段 C 先不准备。** 原因见第 6 节。

### 2.3 拷贝方式

3 台机器同一个包。**U 盘 ≥ 8 GB 就够（不含 Gazebo）。**

---

## 3. 阶段 B：在 weier 上离线装 WSL2（**需要管理员**）

### 3.1 确认有没有浏览器（先做这个，1 分钟）

```cmd
where msedge
dir "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

**或者直接双击桌面上的 Edge 图标。**

- **能打开** → 记下它，后面显示用 ✅
- **打不开/没有** → 需要把 Edge 的离线安装包也加入 2.1 清单（约 150 MB）

### 3.2 开启两个 Windows 功能（离线可做）

**以管理员身份**打开 cmd：

```cmd
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
```
```cmd
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

**然后重启**（必须重启，否则下一步无效）。

### 3.3 装 WSL2 内核

```cmd
wsl_update_x64.msi
```

**或者命令行静默装**：
```cmd
msiexec /i wsl_update_x64.msi /qn
```

### 3.4 设为默认 WSL2

```cmd
wsl --set-default-version 2
```

### 3.5 从 tarball 导入 Ubuntu（**不需要商店、不需要联网**）

```cmd
mkdir C:\wsl
wsl --import Ubuntu2204 C:\wsl\Ubuntu2204 D:\ubuntu-22.04-server-cloudimg-amd64-wsl.rootfs.tar.gz
```

**验证**：

```cmd
wsl -l -v
```

**期望**：
```
  NAME            STATE           VERSION
* Ubuntu2204      Stopped         2
```

### 3.6 进去看看

```cmd
wsl -d Ubuntu2204
```
```bash
cat /etc/os-release | head -3     # 期望 Ubuntu 22.04
python3 --version                 # 可能是 3.10（22.04 自带）
exit
```

> **注意**：`wsl --import` 导入的发行版默认以 **root** 登录（没有普通用户）。
> 测试用没问题；要建用户的话：`adduser weier && usermod -aG sudo weier`。

**⚠️ 此时 `apt update` 会失败（没有网络），这是正常的 —— 我们不用 apt。**

---

## 4. 阶段 C：WSL 里装 Runtime（**不用 apt、不用 root 改系统**）

### 4.1 装便携 Python 3.11

进 WSL：

```cmd
wsl -d Ubuntu2204
```

```bash
# 假设离线包挂在 /mnt/d/offline
mkdir -p ~/tools
tar -xzf /mnt/d/offline/cpython-3.11.*-x86_64-unknown-linux-gnu-install_only.tar.gz -C ~/tools
~/tools/python/bin/python3 --version
```

**期望**：`Python 3.11.x`

```bash
# 确认系统 Python 没被动过
/usr/bin/python3 --version
```

### 4.2 放源码

```bash
mkdir -p ~/uavswarm
tar -xzf /mnt/d/offline/01-source.tar.gz -C ~/uavswarm
tar -xzf /mnt/d/offline/02-frontend-3d-dist.tar.gz -C ~/uavswarm/frontend/swarm-console/simulation-3d
ls ~/uavswarm/src/uav_runtime/http/server.py
ls ~/uavswarm/frontend/swarm-console/simulation-3d/dist/index.html
```

**两条都必须打印出路径。**

### 4.3 起 Runtime

```bash
cd ~/uavswarm
PYTHONPATH="$PWD/src" ~/tools/python/bin/python3 -m uav_runtime.http.server
```

**期望**：
```
uav_runtime_http_bridge listening on http://127.0.0.1:8765/api
```

> **不需要 pymavlink！** Runtime 的 `dependencies = []`。
> 只有要连 PX4/MAVLink 时才需要（阶段 C/Gazebo 才用到 `04-wheelhouse`）。

### 4.4 验证（Windows 侧或 WSL 另一个窗口）

```bash
curl http://127.0.0.1:8765/api/health
```

**期望**：`{"status": "ok", "service": "uav_runtime_http_bridge", ...}`

---

## 5. 阶段 D：起前端并显示（**这一步能看到东西才算成功**）

### 5.1 在 WSL 里起两个静态服务

**⚠️ 关键：必须 `--bind 0.0.0.0`，不能 `127.0.0.1`** —— 否则 Windows 侧访问不到。

```bash
cd ~/uavswarm

# 主控台 5178
~/tools/python/bin/python3 -m http.server 5178 --bind 0.0.0.0 \
  --directory frontend/swarm-console &

# 三维 5179
~/tools/python/bin/python3 -m http.server 5179 --bind 0.0.0.0 \
  --directory frontend/swarm-console/simulation-3d/dist &
```

### 5.2 从 Windows 浏览器访问

WSL2 有 **localhost 转发**，所以 Windows 上直接打开：

```
http://localhost:5178/     主控台
http://localhost:5179/     三维
```

**⚠️ 用 `localhost` 而不是 `127.0.0.1`**，因为 CORS 白名单里两个都允许，
但 `localhost` 在 WSL2 转发下更稳。

### 5.3 验收标准

| 检查 | 期望 |
| --- | --- |
| 5178 能显示界面 | ✅ 左侧 15 个菜单、底部执行链路 |
| 5179 能显示三维场景 | ✅ **3080 上应该非常流畅** |
| 5178 顶部状态 | 起 Runtime 前 `Runtime API OFFLINE`，起后 **`ONLINE`** |
| 三维里有没有三维城市网格 | ✅ 应该有 |

**⭐ 这三条就是 weier 的"部署成功"定义。**

### 5.4 一条命令验证 Runtime 真的在干活

```bash
cd ~/uavswarm
PYTHONPATH="$PWD/src" ~/tools/python/bin/python3 -m uav_runtime.console.cli \
  submit-action land --demo-link-state lost --pretty | grep -E 'decision_code|status|adapter'
```

**期望**：
```
"decision_code": "deny",
"status": "blocked",
"adapter": "",
```

---

## 6. 阶段 E：Gazebo 仿真 —— **先别做，理由在这里**

### 6.1 为什么它是死结

| 组件 | 装法 | 离线难点 |
| --- | --- | --- |
| Gazebo Harmonic | **apt**（OSRF 仓库） | **依赖树几十个包**，要手工 `apt-get download` 全树再 `dpkg -i` |
| PX4 工具链 | **apt**（`Tools/setup/ubuntu.sh`） | 同上：`gcc-arm-none-eabi`、`cmake`、`ninja`、python 依赖 |
| PX4 源码 | git clone | 3.3 GB，可拷 |
| PX4 编译 | 本地编译 | 需要上面全部工具链 |

**weier 完全不能联网 → 上面每一层 apt 都要离线解决。**

### 6.2 三条出路（按可行性）

| 出路 | 做法 | 评价 |
| --- | --- | --- |
| **① 借网一次** | 把一台 weier 临时接到能上网的地方（哪怕半天），装完就断网 | ⭐⭐⭐ **最省事**，一次劳动三台可复制 |
| **② Docker 镜像搬迁** | 有网机器 build 一个含 PX4+Gazebo 的镜像，`docker save` → `docker load` | ⭐⭐ 干净，但镜像 5~10 GB；WSL2 里要装 Docker（又需 apt） |
| **③ 硬啃离线 apt** | 有网机器 `apt-get download` 整棵依赖树 | ⭐ 极痛苦，容易卡在依赖顺序 |

### 6.3 但更重要的判断：**集群不需要 Gazebo**

如果你要的"集群"是：**多机协同、策略裁决、任务分配、界面规模、审计** ——
**Runtime + `fake_adapter` 就够了**，完全不需要 Gazebo。

```bash
# 造一批假载具，不需要任何仿真器
submit-action takeoff --adapter fake --demo-link-state healthy
```

**只有当你需要"真实飞行物理 / 相机画面 / 视觉证据"时，才必须 Gazebo。**

> **所以：weier 现在就能当集群节点，不必等 Gazebo。**

---

## 7. 完整执行顺序（打勾用）

```
□ A1  在有网机器下载：wsl msi、Ubuntu rootfs、便携 Python、01/02 包
□ A2  拷到 U 盘（8 GB 够）
□ B1  weier 上确认 Edge 能不能开          ← 1 分钟，先做
□ B2  管理员 cmd 开两个 Windows 功能 + 重启
□ B3  装 wsl_update_x64.msi
□ B4  wsl --set-default-version 2
□ B5  wsl --import 导入 Ubuntu（走 tarball，不进商店）
□ B6  wsl -l -v 确认 VERSION=2
□ C1  WSL 里解便携 Python，验版本
□ C2  解 01-source + 02-dist，验两个路径存在
□ C3  起 Runtime，看到 listening
□ C4  curl /api/health 返回 ok
□ D1  WSL 里起 5178 + 5179（--bind 0.0.0.0）
□ D2  Windows Edge 打开 localhost:5178 / :5179
□ D3  截图：5178 界面 + 5179 三维 + Runtime ONLINE
□ D4  submit-action land --demo-link-state lost → deny/blocked
□ E1  三台重复 B~D（第 2、3 台会快很多）
□ E2  按第 1 节表格分配角色
□ F    Gazebo：先不做，等①借网或③放弃
```

---

## 8. 已知风险（提前知道）

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| **Windows 19041 没有 WSLg** | WSL 里不能开 Linux GUI 窗口 | ✅ 我们的设计本来就 headless（三维在 Windows 浏览器里画） |
| **驱动 531.29** | WSL CUDA 直通支持（≥470 即可），但**不能用 WSLg** | ✅ 不影响本项目 |
| **DISM 开功能需要管理员** | 没权限就卡住 | 提前确认有本机管理员 |
| **`wsl --import` 的发行版默认 root** | 安全上不理想 | 测试机可接受；要建用户见 3.6 |
| **`--bind 127.0.0.1` 导致 Windows 访问不到** | 5178 打不开 | **必须 `0.0.0.0`** |
| **浏览器缺失**（待确认） | 无法显示 | 加 Edge 离线包到清单 |
| **Store 假 python** | `python` 命令存在但不可用 | **不要用 Windows 侧的 python**，全部在 WSL 里跑 |

---

## 9. 每台机器装完应该长什么样（对照）

```bash
# WSL 里
~/tools/python/bin/python3 --version                 # Python 3.11.x
~/uavswarm/src/uav_runtime/http/server.py            # 存在
~/uavswarm/frontend/swarm-console/simulation-3d/dist/index.html   # 存在
curl http://127.0.0.1:8765/api/health                # {"status":"ok",...}
```

```cmd
:: Windows 侧
wsl -l -v                                            :: VERSION = 2
```

**Windows 浏览器**：
```
http://localhost:5178/    ← 界面 + 顶部 ONLINE
http://localhost:5179/    ← 三维场景
```
