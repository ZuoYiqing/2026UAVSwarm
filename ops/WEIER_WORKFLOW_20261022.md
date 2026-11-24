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

### 1.1 ⚠️ 先看清两条硬限制（决定了哪些分工**现在做不了**）

| 限制 | 依据 | 后果 |
| --- | --- | --- |
| **Runtime 只监听 `127.0.0.1:8765`，且不可配置** | `server.py:104` 调 `create_server()` 不传参 | **别的机器连不上这台 Runtime**；也**跑不了第二个实例** |
| **`ALLOWED_ORIGINS` 只有 `localhost` / `127.0.0.1`，没有 IP** | `server.py:21` | 从别的机器用 IP 打开主控台 → **跨域被拒 → 显示"后端不可达"** |

**→ 结论：现在唯一能跑通的是「每台机器自己一整套，本机浏览器访问」。
"一台 Runtime 服务多台显示"要等那个 4 行补丁（见 `WEIER_ENVIRONMENT_20261022.md` §5.3）。**

### 1.2 三种角色（**每台机器都装全套，按需启动**）

你说"每台都装所有东西，后面看情况去用" —— 正合适。装完之后同一台机器可以扮演不同角色，
**区别只在于启动哪几个进程**：

| 角色 | 怎么启动 | 现在能做吗 |
| --- | --- | --- |
| **① 地面站**（Runtime + 前端） | 起 Runtime `:8765` + 两个静态服务 `:5178/:5179`，本机浏览器看 | ✅ **可以，已实测** |
| **② 无人平台仿真**（PX4 + Gazebo） | 需要 Gazebo | ❌ **装不上**（离线 apt 依赖地狱） |
| **③ 两者都当**（地面站 + 无人平台） | 需要 Gazebo | ❌ 同上，缺那一半 |

### 1.3 ⭐ 关于"无人平台"的一个替代方案

**如果"无人平台"只是要"有载具在动、能验证策略与界面规模"**，
那不需要 Gazebo —— 用 **`fake_adapter`** 造即可：

```cmd
:: 造几个假载具（不需要任何仿真器）
D:\tools\python\python.exe -m uav_runtime.console.cli submit-action takeoff --adapter fake --demo-link-state healthy
```

| 你要验证的 | fake adapter 够吗 | 需要 Gazebo 吗 |
| --- | --- | --- |
| 策略门裁决 | ✅ 够 | ❌ 不需要 |
| 审计 / 回放 | ✅ 够 | ❌ 不需要 |
| 动作生命周期 | ✅ 够 | ❌ 不需要 |
| 界面规模（多载具显示） | ✅ 够（假数据） | ❌ 不需要 |
| **真实飞行物理** | ❌ 不够 | ✅ **需要** |
| **相机画面 / 视觉证据** | ❌ 不够 | ✅ **需要** |

### 1.4 建议的起步安排

| 机器 | 建议角色 | 装什么 |
| --- | --- | --- |
| **weier-1** | **地面站**（Runtime + 前端，本机看） | 全套（本来就都装） |
| **weier-2** | **地面站**（同上，独立一套） | 全套 |
| **weier-3** | **备用 / 压测准备** | 全套 |

**每台都是独立可验证的一整套** —— 一台出问题不影响结论，也不需要 Gazebo。

> ⚠️ 如果你确实需要"一台 Runtime、多台看同一个态势"，那必须先把
> `UAV_RUNTIME_HTTP_HOST` / `_PORT` 那个补丁合入，否则跨机一定连不上。

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

## 4. 阶段 C：装 Runtime（**Windows 原生，已实测**）

> **⚠️ 2026-10-22 更新：本阶段已改为 Windows 原生，不再需要 WSL。**
>
> 实测证明 Runtime 在 Windows 上完全正常（`WEIER_ENVIRONMENT_20261022.md` §5.1.1），
> 所以只要解压便携 Python 就能跑。**WSL 那条路保留在第 3 节，仅在将来要 ROS 时才用。**
>
> 需要的文件从 3 个降到 **1 个**：`cpython-...-x86_64-pc-windows-msvc-install_only.tar.gz`

### 4.1 解压便携 Python

```cmd
mkdir D:\tools
tar -xf D:\weier-offline\cpython-3.11.18+20261026-x86_64-pc-windows-msvc-install_only.tar.gz -C D:\tools
D:\tools\python\python.exe --version
```

**期望**：`Python 3.11.18`

### 4.2 放源码

```cmd
mkdir D:\uavswarm
tar -xzf D:\weier-offline\01-source.tar.gz -C D:\uavswarm
tar -xzf D:\weier-offline\02-frontend-3d-dist.tar.gz -C D:\uavswarm\frontend\swarm-console\simulation-3d

dir D:\uavswarm\src\uav_runtime\http\server.py
dir D:\uavswarm\frontend\swarm-console\simulation-3d\dist\index.html
```

**两条都必须找到文件。**

### 4.3 起 Runtime

```cmd
cd /d D:\uavswarm
set PYTHONPATH=%CD%\src
D:\tools\python\python.exe -m uav_runtime.http.server
```

**期望**：
```
uav_runtime_http_bridge listening on http://127.0.0.1:8765/api
```

> **不需要 pymavlink！** Runtime 的 `dependencies = []`，实测在 Windows 上
> 不装 pymavlink 也能起（`adapters` 是惰性导入）。
> 只有要连 PX4/MAVLink 时才需要 `04-wheelhouse`。

> **⚠️ 窗口别关。** `set` 只对当前窗口有效，关掉要重设。

### 4.4 验证（另一个 cmd 窗口）

```cmd
curl http://127.0.0.1:8765/api/health
```

**期望**：`{"status": "ok", "service": "uav_runtime_http_bridge", ...}`

---

## 4b. 阶段 C-备用：WSL 路线（仅当将来需要 ROS 时）

> 如果确实需要在 weier 上跑 Linux/ROS，再按第 3 节装 WSL2；
> 装完后：
>
> ```bash
> mkdir -p ~/tools
> tar -xzf /mnt/d/weier-offline/cpython-3.11.*-x86_64-unknown-linux-gnu-install_only.tar.gz -C ~/tools
> mkdir -p ~/uavswarm
> tar -xzf /mnt/d/weier-offline/01-source.tar.gz -C ~/uavswarm
> tar -xzf /mnt/d/weier-offline/02-frontend-3d-dist.tar.gz -C ~/uavswarm/frontend/swarm-console/simulation-3d
> cd ~/uavswarm
> PYTHONPATH="$PWD/src" ~/tools/python/bin/python3 -m uav_runtime.http.server
> ```
>
> **⚠️ WSL 里起前端必须 `--bind 0.0.0.0`**（WSL2 是 NAT）。

### 4.4 验证（另一个 cmd 窗口）

```cmd
curl http://127.0.0.1:8765/api/health
```

**期望**：`{"status": "ok", "service": "uav_runtime_http_bridge", ...}`

---

## 5. 阶段 D：起前端并显示（**这一步能看到东西才算成功**）

> **⚠️ 2026-10-22 更新：前端也走 Windows 原生，不要放进 WSL。**
>
> 原因：Runtime 已在 Windows 原生实测跑通（见 `WEIER_ENVIRONMENT_20261022.md` §5.1.1），
> 便携 Python 同时提供 `python.exe`，所以 `python -m http.server` 直接在 Windows 跑即可。
> **放进 WSL 只有一个坏处**：要多一层 `--bind 0.0.0.0` 与 WSL 网络转发，没有必要。
>
> **两边都保留**：如果哪台机器 WSL 已经装好了，用 WSL 起前端也能工作（见 5.6）。

### 5.1 Windows 原生起两个静态服务（推荐）

**开两个 cmd 窗口**，各跑一个：

**窗口 A —— 主控台 5178**
```cmd
cd /d D:\uavswarm
D:\tools\python\python.exe -m http.server 5178 --bind 127.0.0.1 --directory frontend/swarm-console
```

**窗口 B —— 三维 5179**
```cmd
cd /d D:\uavswarm
D:\tools\python\python.exe -m http.server 5179 --bind 127.0.0.1 --directory frontend/swarm-console/simulation-3d\dist
```

> **Windows 原生下 `--bind 127.0.0.1` 就够** —— 浏览器和服务器在同一台机器上。
> 只有要让**别的机器**访问时才需要 `--bind 0.0.0.0`（见 5.7）。

### 5.2 打开浏览器

```
http://127.0.0.1:5178/     主控台
http://127.0.0.1:5179/     三维
```

**✅ CORS 白名单里 `127.0.0.1:5178/5179` 和 `localhost:5178/5179` 都在，
两种写法都能用。**

### 5.3 ⚠️ 三维报 `toSorted is not a function` 怎么办

**这是浏览器版本问题，不是显卡问题。**

| 检查 | 做法 |
| --- | --- |
| 5 秒判定 | 浏览器里按 F12，控制台敲 `typeof [].toSorted`<br>返回 `"function"` = 支持；`"undefined"` = 不支持，必崩 |
| 最低版本 | **Edge/Chrome 110+**，**Firefox 115+**，Safari 16+ |
| 查版本 | Edge `edge://version`；Chrome `chrome://version`；Firefox `about:support` |

**解法二选一**：
1. **换一个够新的浏览器**（最简单，不需要改任何东西）
2. **给三维页加兼容垫片** —— 已备好，见 `WEIER_ENVIRONMENT_20261022.md` 的说明；
   加完老浏览器也能跑

> **注意：报错文案里提到 WebGL 是误导。** 真正的原因是 Cesium 内部调用了
> `Array.prototype.toSorted`，而这个方法是 2023 年才进浏览器的。

### 5.4 验收标准

| 检查 | 期望 |
| --- | --- |
| 5178 能显示界面 | ✅ 左侧 15 个菜单、底部执行链路 |
| 5179 能显示三维场景 | ✅ **3080 上应该非常流畅** |
| 5178 顶部状态 | 起 Runtime 前 `Runtime API OFFLINE`，起后 **`ONLINE`** |
| 三维里有没有三维城市网格 | ✅ 应该有 |

**⭐ 这几条就是 weier 的"部署成功"定义。**

### 5.5 一条命令验证 Runtime 真的在干活

```cmd
cd /d D:\uavswarm
set PYTHONPATH=%CD%\src
D:\tools\python\python.exe -m uav_runtime.console.cli submit-action land --demo-link-state lost --pretty
```

**期望**（在输出里找到这三行）：
```
"decision_code": "deny",
"status": "blocked",
"adapter": "",
```

### 5.6 如果你已经装好 WSL，想用 WSL 起前端（可选，不是首选）

```bash
cd ~/uavswarm
~/tools/python/bin/python3 -m http.server 5178 --bind 0.0.0.0 --directory frontend/swarm-console &
~/tools/python/bin/python3 -m http.server 5179 --bind 0.0.0.0 --directory frontend/swarm-console/simulation-3d/dist &
```

**⚠️ WSL 里必须 `--bind 0.0.0.0`**（WSL2 是 NAT，绑 `127.0.0.1` 的话 Windows 侧访问不到）。
浏览器用 `http://localhost:5178/`（WSL2 有 localhost 转发）。

### 5.7 要让别的机器看这台的前端（多机场景）

**Windows 原生**（管理员 cmd）：
```cmd
netsh advfirewall firewall add rule name="UAVSwarm 5178-5179" dir=in action=allow protocol=TCP localport=5178-5179
```
并且起服务时要 `--bind 0.0.0.0`。

**⚠️ 但跨机访问 Runtime 目前做不到** —— Runtime 只监听 `127.0.0.1:8765`，不可配置
（见 `WEIER_ENVIRONMENT_20261022.md` §5.2）。所以跨机时：
**页面能看，但连不上后端**，需要那个 4 行补丁。

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
□ C1  Windows 上解压便携 Python，验版本 3.11.x
□ C2  解 01-source + 02-dist，验两个路径存在
□ C3  起 Runtime（set PYTHONPATH 后跑），看到 listening
□ C4  curl /api/health 返回 ok
□ D1  Windows 原生起 5178 + 5179（两个 cmd 窗口）
□ D2  浏览器打开 127.0.0.1:5178 / :5179
□ D2b 三维若报 toSorted → F12 敲 typeof [].toSorted 判定浏览器版本
□ D3  截图：5178 界面 + 5179 三维 + Runtime ONLINE
□ D4  submit-action land --demo-link-state lost → deny/blocked/adapter 空
□ E1  三台重复 A2~D（第 2、3 台会快很多）
□ E2  按第 1 节表格决定角色（默认：每台独立地面站）
□ F    Gazebo：先不做，等①借网或③放弃
```

---

## 8. 已知风险（提前知道）

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| **浏览器太老（无 `toSorted`）** | 三维崩在 CesiumWidget，且**报错文案误提 WebGL** | F12 敲 `typeof [].toSorted` 判定；换新浏览器或加垫片 |
| **Windows 19041 没有 WSLg** | WSL 里不能开 Linux GUI 窗口 | ✅ 我们的设计本来就 headless（三维在 Windows 浏览器里画） |
| **驱动 531.29** | WSL CUDA 直通支持（≥470 即可），但**不能用 WSLg** | ✅ 不影响本项目 |
| **DISM 开功能需要管理员** | 没权限就卡住 | **只有走 WSL 路线才需要**；Windows 原生路线不需要 |
| **`wsl --import` 的发行版默认 root** | 安全上不理想 | 测试机可接受；要建用户见 3.6 |
| **WSL 里绑 `127.0.0.1`** | Windows 访问不到 5178 | WSL 路线必须 `0.0.0.0` |
| **Windows 控制台是 GBK** | 打印 emoji 会 `UnicodeEncodeError` | 脚本不要用 emoji；中文没问题 |
| **Store 假 python** | `python` 命令存在但不可用 | **用 `D:\tools\python\python.exe` 的绝对路径** |
| **Runtime 只听 127.0.0.1** | 跨机连不上、多实例跑不了 | 等那个 4 行补丁 |

---

## 9. 每台机器装完应该长什么样（对照）

```cmd
:: Windows 原生（推荐路线）
D:\tools\python\python.exe --version                          :: Python 3.11.x
dir D:\uavswarm\src\uav_runtime\http\server.py                :: 存在
dir D:\uavswarm\frontend\swarm-console\simulation-3d\dist\index.html  :: 存在
curl http://127.0.0.1:8765/api/health                          :: {"status":"ok",...}
```

**浏览器**：
```
http://127.0.0.1:5178/    ← 界面 + 顶部 ONLINE
http://127.0.0.1:5179/    ← 三维场景
```

**F12 控制台**：
```js
typeof [].toSorted        // 必须是 "function"，否则三维会崩
```

```cmd
:: 只有走 WSL 备用路线才需要
wsl -l -v                 :: VERSION = 2
```
