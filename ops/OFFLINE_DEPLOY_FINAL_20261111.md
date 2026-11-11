# 2026UAVSwarm 离线部署手册（最终版）

**版本**：v1.0
**日期**：2026-11-11
**目标机**：weier（Lenovo ThinkStation，Windows 10 19041，i7-11700K / 63.6 GB RAM / RTX 3080）
**写这份文档的依据**：2026-10 ~ 2026-11 在 weier 上**实际跑通**的完整流程，不是理论方案

---

## 0. 这份文档给谁看

给**从没接触过这个项目、也没用过 WSL / Gazebo / PX4** 的同事。

（负责部署的人，以下称「你」。）

**照做的结果**：weier 上会出现 4 个窗口，三架无人机在 Gazebo 三维世界里，主控台和三维态势都能看到真实数据。

**用法**：从上到下照着做。**每一步都有「必须看到什么」**，输出对不上就停下来查第 11 节。

---

## 1. 先建立预期：最终会长成什么样

```
┌──────────────────────────┐   ┌──────────────────────────┐
│ 窗口 1：终端              │   │ 窗口 2：终端              │
│  三机仿真（PX4 + Gazebo） │   │  Runtime（治理内核）      │
│  会弹出 Gazebo 三维窗口   │   │  监听 8765               │
└──────────────────────────┘   └──────────────────────────┘
┌──────────────────────────┐   ┌──────────────────────────┐
│ 窗口 3：终端              │   │ 窗口 4：终端              │
│  主控台静态服务 5178      │   │  三维静态服务 5179        │
└──────────────────────────┘   └──────────────────────────┘
                    ↓
        浏览器打开两个页面：
        http://127.0.0.1:5178    主控台（3 架在线，遥测在跳）
        http://127.0.0.1:5179    三维态势（城市 + 3 架飞机）
```

**注意**：所有 4 个终端窗口**都不能关**。关了对应服务就停。

---

## 2. 前置条件（不满足就别往下走）

| 项目 | 要求 | 怎么查 |
|---|---|---|
| Windows 版本 | **10 19041（2004）或更高** | `winver` |
| 管理员权限 | 需要 | 开始菜单右键 → 有「以管理员身份运行」 |
| 磁盘空间 | **C 盘 ≥ 30 GB** | 此电脑 → 右键 C 盘 → 属性 |
| 内存 | ≥ 16 GB | 任务管理器 → 性能 |
| **代理机** | **需要一台能上网的 Linux 机器做 HTTP 代理** | 见第 4 节 |

### ⚠️ 关于"离线"的实话

**这套流程不是 100% 离线。** 其中「装 Gazebo」「装 Python 依赖」两步**必须能访问外网**。

我们当时的做法是：**让 UGV（Ubuntu 车载机，IP `192.168.0.100`）跑一个 HTTP 代理，weier 通过它上网。**

**你需要确认**：这次部署有没有一台这样的机器可用。
- **有** → 按第 4 节配代理，全程照做
- **没有** → 停下，先解决网络问题，否则第 6、7 步一定失败

---

## 3. 文件清单（U 盘里应该有这些）

### 3.1 `D:\weier-offline\`（Windows 侧，装系统和工具）

| 文件 | 大小 | 干什么 |
|---|---|---|
| `wsl_update_x64.msi` | 16.3 MB | WSL2 内核（第 5 步） |
| `ubuntu-jammy-wsl-amd64-ubuntu22.04lts.rootfs.tar.gz` | 325.3 MB | Ubuntu 22.04 系统镜像（第 6 步） |
| `PX4-Autopilot-src.tar.gz` | 540.5 MB | PX4 飞控源码（第 9 步） |
| `serve_3d_proxy.py` | 7.1 KB | 三维静态服务 + API 反代（第 12 步，**必须用**） |
| `px4_fix_offline.sh` | 6.8 KB | PX4 的 `.git` 缺失修复（第 9 步，**必须用**） |

> 另外还有 `python-3.11.9-amd64.exe` 和 `VSCode-win32-x64-portable.zip`，
> **本次部署用不到**（Python 全靠 WSL 里的，编辑器可选）。

### 3.2 `D:\offline-batch2\`（Linux 侧，项目本身）

| 文件 | 大小 | 干什么 |
|---|---|---|
| `01-source.tar.gz` | 10.9 MB | **项目源码**（第 10 步） |
| `02-frontend-3d-dist.tar.gz` | 10.8 MB | **三维构建产物**（第 12 步，漏了三维白屏） |
| `04-wheelhouse.tar.gz` | 74.7 MB | pymavlink 的离线轮子（第 11 步） |

> `03-...node_modules-WIN.tar.gz`、`05-node-...zip` **本次用不到**（那是给"Windows 原生跑 Vite 开发"的，我们不这么干）。

### 3.3 校验（可选，但建议）

在 WSL 里：
```bash
cd /mnt/d/weier-offline && sha256sum *.tar.gz *.msi
cd /mnt/d/offline-batch2 && sha256sum *.tar.gz
```

---

## 4. 第一步：在能上网的机器上架代理

> **在哪做**：那台能上网的 Linux 机器（我们用的是 UGV `nvidia@192.168.0.100`）

### 4.1 装 tinyproxy

```bash
sudo apt update
sudo apt install -y tinyproxy
```

### 4.2 配成允许任何来源

```bash
# 备份
sudo cp /etc/tinyproxy/tinyproxy.conf /etc/tinyproxy/tinyproxy.conf.bak

# 删掉原有的 Allow 行（默认只允许 127.0.0.1）
sudo sed -i '/^Allow /d' /etc/tinyproxy/tinyproxy.conf

# 允许所有来源
echo 'Allow 0.0.0.0/0' | sudo tee -a /etc/tinyproxy/tinyproxy.conf

# 确认最后一行是 Allow 0.0.0.0/0
sudo grep -n -i '^Allow' /etc/tinyproxy/tinyproxy.conf

# 重启并确认在监听
sudo systemctl restart tinyproxy
sudo systemctl enable tinyproxy
systemctl is-active tinyproxy
sudo ss -ltnp | grep 8888
```

**必须看到**：
```
active
LISTEN 0 1024 0.0.0.0:8888 0.0.0.0:*
LISTEN 0 1024    [::]:8888    [::]:*
```

### 4.3 记下这台机器的 IP

```bash
hostname -I
```

**第一个 192.168.x.x 就是代理地址**（我们当时是 `192.168.0.100`）。

### 4.4 自测代理能用

```bash
curl -sI --max-time 10 http://mirrors.tuna.tsinghua.edu.cn/ | head -1
```
**必须看到** `HTTP/1.1 301` 之类 —— 说明这台机器自己能上网。

---

## 5. 第二步：启用 WSL2（在 weier 上，**需要重启**）

> **在哪做**：weier，**管理员 PowerShell**

```powershell
# 1. 装内核更新包（双击也行）
Start-Process msiexec.exe -Wait -ArgumentList '/i', 'D:\weier-offline\wsl_update_x64.msi', '/quiet', '/norestart'

# 2. 启用两个 Windows 功能
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

# 3. 重启
Restart-Computer
```

**重启后**，管理员 PowerShell：

```powershell
wsl --set-default-version 2
wsl --status
```

**必须看到**：
```
默认版本: 2
```

> ⚠️ **Windows 10 19041 没有 WSLg**（没有 Linux 图形界面支持）。
> **这正好符合本方案**：Gazebo 的图形窗口由 Windows 侧显示，
> 我们只让 WSL 跑无界面的物理服务器和 PX4 —— 所以不受影响。

---

## 6. 第三步：导入 Ubuntu 22.04

> **在哪做**：weier，普通 PowerShell 或 cmd 都可以

```powershell
# 先建目录（不放 C 盘，放 D 盘）
New-Item -ItemType Directory -Force D:\WSL | Out-Null

# 导入（约 10 秒，解压后约 1 GB）
wsl --import Ubuntu D:\WSL\Ubuntu D:\weier-offline\ubuntu-jammy-wsl-amd64-ubuntu22.04lts.rootfs.tar.gz

# 确认
wsl -l -v
```

**必须看到**：
```
  NAME      STATE      VERSION
* Ubuntu    Running    2
```

### 6.1 进 WSL

```powershell
wsl -d Ubuntu
```

**你会看到提示符变成** `root@DESKTOP-XXXX:~#`。

> **注意**：`wsl --import` 导入的镜像**默认就是 root 登录**，不用 `sudo`。
> 下面所有命令都在 **WSL 里**、以 **root** 身份执行。

### 6.2 确认系统版本

```bash
. /etc/os-release && echo $PRETTY_NAME
```
**必须看到** `Ubuntu 22.04.5 LTS`（或 22.04.x）

### 6.3 确认 Python 版本

```bash
python3 --version
```
**必须看到** `Python 3.10.12`

> **为什么强调这个**：本项目 Runtime 要求 Python ≥ 3.10，而 3.10.12 **正好够**。
> **不要**去装 3.11 —— 第 11 步的离线轮子是给 3.10 编译的，装 3.11 会装不上 pymavlink。

---

## 7. 第四步：在 WSL 里配代理

> **在哪做**：WSL 里，root

把下面 3 处 `192.168.0.100` 换成第 4.3 步记下的代理机 IP。

### 7.1 写 apt 代理配置（一行搞定，别分多步）

```bash
printf 'Acquire::http::Proxy "http://192.168.0.100:8888";\nAcquire::https::Proxy "http://192.168.0.100:8888";\n' > /etc/apt/apt.conf.d/01proxy

cat /etc/apt/apt.conf.d/01proxy
```

**必须看到两行，且两行都有 IP**：
```
Acquire::http::Proxy "http://192.168.0.100:8888";
Acquire::https::Proxy "http://192.168.0.100:8888";
```

> 🚨 **这一步最容易出错**。历史教训：误用旧命令导致写成 `"http://:8888"`（IP 丢了），
> 后面全部报 `Temporary failure resolving`。
> **必须 `cat` 出来确认 IP 在里面。**

### 7.2 设环境变量（给 curl / pip 用）

```bash
export http_proxy=http://192.168.0.100:8888
export https_proxy=http://192.168.0.100:8888
```

> ⚠️ **`sudo` 会清空这两个变量**。本方案里你是 root，**到处都不要用 `sudo`**。
> 需要 curl 走代理时，直接 `curl`（不加 sudo）或显式写 `https_proxy=... curl ...`。

### 7.3 测试代理真的能用

```bash
timeout 5 bash -c 'cat < /dev/null > /dev/tcp/192.168.0.100/8888' && echo "✅ 端口通" || echo "❌ 端口不通"
curl -sI --max-time 15 http://mirrors.tuna.tsinghua.edu.cn/ | head -1
```

**必须看到**：
```
✅ 端口通
HTTP/1.1 301 Moved Permanently
```

**❌ 如果不通** → 回第 4 节检查 tinyproxy；或检查两台机器是否同网段（`ping 代理机IP`）。

### 7.4 换清华源（快很多）

```bash
sed -i 's|http://archive.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g; s|http://security.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list
grep -c tuna /etc/apt/sources.list
```
**必须看到**一个非零数字。

### 7.5 apt update

```bash
apt update
```

**必须看到 `Get:` 下载行**，例如：
```
Get:1 https://mirrors.tuna.tsinghua.edu.cn/ubuntu jammy InRelease [270 kB]
...
Reading package lists... Done
```

> **如果看到 `Temporary failure resolving`** → 代理没生效，回 7.1 重写配置。

---

## 8. 第五步：装工具链和 Gazebo

### 8.1 工具链（apt，快）

```bash
apt install -y build-essential cmake ninja-build python3-dev pkg-config git python3-pip
```

**验证**：
```bash
cmake --version | head -1 ; ninja --version ; gcc --version | head -1
```
**必须看到**类似：
```
cmake version 3.22.1
1.10.1
gcc (Ubuntu 11.4.0-...) 11.4.0
```

### 8.2 加 OSRF 仓库（装 Gazebo 的来源）

```bash
# 下 key（不要加 sudo，要带代理）
curl -fsSL --max-time 90 https://packages.osrfoundation.org/gazebo.gpg -o /tmp/gazebo.gpg
file /tmp/gazebo.gpg
```
**必须看到** `PGP public key block`（约 1222 字节）

```bash
# 装 key
install -m 0644 /tmp/gazebo.gpg /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg

# 加仓库（★ 必须是 https，不能是 http）
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] https://packages.osrfoundation.org/gazebo/ubuntu-stable jammy main' > /etc/apt/sources.list.d/gazebo-stable.list

cat /etc/apt/sources.list.d/gazebo-stable.list
```
**必须看到 `https://packages.osrfoundation.org`**（`https`，不是 `http`）

> 🚨 **为什么必须 https**：走代理时 `http://` 那条路会报
> `Temporary failure resolving '192.168.0.100'`（apt 去解析代理 IP 本身，很诡异）。
> 换成 https 之后立刻正常 —— 这是我们实际踩过的坑。

### 8.3 调大超时（链路慢，默认超时会断）

```bash
printf 'Acquire::http::Timeout "120";\nAcquire::https::Timeout "120";\nAcquire::Retries "3";\n' > /etc/apt/apt.conf.d/99timeout
cat /etc/apt/apt.conf.d/99timeout
```

### 8.4 装 Gazebo

```bash
apt update
```
**必须看到** `Get:... packages.osrfoundation.org ... InRelease`

```bash
apt install -y gz-harmonic
```

预计下载 **300~500 MB**，1.8 MB/s 下约 **3~5 分钟**。

### 8.5 验证

```bash
gz sim --versions
```
**必须看到** `8.15.0`（或 8.x 的其它版本）

```bash
which gz
```
**必须看到** `/usr/bin/gz`

---

## 9. 第六步：装 PX4 的 Python 依赖

> PX4 的代码生成器（uORB 话题、DDS 桥、飞行任务）依赖一批 Python 包，
> **其中 `empy` 版本必须是 3.x**。

### 9.1 一次性装（推荐）

```bash
cd /root
tar -xzf /mnt/d/weier-offline/PX4-Autopilot-src.tar.gz    # 先解出来，才能拿到 requirements.txt
python3 -m pip install --user -i https://pypi.tuna.tsinghua.edu.cn/simple -r /root/PX4-Autopilot/Tools/setup/requirements.txt
```

> **注意**：`-r` 后面写**绝对路径**，并且**整条命令写在一行**（不要用 `\` 换行，
> 从 Windows 复制过去会变成 `\ ` + 回车，pip 会报 `ambiguous option`）。

### 9.2 验证（关键三行）

```bash
python3 -c "import em; print('empy', em.__version__ if hasattr(em,'__version__') else 'ok')"
python3 -c "import jinja2; print('jinja2', jinja2.__version__)"
python3 -c "import nunavut; print('nunavut ok')"
```

**必须三行都成功。**

### 9.3 ⚠️ 最常见的坑：empy 装成 4.x

```bash
python3 -m pip show empy | head -2
```
**必须是 `Version: 3.3.4`**

**如果是 4.x**（错误提示里会写 `pip3 install --user empy`，**别照做**，那会装 4.x）：
```bash
python3 -m pip uninstall -y empy
python3 -m pip install --user -i https://pypi.tuna.tsinghua.edu.cn/simple "empy==3.3.4"
```

---

## 10. 第七步：修 PX4 源码并编译

### 10.1 为什么需要修复

我们发的 PX4 源码包**没有打包 `.git`**（省 1.6 GB）。而 PX4 构建链有**四处**强依赖 `.git`：

| 位置 | 检查什么 | 不修会怎样 |
|---|---|---|
| `Makefile:38` | 根目录 `.git` | `YOU HAVE TO USE GIT TO DOWNLOAD THIS REPOSITORY. ABORTING.` |
| `cmake/px4_git.cmake:58` | **每个子模块**的 `.git` | `ninja: error: '.../gps/devices/.git', needed by '...git_init_...'` |
| `px_update_git_header.py:80` | 根仓库有有效 HEAD | `CalledProcessError: git rev-parse --verify HEAD` exit 128 |
| 同文件 `:118/:128` | mavlink / nuttx 子模块有有效 HEAD | 同上 |

### 10.2 一条命令修复

```bash
cd /root/PX4-Autopilot
bash /mnt/d/weier-offline/px4_fix_offline.sh
```

**必须看到**（关键三行）：
```
① 根仓库（过 Makefile:38 与 py:80）
   ✅ HEAD 有效: xxxxxxx
② 每个子模块建微型真仓库（过 cmake:58 与 py:118/128）
   成功 35 个 / 失败 0 个
③ 自检：px_update_git_header.py（第 ③④ 关）
   ✅ 通过
```

> **`③ 自检 ✅ 通过` 是硬指标**。过不了就别浪费时间编译。

### 10.3 编译

```bash
cd /root/PX4-Autopilot
GIT_SUBMODULES_ARE_EVIL=1 make px4_sitl gz_x500_mono_cam
```

**`GIT_SUBMODULES_ARE_EVIL=1` 必须带** —— 这是 PX4 自带的开关
（`Tools/check_submodules.sh:39-42`），设了它才跳过联网拉子模块。

**预计 5~15 分钟**（1180 个目标左右）。

**必须看到**：
```
[1126/1126] Linking CXX executable bin/px4
```

**验证**：
```bash
ls -lh /root/PX4-Autopilot/build/px4_sitl_default/bin/px4
```
**必须看到**约 **56 MB**

> 编译完会**自动启动一次 PX4 + Gazebo**，看到 `pxh>` 提示符就是成功了。
> 按 `Ctrl-C` 退出，或敲 `shutdown`。

---

## 11. 第八步：装项目源码和 pymavlink

### 11.1 解项目源码

```bash
tar -xzf /mnt/d/offline-batch2/01-source.tar.gz -C /root
ls /root/uavswarm/src/uav_runtime/http/server.py
```
**必须看到那个路径存在**（解出来就是 `/root/uavswarm`）

### 11.2 解三维构建产物

```bash
tar -xzf /mnt/d/offline-batch2/02-frontend-3d-dist.tar.gz -C /root/uavswarm/frontend/swarm-console/simulation-3d/
ls -lh /root/uavswarm/frontend/swarm-console/simulation-3d/dist/assets/
```
**必须看到 4.3 MB 的主程序**：
```
index-BB2bG-ND.css     35K
index-DCSbRQMB.js     4.3M      ← ★ 这个必须有
```

> 🚨 **这一步最容易漏**。漏了三维能打开但**白屏**。

### 11.3 装 pymavlink（离线，用 wheelhouse）

```bash
tar -xzf /mnt/d/offline-batch2/04-wheelhouse.tar.gz -C /root
ls /root/wheelhouse | wc -l
```
**必须是 27**

```bash
python3 -m pip install --user --no-index --find-links=/root/wheelhouse pymavlink
```

**必须看到**：
```
Successfully installed fastcrc-0.5.0 lxml-6.1.3 pymavlink-2.4.50
```

### 11.4 验证（这一步是 Runtime 能不能连上 PX4 的分水岭）

```bash
python3 -c "import pymavlink, fastcrc, lxml; print('pymavlink', pymavlink.__version__)"
python3 -c "import importlib.util as u; print('find_spec ->', u.find_spec('pymavlink') is not None)"
```

**必须看到**：
```
pymavlink 2.4.50
find_spec -> True            ← ★ 必须是 True
```

> 🚨 **为什么必须用 `python3`（3.10）**：wheelhouse 里的 pymavlink 轮子是
> **cp310 + manylinux x86_64**。如果你用 3.11 装，会报
> `No matching distribution found` —— **那不是包坏了，是版本对不上**。

---

## 12. 第九步：启动（4 个终端）

> **全部在 WSL 里**。开 4 个 Windows PowerShell 窗口，每个窗口敲 `wsl -d Ubuntu` 进去。

### 终端 1 —— 三机仿真（最慢，最先起）

```bash
cd /root/uavswarm
bash simulation/px4_gazebo/scripts/start_three_uav.sh \
  --config simulation/px4_gazebo/config/three_uav_mono_cam_sitl.json --gui
```

**必须看到**：Gazebo 三维窗口弹出，三架飞机在 Y 轴错开停在地面，终端刷出三个 PX4 的日志。

> ⚠️ **起之前先确认没有旧的 PX4 占着端口**：
> ```bash
> pkill -f 'bin/px4' ; pkill -f 'gz sim' ; sleep 2
> ```

### 终端 2 —— Runtime（治理内核）

```bash
cd /root/uavswarm && PYTHONPATH="$PWD/src" /usr/bin/python3 -m uav_runtime.http.server
```

**必须看到**：
```
uav_runtime_http_bridge listening on http://127.0.0.1:8765/api
```

> ★ **注意是 `/usr/bin/python3`**（3.10），不是别的路径。

### 终端 3 —— 主控台 5178

```bash
cd /root/uavswarm/frontend/swarm-console && python3 -m http.server 5178 --bind 0.0.0.0
```

**必须看到**：
```
Serving HTTP on 0.0.0.0 port 5178 (http://0.0.0.0:5178/) ...
```

### 终端 4 —— 三维 5179（**必须用反代脚本**）

```bash
cd /root/uavswarm
python3 /mnt/d/weier-offline/serve_3d_proxy.py --dir frontend/swarm-console/simulation-3d/dist
```

**必须看到**：
```
  服务目录 : /root/uavswarm/frontend/swarm-console/simulation-3d/dist
  监听     : http://127.0.0.1:5179
  代理前缀 : /api/*  →  http://127.0.0.1:8765
```

> 🚨 **绝对不能用 `python3 -m http.server 5179`**。
> 三维的构建产物里 API 地址是相对路径 `/api`，
> `http.server` 会去找文件 `dist/api/vehicle-snapshot` —— 永远 404，三维没数据。

### 浏览器

```
http://127.0.0.1:5178     主控台
http://127.0.0.1:5179     三维态势
```

---

## 13. 验收清单（逐条打勾，全绿才算装好）

| # | 检查 | 命令 | 期望 |
|---|---|---|---|
| 1 | Gazebo 版本 | `gz sim --versions` | `8.15.0` |
| 2 | PX4 二进制 | `ls -lh /root/PX4-Autopilot/build/px4_sitl_default/bin/px4` | 约 56 MB |
| 3 | pymavlink | `python3 -c "import importlib.util as u;print(u.find_spec('pymavlink') is not None)"` | `True` |
| 4 | 三维主程序 | `ls -lh /root/uavswarm/.../dist/assets/index-DCSbRQMB.js` | 4.3 MB |
| 5 | Runtime 在听 | `curl -s http://127.0.0.1:8765/api/health` | `{"status":"ok",...}` |
| 6 | **三架载具** | `curl -s http://127.0.0.1:8765/api/vehicles` | 3 架，`connected: true` |
| 7 | **遥测有数** | `curl -s http://127.0.0.1:8765/api/telemetry/latest \| head -30` | 有 `mode`/`armed`/位置 |
| 8 | **PX4 不再报 GCS 断** | 看终端 1 | `Preflight Fail: No connection to the GCS` **不再刷** |
| 9 | 主控台 | 浏览器 5178 | `在线节点 3 / 3` |
| 10 | 三维 | 浏览器 5179 | 三架飞机出现在场景里 |
| 11 | 三维 API 转发 | 终端 4 日志 | 出现 `[PROXY] ... 200` |

---

## 14. 出问题了查这里（按现象索引）

| 现象 | 原因 | 怎么办 |
|---|---|---|
| `Temporary failure resolving 'xxx'` | 代理没生效，或配置文件里 IP 丢了 | `cat /etc/apt/apt.conf.d/01proxy` 确认有 IP；重跑第 7.1 |
| `Temporary failure resolving '192.168.0.100'` | apt 用 `http://` 走代理时的怪问题 | 把 OSRF 仓库改成 `https://`（第 8.2） |
| `E: Unable to locate package gz-harmonic` | OSRF 仓库没拉成功 | `apt update` 看有没有 `packages.osrfoundation.org` |
| `curl: (6) Could not resolve host` | 用了 `sudo curl`（代理变量被清空） | 去掉 `sudo` |
| `ambiguous option: --no` | `--no-index` 被截断/写成 `--no index` | 改用 `--find-links=/path` 且整行不换行 |
| `No matching distribution found for pymavlink` | 用 3.11 装了 cp310 的轮子 | 改用 `/usr/bin/python3`（3.10） |
| `ModuleNotFoundError: No module named 'em'` | empy 没装 | 第 9.1 |
| PX4 编译报 `empy` 版本错 | empy 是 4.x | `pip install "empy==3.3.4"` |
| `YOU HAVE TO USE GIT TO DOWNLOAD...` | 根目录没 `.git` | 第 10.2 |
| `ninja: error: '.../xxx/.git', needed by ...` | 子模块没 `.git` | 第 10.2 |
| `git rev-parse --verify HEAD` exit 128 | 根仓库没有有效提交 | 第 10.2（脚本会建空提交） |
| 端口被占用 | 上次没退干净 | `ss -ltnpH 'sport = :5178'` 查 PID 后 kill |
| 三维白屏 + Console 报 `toSorted is not a function` | 浏览器太老 | 用 Edge/Chrome 110+ 或 Firefox 115+ |
| 三维白屏 + Console 报 404 assets | `02-frontend-3d-dist.tar.gz` 没解压 | 第 11.2 |
| 三维"数据源断开"、终端刷 `code 404, message File not found` | 用了 `python -m http.server 5179` | 换成 `serve_3d_proxy.py`（第 12 终端 4） |
| 主控台 `在线节点 0/3` | Runtime 用了没 pymavlink 的 Python | 第 11.4 验证，然后第 12 终端 2 |
| PX4 一直刷 `No connection to the GCS` | Runtime 没连上 | 同上 |
| 三机起不来/端口冲突 | 单机 PX4 还占着 14540/14580 | `pkill -f 'bin/px4'` 再起 |

---

## 15. 端口与目录速查

### 端口

| 端口 | 谁在用 | 说明 |
|---|---|---|
| **8765** | Runtime | 前端访问的 API |
| **5178** | 主控台静态服务 | 浏览器打开 |
| **5179** | 三维静态服务 + `/api` 反代 | 浏览器打开 |
| 14540/14541/14542 | PX4 → Runtime（遥测） | `14540 + 实例号` |
| 14580/14581/14582 | Runtime → PX4（指令） | `14580 + 实例号` |

> 端口不是硬编码，是 PX4 在
> `ROMFS/px4fmu_common/init.d-posix/px4-rc.mavlink:4-6` 里用
> `14540 + px4_instance` 算出来的。

### 关键目录（全在 WSL 里）

| 路径 | 是什么 |
|---|---|
| `/root/PX4-Autopilot` | PX4 源码 + 编译产物 |
| `/root/uavswarm` | 我们的项目仓库根 |
| `/root/uavswarm/src/uav_runtime` | 控制面内核 |
| `/root/uavswarm/frontend/swarm-console` | 主控台 |
| `/root/uavswarm/frontend/swarm-console/simulation-3d/dist` | 三维构建产物 |
| `/root/wheelhouse` | pymavlink 离线轮子 |
| `/mnt/d/weier-offline` | Windows 的 `D:\weier-offline` |
| `/mnt/d/offline-batch2` | Windows 的 `D:\offline-batch2` |

---

## 16. 收尾：这份文档替代了哪些旧文件

以下文件**已过期，不要再照着做**：

| 旧文件 | 为什么过期 |
|---|---|
| `ops/WEIER_WORKFLOW_20261022.md` | 写于还没装 Gazebo 的阶段 |
| `ops/WEIER_ENVIRONMENT_20261022.md` | 环境勘察记录，非操作手册 |
| `ops/OFFLINE_ACCEPTANCE_20261019.md` | 早期验收记录 |
| `ops/MIGRATION_OFFLINE_20261014.md` | 早期迁移记录 |
| `2026UAVSwarm_目标机现场演示脚本.md` | 已于 2026-11-10 删除，被 `_v2_20261110.md` 取代 |

**本方案与它们的根本区别**：本方案记录的是**在 weier 上实际跑通**的路径，
包括所有踩过的坑和规避方法。

---

## 附录：执行顺序速查（贴在显示器边上）

```
1. 代理机架上 tinyproxy（Allow 0.0.0.0/0，端口 8888）
2. weier: 装 wsl_update_x64.msi + 两个 dism 功能 + 重启
3. weier: wsl --import Ubuntu D:\WSL\Ubuntu <rootfs>
4. WSL:   printf 写 01proxy（两个 IP 都要在）→ export 两个变量 → apt update
5. WSL:   换清华源 → apt install 工具链
6. WSL:   OSRF key + https 仓库 → apt install gz-harmonic → gz sim --versions = 8.15.0
7. WSL:   pip install -r requirements.txt（empy 必须 3.3.4）
8. WSL:   解 PX4 → bash px4_fix_offline.sh（等 SELFCHECK_OK）→ make px4_sitl gz_x500_mono_cam
9. WSL:   解 01-source → 解 02-dist → 装 pymavlink（find_spec 必须 True）
10. 4 个终端：三机仿真 / Runtime(3.10) / 5178 / 5179(反代)
11. 浏览器 5178 + 5179 → 逐条走第 13 节验收
```
