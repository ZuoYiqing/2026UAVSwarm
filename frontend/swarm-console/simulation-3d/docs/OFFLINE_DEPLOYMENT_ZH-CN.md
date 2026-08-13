# UAVSwarm 三维仿真：安装、运行与离线部署手册

本文面向第一次接触本项目的使用者。按照本文操作，可以在联网开发机上安装和
构建 CesiumJS，也可以把构建结果部署到完全不能联网的 Windows、Linux 或 WSL
服务器。

## 1. 先理解三个不同的东西

### 1.1 CesiumJS

CesiumJS 是浏览器里的三维地球和地图渲染引擎。本项目通过 npm 安装：

```text
cesium 1.143.0
```

CesiumJS 只在浏览器前端使用。PX4、MAVLink 和仿真后端不需要安装 CesiumJS。

### 1.2 3D Tiles

3D Tiles 是三维地理数据格式。`tileset.json` 是入口文件，旁边的 `.glb`、
`.b3dm`、`.pnts` 等文件是实际模型或点云内容。

### 1.3 CesiumGS/3d-tiles-samples

`3d-tiles-samples-main.zip` 是示例数据，不是 CesiumJS 引擎。本项目使用的是用户
下载到下面位置的 ZIP：

```text
C:\Users\m1360\Downloads\3d-tiles-samples-main.zip
```

没有另外下载一份示例仓库。只从该 ZIP 复制了两组数据：

```text
1.1/MetadataGranularities
1.0/TilesetWithDiscreteLOD
```

它们现在位于：

```text
public/tiles/1.1/MetadataGranularities
public/tiles/1.0/TilesetWithDiscreteLOD
```

1.1 和 1.0 示例都只用于兼容性验证。默认展示的是项目本地构建的任务园区，没有把 ZIP
中所有测试数据放进项目，也没有修改原 ZIP。

## 2. 当前项目结构

```text
simulation-3d/
├─ deployment/               离线服务器启动脚本和 Nginx 示例
├─ docs/                     本手册
├─ public/
│  └─ tiles/                 本地 3D Tiles 1.0/1.1 数据
├─ scripts/
│  ├─ start-dev.ps1          Windows 后台启动开发服务
│  ├─ stop-dev.ps1           只停止上述开发服务
│  └─ package-offline.ps1    生成完整离线 ZIP
├─ src/
│  ├─ campus-scene.js        离线园区建筑群、道路、跑道和设施
│  ├─ demo-vehicle-feed.js   两分钟本地测试数据源
│  ├─ vehicle-contract.js    实时载具快照归一化和坐标转换
│  ├─ vehicle-layer.js       动态载具、轨迹、标牌和选择逻辑
│  ├─ main.js                Cesium 场景、外部 Bridge 和页面交互
│  └─ styles.css             三维页面样式
├─ index.html
├─ package.json
├─ package-lock.json
└─ vite.config.js
```

`node_modules/`、`dist/` 和生成的离线 ZIP 都不会提交到 Git。

## 3. 联网开发机首次安装

### 3.1 环境要求

- Windows 10/11 或 Linux；
- Node.js 22 或更高版本；
- npm；
- 推荐安装 Python 3，便于测试静态部署。

检查版本：

```powershell
node --version
npm --version
python --version
```

进入项目：

```powershell
cd D:\2026UAVSwarm\frontend\swarm-console\simulation-3d
```

仓库已有 `package-lock.json` 时，推荐使用：

```powershell
npm ci
```

`npm ci` 会严格按照锁文件安装 CesiumJS、Vite 和构建插件。不要手工复制其他
机器的 `node_modules`，尤其不要在 Windows 与 WSL 之间共用 `node_modules`。

如果在中国大陆且默认 npm 源无法连接，可以临时使用：

```powershell
npm ci --registry=https://registry.npmmirror.com
```

## 4. 开启和停止开发预览

### 4.1 最简单、最推荐：前台运行

进入项目目录后运行：

```powershell
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5179/
```

停止服务：回到运行该命令的终端，按：

```text
Ctrl+C
```

这种方式最容易理解，也最不容易遗留后台进程。

### 4.2 Windows 后台运行

在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1
```

停止这个后台服务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-dev.ps1
```

日志位置：

```text
.vite-dev.stdout.log
.vite-dev.stderr.log
```

脚本通过 `.vite-dev.pid` 记录它自己启动的进程，并使用进程树方式停止，不会按
名称结束机器上的所有 Node 进程。

### 4.3 端口占用

Windows 查看 5179 端口：

```powershell
netstat -ano | Select-String ":5179"
```

不要直接结束不认识的 PID。先确认它是否由本项目启动。使用本项目后台脚本启动
时，优先运行 `stop-dev.ps1`。

## 5. 构建生产静态文件

在联网开发机或已经完成依赖安装的构建机执行：

```powershell
npm run build
```

输出目录：

```text
dist/
```

`dist/` 已包含：

- 编译后的页面、JavaScript 和 CSS；
- Cesium Workers、Assets、Widgets 和 ThirdParty 文件；
- 3D Tiles 1.0/1.1 示例；
- 当前离线网格底图。

因此目标服务器只需提供普通 HTTP 静态文件服务，不需要 npm、Vite 或 Cesium
账号，也不需要访问互联网。

不能双击 `dist/index.html` 后通过 `file://` 使用。Cesium Workers 和 3D Tiles
必须通过 `http://` 或 `https://` 访问。

## 6. 一键生成离线部署 ZIP

在项目目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package-offline.ps1
```

脚本会：

1. 再运行一次 `npm run build`；
2. 将 `dist/` 放入离线包的 `site/`；
3. 加入 Windows/Linux 启动脚本；
4. 加入本文、Nginx 示例和 CesiumJS 许可证；
5. 生成：

```text
uavswarm-simulation-3d-offline.zip
uavswarm-simulation-3d-offline.zip.sha256
```

将这个 ZIP 通过公司允许的介质或文件传输流程送到离线服务器。目标服务器不需要
复制源码、`node_modules` 或用户下载目录里的原 ZIP。

转移后在 Windows 校验：

```powershell
Get-FileHash .\uavswarm-simulation-3d-offline.zip -Algorithm SHA256
Get-Content .\uavswarm-simulation-3d-offline.zip.sha256
```

两处哈希值必须一致。Linux 校验：

```bash
sha256sum -c uavswarm-simulation-3d-offline.zip.sha256
```

## 7. 离线 Windows 服务器部署

### 7.1 准备工作

在进入隔离网络前，确认目标机至少已有下面一种静态服务器：

- Python 3；
- IIS；
- Nginx；
- Apache。

若目标机不能联网，不要等进入隔离网络后再尝试下载安装 Python。

### 7.2 使用 Python 3

解压 `uavswarm-simulation-3d-offline.zip`，在解压目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-windows.ps1
```

本机访问：

```text
http://127.0.0.1:5179/
```

停止：在该终端按 `Ctrl+C`。

允许局域网其他机器访问时：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-windows.ps1 -Bind 0.0.0.0
```

然后访问：

```text
http://服务器IP:5179/
```

使用 `0.0.0.0` 会让服务监听所有网卡。必须遵守公司网络和防火墙要求。

## 8. 离线 Linux 或 WSL 服务器部署

解压 ZIP 后进入目录：

```bash
chmod +x start-linux.sh
./start-linux.sh
```

停止：按 `Ctrl+C`。

允许局域网访问：

```bash
BIND=0.0.0.0 PORT=5179 ./start-linux.sh
```

后台运行示例：

```bash
nohup env BIND=0.0.0.0 PORT=5179 ./start-linux.sh >server.log 2>&1 &
echo $! >server.pid
```

停止该后台服务：

```bash
kill "$(cat server.pid)"
```

只使用 `server.pid` 中记录的 PID，不要使用 `pkill python`，否则可能停止服务器上
其他 Python 服务。

## 9. 使用 Nginx 长期运行

离线包带有 `nginx.conf.example`。先把其中的路径：

```text
/opt/uavswarm-simulation-3d/site
```

改为实际 `site/` 绝对路径，再将 `server` 段合并到公司的 Nginx 配置。修改后：

```bash
nginx -t
```

检查通过后，由服务器管理员按照公司的变更流程重新加载 Nginx。

## 10. WSL 是否需要安装 CesiumJS

分两种情况：

1. 只在 WSL 运行 PX4、MAVLink 或仿真后端：不需要 CesiumJS；
2. 要在 WSL 内重新构建前端：进入本目录运行 `npm ci`，再运行
   `npm run build`。

Windows 和 WSL 应分别执行依赖安装，不要共用 `node_modules`。若使用已经生成的
离线 ZIP，WSL 只需 Python/Nginx 提供静态文件服务，不需要 Node/npm。

## 11. 当前地图是否真正离线

当前版本不调用 Cesium ion、在线卫星影像或在线地形：

- 地球表面使用 Cesium 本地网格；
- 3D Tiles 数据位于 `site/tiles/`；
- Cesium Workers 和资源位于 `site/cesium-static/`。

浏览器开发者工具中不应出现必须访问公网才能完成的资源请求。页面左下角的 Cesium
版权标识是运行时要求，并不表示当前场景正在从 Cesium ion 下载地图。

## 12. 后续替换成项目自己的地图

官方示例只用于确认 1.0/1.1 加载能力，不是正式仿真地图。正式数据应有自己的：

- `tileset.json`；
- `.glb`、`.b3dm`、`.pnts` 或其他内容文件；
- WGS84 场景原点；
- 数据许可证和来源说明。

保持原有目录关系，把完整 tileset 放入 `public/tiles/`，再修改
`src/main.js` 中的 `sceneDefinitions`。修改源码后必须重新运行：

```powershell
npm run build
```

PX4 本地坐标通常是 NED，Cesium 任务区使用 ENU/WGS84。接实时遥测时必须做：

```text
NED -> ENU -> WGS84/ECEF
```

## 13. 本次实际执行的主要命令

创建项目文件后，实际安装命令为：

```powershell
npm install cesium@1.143.0 --registry=https://registry.npmmirror.com --no-audit --no-fund
npm install --save-dev vite@7.0.6 vite-plugin-static-copy@3.1.1 --registry=https://registry.npmmirror.com --no-audit --no-fund
```

默认 npm 官方源第一次连接超时，所以改用镜像完成安装。依赖版本已经记录在
`package-lock.json`。

构建和运行命令：

```powershell
npm run build
npm run dev
```

示例数据没有通过 npm 下载。程序从用户已有
`C:\Users\m1360\Downloads\3d-tiles-samples-main.zip` 中选择性提取了前述两个
目录。

## 14. 部署后检查清单

- 页面通过 `http://` 或 `https://` 打开，不是 `file://`；
- 顶部显示 `任务园区 · READY`；
- 能看到建筑群、机库、跑道、停机坪、道路、树木和园区边界；
- 本地演示显示多旋翼、固定翼、垂直起降固定翼和无人车等动态平台；
- 可切换到 3D Tiles 1.1 和 1.0 兼容性场景；
- 播放、暂停、倍速、跟随、园区复位、航迹和标牌开关可用；
- 浏览器控制台没有 404、CORS 或 WebGL 错误；
- `site/cesium-static/`、`site/tiles/`、`site/contracts/` 没有遗漏；
- 离线 ZIP 的 SHA-256 与 `.sha256` 文件一致；
- 局域网访问时，服务器防火墙只开放经过批准的端口。

## 15. 常见故障

### 页面空白

确认不是双击 HTML，使用 Python、Nginx 或 IIS 通过 HTTP 打开。

### `cesium-static` 出现 404

离线包没有完整解压，或只复制了 `index.html`。必须复制整个 `site/`。

### 3D Tiles 出现 404

不要只复制 `tileset.json`。它引用的 `.glb`、`.b3dm` 和子目录必须保持原结构。

### WebGL 不可用

确认服务器访问端使用支持 WebGL 2 的浏览器和显卡驱动。远程桌面、安全策略或
虚拟机可能禁用硬件加速。

### 5179 端口被占用

换端口：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-windows.ps1 -Port 5180
```

或 Linux：

```bash
PORT=5180 ./start-linux.sh
```

## 16. 两分钟演示与实时数据

页面底部的 `02:00` 是浏览器内的本地测试数据源，不是视频文件，也不是 Gazebo/PX4
飞行脚本。它只用于后端尚未接入时验证混合机型、轨迹、选择、跟随和遥测显示。

正式运行时，主前端或运行时后端应按照下面的契约提供完整状态快照：

```text
docs/VEHICLE_FEED_CONTRACT_ZH-CN.md
public/contracts/vehicle-snapshot.schema.json
```

页面默认进入 `LIVE`，不会自动播放本地路径。平台数量、ID、类型、位置和 Agent 状态全部
以外部快照为准。只有点击 `DEMO` 或使用 `?mode=demo` 才会启用两分钟测试数据。

嵌入主控制台时，由主控制台统一获取快照并通过 `postMessage` 发送，三维页不会重复轮询。
独立运行时请求同源 `/api/vehicle-snapshot`：开发环境由 Vite 代理，长期部署使用离线包中的
`nginx.conf.example` 代理到 `127.0.0.1:8765`。仅用 Python 静态服务器时没有反向代理能力，
适合 DEMO 或由父页面传入快照，不适合作为独立 LIVE 的正式部署方案。
