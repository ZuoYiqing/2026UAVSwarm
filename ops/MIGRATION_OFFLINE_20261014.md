# 离线环境迁移方案（2026-10-14）

**目标**：把当前 `main`（`ea4bf62`）的前后端搬进一个**无网**环境，先在**中间笔记本**上跑通，
再整体搬到离线机器。

**基线**：上次迁移是 `b4e2f6e`（2026-08-21）。**距今 126 个提交、269 个文件变了，要全换。**

---

## 0. 一句话结论（先看这个）

| 组件 | 离线环境要跑吗 | 现在的状态 |
| --- | --- | --- |
| **主控台 5178** | ✅ 跑 | **纯静态，不用构建**，`python -m http.server` 就能起 |
| **三维控制台 5179** | ✅ 跑 | ⚠️ **`dist/` 比源码旧（9/28 vs 9/30）→ 必须在本机重新 build 一次** |
| **Runtime 8765（Python）** | ⚠️ **可选，且是最大的未知** | 从未在 Windows 上跑过；20.04 的 Python 3.8 **版本不够** |
| **算法模型（.gguf，3.8 GB）** | ❌ 这次不要 | 不在 git 里，且离线环境暂时没有跑它的机器 |
| **PX4 / Gazebo 仿真** | ❌ 不要 | 离线环境是**真机**，仿真进去无用（Jetson 上也跑不动） |
| **`.runtime/`（1.6 GB）** | ❌ 不要 | 仿真运行产物 |

**最省事、收益最大的路径**：本机重建一次三维前端 → 打包
`源码（16.4 MB）+ wheelhouse（4.3 MB）+ 两个前端（主控台静态 + 三维 dist）`
≈ **40 MB**。离线机器只要有 **Python + Firefox** 就能看到控制台。

---

## 1. 为什么必须先重建三维前端（不是可选项）

| 证据 | 值 |
| --- | --- |
| `dist/index.html` 时间 | 2026-09-28 17:42 |
| `src/main.js` 时间 | **2026-09-30 11:32** |
| 结论 | **dist 落后源码 2 天**，缺 9/30 之后的改动 |

而 `dist/` **不在 git 里**（`.gitignore:2:dist/`），所以**克隆源码不会带来 dist** —— 必须构建。

**构建在本机做**（本机有 `node v24.21.0` / `npm 11.19.0`）。构建产物是**纯静态**，
离线机器**不需要 Node**。

> `vite.config.js` 里用 `vite-plugin-static-copy` 把 Cesium 的
> `ThirdParty / Workers / Assets / Widgets` 复制到 `dist/cesium-static/` ——
> **这一条是这个项目能离线跑的关键**，已配好，不用改。

---

## 2. 打包清单

### 2.1 要从源码带走的（git 跟踪，514 个文件，16.4 MB）

顶层目录全部带走，**除 `algorithm_lab/` 可选**：

```
config/  demo/  docs/  frontend/  ops/  scenarios/  scripts/
simulation/  src/  tests/  wheelhouse_basic/
audit/            ← 审计日志，带（体积小，且是运行产物目录结构）
algorithm_lab/    ← 可选：模型本体不在这儿，代码在（1.x MB）
```

### 2.2 额外的、不在 git 里的（必须单独准备）

| 项 | 大小 | 为什么必须 |
| --- | --- | --- |
| **`simulation-3d/dist/`（重建后）** | ~19 MB | 被 gitignore，但离线环境靠它显示三维 |
| `wheelhouse_basic/` | 4.3 MB | Python 离线依赖（pytest/pip/setuptools 等 9 个 wheel） |
| `ops/recon-offline-env.sh` | 6 KB | 到离线机器上先跑这个 |
| `ops/recon-windows.ps1` | 11 KB | Windows 机器上跑 |
| `ops/jetson-util/`（若已整理） | 6 KB | 刷 Jetson NVMe 用 |

### 2.3 明确**不要**带的（体积大且无用）

| 项 | 大小 | 原因 |
| --- | --- | --- |
| `.git/` | 40.6 MB | 离线机器没有 git（实测 `git MISSING`），带了也用不上 |
| `.runtime/` | **1,587 MB** | 仿真运行产物（ULog/标定/健康），真机不需要 |
| `node_modules/` | **237.6 MB** | **除非要在现场改前端代码**；只跑 dist 的话不需要 |
| `algorithm_lab/**/artifacts/` | ~7.8 GB | 模型权重，这次不迁 |

---

## 3. 本机操作：构建 + 打包（你在这台电脑上做）

### 步骤 1：重建三维前端

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d
npm ci                 # 按 package-lock.json 精确还原依赖
npm run build          # 产出 dist/
```

**✅ 成功判据**：`dist\index.html` 的时间**变成刚刚**，且 `dist\cesium-static\` 里有东西。

```powershell
# 验证
Get-Item dist\index.html | Select-Object LastWriteTime
(Get-ChildItem dist -Recurse -File | Measure-Object).Count    # 期望 ~422
```

**⚠️ 若 `npm ci` 失败**：先 `npm install`，再 `npm run build`。

### 步骤 2（可选）：跑一遍测试，确认前端没坏

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console
npm test               # 主控台的 node --test
cd simulation-3d
npm test               # 三维的 node --test
```

### 步骤 3：打包

```powershell
# 在 D:\ 下建一个干净的暂存目录
$stage = 'D:\UAVSwarm-Transfer-NEW'
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path "$stage\uavswarm" -Force | Out-Null

# 用 git 导出"干净源码"（不带 .git，且自动排除 .gitignore 的东西）
cd D:\2026UAVSwarm
git archive --format=tar HEAD | tar -x -C "$stage\uavswarm"

# 单独补上 git 里没有的东西
Copy-Item 'frontend\swarm-console\simulation-3d\dist' `
          "$stage\uavswarm\frontend\swarm-console\simulation-3d\dist" -Recurse -Force

# 再补 recon 脚本与 jetson 工具
Copy-Item 'ops\recon-offline-env.sh','ops\recon-windows.ps1' "$stage\uavswarm\ops\" -Force

# 生成校验清单
cd $stage
Get-ChildItem -Recurse -File | Get-FileHash -Algorithm SHA256 |
  ForEach-Object { "$($_.Hash.ToLower())  $($_.Path.Replace($stage+'\',''))" } |
  Set-Content -Encoding UTF8 SHA256SUMS.txt

# 记录基线提交
"commit ea4bf62 (main, 2026-10-12)" | Set-Content -Encoding UTF8 "$stage\SOURCE_COMMIT.txt"
```

**⚠️ 为什么用 `git archive` 而不是直接拷目录**：
它会**自动排除** `.git/`、`.runtime/`、`node_modules/` 等（因为它们被 gitignore），
**不会出现"拷了一半发现 1.6 GB 全是日志"的情况**。

### 步骤 4：压缩成便于搬运的形式

```powershell
cd D:\
tar -czf UAVSwarm-Transfer-NEW.tar.gz UAVSwarm-Transfer-NEW
# 或者用 7z/zip（但 tar.gz 保留行尾和权限位，对 .sh 更安全）
```

**预期大小**：源码 16.4 + dist 19 + wheelhouse 4.3 ≈ **40 MB**（压缩后更小）。

**⚠️ 别用记事本打开任何 `.sh`**（会把行尾变成 CRLF，脚本就废了）。**我们已经踩过这个坑两次。**

---

## 4. 离线机器上：安装与启动

### 4.1 前置（三台机器分别确认）

| 机器 | 需要什么 | 现状（据 recon） |
| --- | --- | --- |
| **中间笔记本**（DESKTOP-7T76KF3，Win10 1909） | **Python 3** ✅ 有（3.13.9）· **Firefox** ✅ 有 | 缺 Node（**不需要**，因为用 dist） |
| **华硕 Ubuntu 20.04** | `python3` + 浏览器 | ⏳ **未跑 recon** |
| **Jetson AGX Orin** | `python3` + 浏览器 | ⏳ **未跑 recon** |

### 4.2 主控台 5178（纯静态，最稳）

```powershell
cd <解压目录>\frontend\swarm-console
python -m http.server 5178 --bind 127.0.0.1 --directory .
```

浏览器打开 `http://127.0.0.1:5178/`

**Linux 上一样**：`python3 -m http.server 5178 --directory .`

### 4.3 三维控制台 5179

**两条路，选一条：**

**路 A（推荐，离线机器不需要 Node）** —— 用构建好的 `dist/`

```powershell
cd <解压目录>\frontend\swarm-console\simulation-3d
python -m http.server 5179 --bind 127.0.0.1 --directory dist
```

**路 B（要在现场改前端代码才用）** —— 需要 Node

```powershell
cd <解压目录>\frontend\swarm-console\simulation-3d
npm run dev            # 需要 node_modules（打包时带了 237 MB 才行）
```

> **注意**：项目自带的 `deployment\start-windows.ps1` / `start-linux.sh` 期望一个
> **`site\` 目录**（不是 `dist\`）。那是上次迁移的目录约定。**这次用 `dist\`，
> 所以那三个 deployment 脚本要么改路径、要么不用。**（`nginx.conf.example` 里
> `/api/` 已正确反代到 `127.0.0.1:8765`，可参考。）

### 4.4 Runtime 8765（**最大未知，建议这次先不装**）

**为什么不建议这次装**：

| 问题 | 说明 |
| --- | --- |
| **从未在 Windows 上跑过** | 它的启动方式含 Linux 专有假设（`setsid`、`PYTHONPATH="$PWD/src"`、`nohup`） |
| **README 要求 Python ≥3.10** | 中间笔记本有 **3.13.9** ✅，但**项目只在 3.10 上测过**，3.13 太新 |
| **没有真机可接** | 离线环境的真机接口还没确定（MAVLink？ROS？），装了也没数据 |
| **前端没有它也能显示** | 前端会显示"后端不可达"，但界面、三维、静态数据都能看 |

**结论**：**这次先把两个前端跑起来，确认浏览器与三维渲染没问题。**
Runtime 等第 5 节那几个问题回答清楚之后再单独做一轮。

---

## 5. 🔴 我还需要你确认的（会直接改变方案）

| # | 问题 | 为什么关键 |
| --- | --- | --- |
| **1** | **中间笔记本上 `D:\UAVSwarm` 是什么？跟 `D:\UAVSwarm-Transfer` 什么关系？** | 报告扫出这两个目录。**上次迁移是 8/21 版本**，可能与新的混在一起。**要不要先删旧的，避免版本混淆？** |
| **2** | **华硕那台的 GPU 是哪家？** | 决定三维视图能不能流畅。`lspci \| grep -i vga` |
| **3** | **Jetson：ROS1 还是 ROS2？NVMe 挂载了吗？** | `ls /opt/ros/` 和 `lsblk`。决定 Runtime 怎么接真机 |
| **4** | **真机跟 Runtime 怎么通信？MAVLink 还是 ROS？** | 决定要不要新写一个后端（**这是本轮最大的工作量**） |
| **5** | **联想 Windows 那台干什么用？** | 跑控制台？还是纯存储？ |
| **6** | **中间笔记本的 Firefox 版本 + WebGL 是否可用？** | `about:support` 看 `WebGL 1 Driver Renderer`。**这台是 Intel UHD 620 + 2018 年驱动，是三维渲染的主要风险点** |

---

## 6. 到离线机器后的验证清单（按顺序）

```
□ 1. 跑 ops/recon-offline-env.sh（Linux）或 ops/recon-windows.ps1（Windows）
     把报告带出来
□ 2. cd frontend/swarm-console && python -m http.server 5178
     Firefox 打开 http://127.0.0.1:5178/  → 主控台出现
□ 3. cd frontend/swarm-console/simulation-3d && python -m http.server 5179 --directory dist
     Firefox 打开 http://127.0.0.1:5179/  → 三维出现
     ⚠️ 若三维白屏或极卡 → about:support 看 WebGL，可能是 Intel 核显驱动太老
□ 4. 浏览器控制台（F12）看有没有报错，拍照带出来
□ 5. 记录：主控台/三维各自显示成什么样（拍照）
```

---

## 7. 已知风险（写在前面，免得现场慌）

| 风险 | 可能性 | 应对 |
| --- | --- | --- |
| **三维在 Intel UHD 620 上卡或白屏** | **中高** | 驱动是 2018 年的。可降低场景质量；或改用有独显的机器显示 |
| **Windows 10 1909 太老** | 中 | Edge 没有、系统 WebView 老。Firefox 是唯一选择，**确认它版本不太旧** |
| **`.sh` 被改成 CRLF** | 中 | 打包用 `tar.gz`；到机器上先 `file xxx.sh` 检查 |
| **Python 3.13 跑 Runtime 出兼容问题** | 中（若装 Runtime） | 本次不装；要用的话单独测 |
| **两个 `192.168.0.x` 网卡路由冲突** | 低 | 中间笔记本两个网口各有 2 个同段 IP，若连不通先禁用其一 |

---

## 8. 本次**不做**的事（明确划界）

* ❌ 不迁 `algorithm_lab` 的模型权重（3.8 GB，且离线环境暂无跑它的机器）
* ❌ 不迁 PX4 / Gazebo / 仿真栈
* ❌ 不迁 `.runtime/`（1.6 GB 运行产物）
* ❌ 不在离线环境跑 Runtime（等第 5 节的接口问题确定后单独一轮）
* ❌ 不做 Jetson 的 rootfs / NVMe 操作（等 recon 报告）

---

## 附：本方案涉及的命令速查

```powershell
# —— 本机（开发机，有网有 Node）——
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d
npm ci && npm run build

cd D:\2026UAVSwarm
git archive --format=tar HEAD | tar -x -C D:\UAVSwarm-Transfer-NEW\uavswarm
Copy-Item 'frontend\swarm-console\simulation-3d\dist' 'D:\UAVSwarm-Transfer-NEW\uavswarm\frontend\swarm-console\simulation-3d\dist' -Recurse
```

```bash
# —— 离线机器（Ubuntu）——
cd <解压目录>
bash ops/recon-offline-env.sh 2>&1 | tee ~/recon-$(date +%Y%m%d).txt
python3 -m http.server 5178 --directory frontend/swarm-console &
python3 -m http.server 5179 --directory frontend/swarm-console/simulation-3d/dist &
firefox http://127.0.0.1:5178/ http://127.0.0.1:5179/
```

```powershell
# —— 离线机器（Windows）——
powershell -NoProfile -ExecutionPolicy Bypass -File ops\recon-windows.ps1 *> recon-win.txt
cd frontend\swarm-console
python -m http.server 5178 --bind 127.0.0.1 --directory .
# 另一个窗口
cd frontend\swarm-console\simulation-3d
python -m http.server 5179 --bind 127.0.0.1 --directory dist
```
